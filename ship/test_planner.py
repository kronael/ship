"""Unit tests for planner, worker parse, state cascade"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from ship.config import Config
from ship.judge import is_cascade_error
from ship.planner import Planner
from ship.state import StateManager
from ship.types_ import Task
from ship.types_ import TaskStatus
from ship.worker import Worker


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

    planner.claude.execute = AsyncMock(
        return_value=(xml_response, "sess-1")
    )

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

    planner.claude.execute = AsyncMock(
        return_value=(xml_response, "sess-2")
    )

    tasks = await planner.plan_once()

    assert len(tasks) == 2
    assert tasks[0].description == "Create hello.py with main function"

    all_tasks = await state.get_all_tasks()
    assert len(all_tasks) == 2


# -- dependency parsing tests --


def test_parse_xml_with_depends(planner):
    xml = """<project>
<context>test</context>
<tasks>
<task>Setup project</task>
<task depends="1">Build feature A</task>
<task depends="1,2">Write tests</task>
</tasks>
</project>"""

    context, tasks = planner._parse_xml(xml)

    assert len(tasks) == 3
    assert tasks[0].depends_on == []
    assert tasks[1].depends_on == [tasks[0].id]
    assert tasks[2].depends_on == [tasks[0].id, tasks[1].id]


def test_parse_xml_depends_out_of_range(planner):
    xml = """<tasks>
<task depends="99">Build feature</task>
<task>Another task</task>
</tasks>"""

    _, tasks = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[0].depends_on == []


def test_parse_xml_depends_self_reference(planner):
    xml = """<tasks>
<task depends="1">Build feature</task>
</tasks>"""

    _, tasks = planner._parse_xml(xml)

    assert len(tasks) == 1
    assert tasks[0].depends_on == []


def test_parse_xml_depends_with_spaces(planner):
    xml = """<tasks>
<task>First task here</task>
<task depends=" 1 ">Depends on first</task>
</tasks>"""

    _, tasks = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[1].depends_on == [tasks[0].id]


def test_parse_xml_depends_non_numeric(planner):
    xml = """<tasks>
<task>First task here</task>
<task depends="abc">Bad depends</task>
</tasks>"""

    _, tasks = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[1].depends_on == []


# -- cascade_failure tests --


@pytest.mark.asyncio
async def test_cascade_failure_direct(tmp_path):
    state = StateManager(str(tmp_path))
    a = Task(
        id="aaa", description="task A",
        files=[], status=TaskStatus.FAILED,
    )
    b = Task(
        id="bbb", description="task B",
        files=[], status=TaskStatus.PENDING,
        depends_on=["aaa"],
    )
    await state.add_task(a)
    await state.add_task(b)

    cascaded = await state.cascade_failure("aaa")

    assert cascaded == ["bbb"]
    all_tasks = await state.get_all_tasks()
    b_task = [t for t in all_tasks if t.id == "bbb"][0]
    assert b_task.status is TaskStatus.FAILED
    assert is_cascade_error(b_task.error)


@pytest.mark.asyncio
async def test_cascade_failure_recursive(tmp_path):
    """A->B->C: failing A should cascade to both B and C"""
    state = StateManager(str(tmp_path))
    a = Task(
        id="aaa", description="task A",
        files=[], status=TaskStatus.FAILED,
    )
    b = Task(
        id="bbb", description="task B",
        files=[], status=TaskStatus.PENDING,
        depends_on=["aaa"],
    )
    c = Task(
        id="ccc", description="task C",
        files=[], status=TaskStatus.PENDING,
        depends_on=["bbb"],
    )
    await state.add_task(a)
    await state.add_task(b)
    await state.add_task(c)

    cascaded = await state.cascade_failure("aaa")

    assert "bbb" in cascaded
    assert "ccc" in cascaded
    all_tasks = await state.get_all_tasks()
    for t in all_tasks:
        if t.id in ("bbb", "ccc"):
            assert t.status is TaskStatus.FAILED


@pytest.mark.asyncio
async def test_cascade_skips_completed(tmp_path):
    state = StateManager(str(tmp_path))
    a = Task(
        id="aaa", description="task A",
        files=[], status=TaskStatus.FAILED,
    )
    b = Task(
        id="bbb", description="task B (already done)",
        files=[], status=TaskStatus.COMPLETED,
        depends_on=["aaa"],
    )
    await state.add_task(a)
    await state.add_task(b)

    cascaded = await state.cascade_failure("aaa")
    assert cascaded == []


# -- worker parse_output tests --


def test_parse_output_done(config, state):
    w = Worker("w0", config, state)
    status, followups = w._parse_output(
        "did some work\n<status>done</status>"
    )
    assert status == "done"
    assert followups == []


def test_parse_output_partial_with_followups(config, state):
    w = Worker("w0", config, state)
    text = (
        "could not finish\n"
        "<status>partial</status>\n"
        "<followups>\n"
        "<task>finish the remaining API</task>\n"
        "<task>add error handling</task>\n"
        "</followups>"
    )
    status, followups = w._parse_output(text)
    assert status == "partial"
    assert len(followups) == 2
    assert followups[0] == "finish the remaining API"


def test_parse_output_no_tags(config, state):
    w = Worker("w0", config, state)
    status, followups = w._parse_output("just plain text")
    assert status == "done"
    assert followups == []


def test_parse_output_empty_followups(config, state):
    w = Worker("w0", config, state)
    text = (
        "<status>partial</status>\n"
        "<followups>\n"
        "</followups>"
    )
    status, followups = w._parse_output(text)
    assert status == "partial"
    assert followups == []


# -- is_cascade_error tests --


def test_is_cascade_error():
    assert is_cascade_error("cascade: dependency aaa failed")
    assert not is_cascade_error("some other error")
    assert not is_cascade_error("")
    assert not is_cascade_error("Cascade: wrong case")
