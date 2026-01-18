"""Unit tests for planner module

Tests the Planner class which parses design files into tasks.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from demiurg.config import Config
from demiurg.planner import Planner
from demiurg.state import StateManager
from demiurg.types_ import TaskStatus, WorkState


@pytest.fixture
def config(tmp_path):
    """create test config"""
    return Config(
        num_planners=1,
        num_workers=1,
        target_dir=str(tmp_path),
        log_dir=str(tmp_path / ".demiurg" / "log"),
        data_dir=str(tmp_path / ".demiurg"),
        port=8080,
    )


@pytest.fixture
def state(tmp_path):
    """create test state manager"""
    return StateManager(str(tmp_path))


@pytest.fixture
def planner(config, state):
    """create planner instance"""
    return Planner(config, state)


@pytest.mark.asyncio
async def test_simple_parse_bullet_points(planner):
    """test simple parsing with bullet points"""
    goal = """
# My Project

- Create hello.py
- Add tests
- Write documentation
"""
    tasks = planner._simple_parse(goal)

    assert len(tasks) == 3
    assert tasks[0].description == "Create hello.py"
    assert tasks[1].description == "Add tests"
    assert tasks[2].description == "Write documentation"
    assert all(t.status is TaskStatus.PENDING for t in tasks)


@pytest.mark.asyncio
async def test_simple_parse_asterisks(planner):
    """test simple parsing with asterisks"""
    goal = """
* Task one
* Task two
"""
    tasks = planner._simple_parse(goal)

    assert len(tasks) == 2
    assert tasks[0].description == "Task one"
    assert tasks[1].description == "Task two"


@pytest.mark.asyncio
async def test_simple_parse_headings(planner):
    """test simple parsing with markdown headings"""
    goal = """
### Create module
### Add tests
"""
    tasks = planner._simple_parse(goal)

    assert len(tasks) == 2
    assert tasks[0].description == "Create module"
    assert tasks[1].description == "Add tests"


@pytest.mark.asyncio
async def test_simple_parse_empty(planner):
    """test simple parsing with empty goal creates fallback task"""
    goal = ""
    tasks = planner._simple_parse(goal)

    assert len(tasks) == 1
    assert tasks[0].description == ""


@pytest.mark.asyncio
async def test_simple_parse_long_goal(planner):
    """test simple parsing truncates long goals"""
    goal = "x" * 300
    tasks = planner._simple_parse(goal)

    assert len(tasks) == 1
    assert len(tasks[0].description) == 200


@pytest.mark.asyncio
async def test_simple_parse_ignores_comments(planner):
    """test simple parsing ignores comment lines"""
    goal = """
# This is a comment
- Task one
# Another comment
- Task two
"""
    tasks = planner._simple_parse(goal)

    assert len(tasks) == 2
    assert tasks[0].description == "Task one"


@pytest.mark.asyncio
async def test_simple_parse_ignores_short_lines(planner):
    """test simple parsing ignores lines shorter than 5 chars"""
    goal = """
- Hi
- This is a valid task
- OK
"""
    tasks = planner._simple_parse(goal)

    assert len(tasks) == 1
    assert tasks[0].description == "This is a valid task"


@pytest.mark.asyncio
async def test_parse_tasks_claude_success(planner):
    """test _parse_tasks with successful Claude response"""
    goal = "Create a web server"

    # mock Claude response
    claude_response = json.dumps([
        {"description": "Create server.py", "priority": "high", "estimated_complexity": "moderate"},
        {"description": "Add routing logic", "priority": "medium", "estimated_complexity": "simple"},
    ])

    planner.claude.execute = AsyncMock(return_value=claude_response)

    tasks = await planner._parse_tasks(goal)

    assert len(tasks) == 2
    assert tasks[0].description == "Create server.py"
    assert tasks[1].description == "Add routing logic"
    assert all(t.status is TaskStatus.PENDING for t in tasks)


@pytest.mark.asyncio
async def test_parse_tasks_claude_invalid_json(planner):
    """test _parse_tasks falls back on invalid JSON"""
    goal = "- Fallback task"

    planner.claude.execute = AsyncMock(return_value="not json")

    tasks = await planner._parse_tasks(goal)

    # should fall back to simple parsing
    assert len(tasks) == 1
    assert tasks[0].description == "Fallback task"


@pytest.mark.asyncio
async def test_parse_tasks_claude_not_array(planner):
    """test _parse_tasks falls back when response is not array"""
    goal = "- Fallback task"

    planner.claude.execute = AsyncMock(return_value='{"not": "an array"}')

    tasks = await planner._parse_tasks(goal)

    assert len(tasks) == 1
    assert tasks[0].description == "Fallback task"


@pytest.mark.asyncio
async def test_parse_tasks_claude_empty_array(planner):
    """test _parse_tasks falls back on empty array"""
    goal = "- Fallback task"

    planner.claude.execute = AsyncMock(return_value="[]")

    tasks = await planner._parse_tasks(goal)

    assert len(tasks) == 1
    assert tasks[0].description == "Fallback task"


@pytest.mark.asyncio
async def test_parse_tasks_claude_timeout(planner):
    """test _parse_tasks falls back on timeout"""
    goal = "- Fallback task"

    planner.claude.execute = AsyncMock(side_effect=RuntimeError("timeout"))

    tasks = await planner._parse_tasks(goal)

    assert len(tasks) == 1
    assert tasks[0].description == "Fallback task"


@pytest.mark.asyncio
async def test_plan_once_no_work(planner, state):
    """test plan_once returns empty list when no work state"""
    tasks = await planner.plan_once()

    assert tasks == []


@pytest.mark.asyncio
async def test_plan_once_with_work(planner, state):
    """test plan_once creates tasks from work state"""
    # set up work state
    await state.init_work("test.txt", "- Task one\n- Task two")

    # mock Claude to use simple parsing
    planner.claude.execute = AsyncMock(side_effect=RuntimeError("force fallback"))

    tasks = await planner.plan_once()

    assert len(tasks) == 2
    assert tasks[0].description == "Task one"
    assert tasks[1].description == "Task two"

    # verify tasks were added to state
    all_tasks = await state.get_all_tasks()
    assert len(all_tasks) == 2


@pytest.mark.asyncio
async def test_plan_once_integration(planner, state):
    """integration test: plan_once with Claude CLI"""
    await state.init_work("test.txt", """
Create a simple Python calculator with:
- Add function
- Subtract function
- Multiply function
- Divide function with zero check
""")

    # this will actually call Claude CLI if available
    tasks = await planner.plan_once()

    # should get at least the 4 functions as tasks
    assert len(tasks) >= 4

    # verify all tasks are pending
    assert all(t.status is TaskStatus.PENDING for t in tasks)

    # verify tasks were persisted
    all_tasks = await state.get_all_tasks()
    assert len(all_tasks) == len(tasks)
