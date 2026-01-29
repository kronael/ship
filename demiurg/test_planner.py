"""Unit tests for planner module

Tests the Planner class which parses design files into tasks using Claude.
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from demiurg.config import Config
from demiurg.planner import Planner
from demiurg.state import StateManager
from demiurg.types_ import TaskStatus


@pytest.fixture
def config(tmp_path):
    """create test config"""
    return Config(
        num_workers=1,
        log_dir=str(tmp_path / ".demiurg" / "log"),
        data_dir=str(tmp_path / ".demiurg"),
        max_turns=5,
        task_timeout=120,
    )


@pytest.fixture
def state(tmp_path):
    """create test state manager"""
    return StateManager(str(tmp_path))


@pytest.fixture
def planner(config, state):
    """create planner instance"""
    return Planner(config, state)


def test_parse_xml_basic(planner):
    """test XML parsing with valid response"""
    xml = """<tasks>
<task>Create main.go</task>
<task>Add HTTP server</task>
</tasks>"""

    tasks = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[0].description == "Create main.go"
    assert tasks[1].description == "Add HTTP server"
    assert all(t.status is TaskStatus.PENDING for t in tasks)


def test_parse_xml_with_whitespace(planner):
    """test XML parsing handles whitespace"""
    xml = """
    <tasks>
        <task>  Create main.go  </task>
        <task>
            Add HTTP server
        </task>
    </tasks>
    """

    tasks = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[0].description == "Create main.go"
    assert tasks[1].description == "Add HTTP server"


def test_parse_xml_empty(planner):
    """test XML parsing with no tasks"""
    xml = "<tasks></tasks>"

    tasks = planner._parse_xml(xml)

    assert len(tasks) == 0


def test_parse_xml_ignores_short(planner):
    """test XML parsing ignores short descriptions"""
    xml = """<tasks>
<task>Hi</task>
<task>Create a valid task</task>
</tasks>"""

    tasks = planner._parse_xml(xml)

    assert len(tasks) == 1
    assert tasks[0].description == "Create a valid task"


def test_parse_xml_with_noise(planner):
    """test XML parsing extracts tasks from noisy response"""
    xml = """Here are the tasks:

<tasks>
<task>Create main.go</task>
</tasks>

Let me know if you need more."""

    tasks = planner._parse_xml(xml)

    assert len(tasks) == 1
    assert tasks[0].description == "Create main.go"


@pytest.mark.asyncio
async def test_parse_tasks_success(planner):
    """test _parse_tasks with successful Claude response"""
    goal = "Create a web server"

    xml_response = """<tasks>
<task>Create server.go with main function</task>
<task>Add HTTP handler for /health endpoint</task>
</tasks>"""

    planner.claude.execute = AsyncMock(return_value=xml_response)

    tasks = await planner._parse_tasks(goal)

    assert len(tasks) == 2
    assert tasks[0].description == "Create server.go with main function"
    assert tasks[1].description == "Add HTTP handler for /health endpoint"


@pytest.mark.asyncio
async def test_parse_tasks_claude_failure(planner):
    """test _parse_tasks returns empty on Claude failure"""
    goal = "Create a web server"

    planner.claude.execute = AsyncMock(side_effect=RuntimeError("timeout"))

    tasks = await planner._parse_tasks(goal)

    assert len(tasks) == 0


@pytest.mark.asyncio
async def test_plan_once_no_work(planner, state):
    """test plan_once returns empty list when no work state"""
    tasks = await planner.plan_once()

    assert tasks == []


@pytest.mark.asyncio
async def test_plan_once_with_work(planner, state):
    """test plan_once creates tasks from work state"""
    await state.init_work("test.txt", "Create a hello world app")

    xml_response = """<tasks>
<task>Create hello.py with main function</task>
<task>Add print statement</task>
</tasks>"""

    planner.claude.execute = AsyncMock(return_value=xml_response)

    tasks = await planner.plan_once()

    assert len(tasks) == 2
    assert tasks[0].description == "Create hello.py with main function"

    # verify tasks were added to state
    all_tasks = await state.get_all_tasks()
    assert len(all_tasks) == 2
