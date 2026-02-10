"""Unit tests for planner module"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ship.config import Config
from ship.planner import Planner
from ship.state import StateManager
from ship.types_ import TaskStatus


@pytest.fixture
def config(tmp_path):
    return Config(
        num_workers=1,
        log_dir=str(tmp_path / ".ship" / "log"),
        data_dir=str(tmp_path / ".ship"),
        max_turns=5,
        task_timeout=120,
        verbose=False,
    )


@pytest.fixture
def state(tmp_path):
    return StateManager(str(tmp_path))


@pytest.fixture
def planner(config, state):
    return Planner(config, state)


def test_parse_xml_basic(planner):
    xml = """<tasks>
<task>Create main.go</task>
<task>Add HTTP server</task>
</tasks>"""

    context, tasks = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[0].description == "Create main.go"
    assert tasks[1].description == "Add HTTP server"
    assert all(t.status is TaskStatus.PENDING for t in tasks)


def test_parse_xml_with_whitespace(planner):
    xml = """
    <tasks>
        <task>  Create main.go  </task>
        <task>
            Add HTTP server
        </task>
    </tasks>
    """

    context, tasks = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[0].description == "Create main.go"
    assert tasks[1].description == "Add HTTP server"


def test_parse_xml_empty(planner):
    context, tasks = planner._parse_xml("<tasks></tasks>")
    assert len(tasks) == 0


def test_parse_xml_ignores_short(planner):
    xml = """<tasks>
<task>Hi</task>
<task>Create a valid task</task>
</tasks>"""

    context, tasks = planner._parse_xml(xml)

    assert len(tasks) == 1
    assert tasks[0].description == "Create a valid task"


def test_parse_xml_with_noise(planner):
    xml = """Here are the tasks:

<tasks>
<task>Create main.go</task>
</tasks>

Let me know if you need more."""

    context, tasks = planner._parse_xml(xml)

    assert len(tasks) == 1
    assert tasks[0].description == "Create main.go"


def test_parse_xml_with_context(planner):
    xml = """<project>
<context>Go web server with REST API</context>
<tasks>
<task>Create main.go</task>
</tasks>
</project>"""

    context, tasks = planner._parse_xml(xml)

    assert context == "Go web server with REST API"
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_parse_design_success(planner):
    goal = "Create a web server"

    xml_response = """<project>
<context>Go web server</context>
<tasks>
<task>Create server.go with main function</task>
<task>Add HTTP handler for /health endpoint</task>
</tasks>
</project>"""

    planner.claude.execute = AsyncMock(return_value=xml_response)

    context, tasks = await planner._parse_design(goal)

    assert context == "Go web server"
    assert len(tasks) == 2
    assert tasks[0].description == "Create server.go with main function"


@pytest.mark.asyncio
async def test_parse_design_claude_failure(planner):
    goal = "Create a web server"
    planner.claude.execute = AsyncMock(side_effect=RuntimeError("timeout"))

    context, tasks = await planner._parse_design(goal)

    assert context == ""
    assert len(tasks) == 0


@pytest.mark.asyncio
async def test_plan_once_no_work(planner, state):
    tasks = await planner.plan_once()
    assert tasks == []


@pytest.mark.asyncio
async def test_plan_once_with_work(planner, state):
    await state.init_work("test.txt", "Create a hello world app")

    xml_response = """<project>
<context>Python hello world</context>
<tasks>
<task>Create hello.py with main function</task>
<task>Add print statement</task>
</tasks>
</project>"""

    planner.claude.execute = AsyncMock(return_value=xml_response)

    tasks = await planner.plan_once()

    assert len(tasks) == 2
    assert tasks[0].description == "Create hello.py with main function"

    all_tasks = await state.get_all_tasks()
    assert len(all_tasks) == 2
