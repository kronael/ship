"""Unit tests for planner, worker parse, state cascade, adversarial"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from ship.config import Config
from ship.judge import Judge
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
        verbosity=1,
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

    context, tasks, _ = planner._parse_xml(xml)

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

    context, tasks, _ = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[0].description == "Create main.go"
    assert tasks[1].description == "Add HTTP server"


def test_parse_xml_empty(planner):
    context, tasks, _ = planner._parse_xml("<tasks></tasks>")
    assert len(tasks) == 0


def test_parse_xml_ignores_short(planner):
    xml = """<tasks>
<task>Hi</task>
<task>Create a valid task</task>
</tasks>"""

    context, tasks, _ = planner._parse_xml(xml)

    assert len(tasks) == 1
    assert tasks[0].description == "Create a valid task"


def test_parse_xml_with_noise(planner):
    xml = """Here are the tasks:

<tasks>
<task>Create main.go</task>
</tasks>

Let me know if you need more."""

    context, tasks, _ = planner._parse_xml(xml)

    assert len(tasks) == 1
    assert tasks[0].description == "Create main.go"


def test_parse_xml_with_context(planner):
    xml = """<project>
<context>Go web server with REST API</context>
<tasks>
<task>Create main.go</task>
</tasks>
</project>"""

    context, tasks, _ = planner._parse_xml(xml)

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

    context, tasks, _ = await planner._parse_design(goal)

    assert context == "Go web server"
    assert len(tasks) == 2
    assert tasks[0].description == "Create server.go with main function"


@pytest.mark.asyncio
async def test_parse_design_claude_failure(planner):
    goal = "Create a web server"
    planner.claude.execute = AsyncMock(side_effect=RuntimeError("timeout"))

    context, tasks, _ = await planner._parse_design(goal)

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

    context, tasks, _ = planner._parse_xml(xml)

    assert len(tasks) == 3
    assert tasks[0].depends_on == []
    assert tasks[1].depends_on == [tasks[0].id]
    assert tasks[2].depends_on == [tasks[0].id, tasks[1].id]


def test_parse_xml_depends_out_of_range(planner):
    xml = """<tasks>
<task depends="99">Build feature</task>
<task>Another task</task>
</tasks>"""

    _, tasks, _ = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[0].depends_on == []


def test_parse_xml_depends_self_reference(planner):
    xml = """<tasks>
<task depends="1">Build feature</task>
</tasks>"""

    _, tasks, _ = planner._parse_xml(xml)

    assert len(tasks) == 1
    assert tasks[0].depends_on == []


def test_parse_xml_depends_with_spaces(planner):
    xml = """<tasks>
<task>First task here</task>
<task depends=" 1 ">Depends on first</task>
</tasks>"""

    _, tasks, _ = planner._parse_xml(xml)

    assert len(tasks) == 2
    assert tasks[1].depends_on == [tasks[0].id]


def test_parse_xml_depends_non_numeric(planner):
    xml = """<tasks>
<task>First task here</task>
<task depends="abc">Bad depends</task>
</tasks>"""

    _, tasks, _ = planner._parse_xml(xml)

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


# -- adversarial verification tests --


def _make_judge(tmp_path, session_id="test-sess"):
    state = StateManager(str(tmp_path))
    queue = asyncio.Queue()
    return Judge(
        state=state,
        queue=queue,
        project_context="test project",
        session_id=session_id,
    )


def test_parse_challenges(tmp_path):
    j = _make_judge(tmp_path)
    text = (
        "<challenges>\n"
        "<challenge>Verify that X works</challenge>\n"
        "<challenge>Check that Y handles Z</challenge>\n"
        "<challenge>  </challenge>\n"
        "</challenges>"
    )
    result = j._parse_challenges(text)
    assert len(result) == 2
    assert result[0] == "Verify that X works"
    assert result[1] == "Check that Y handles Z"


def test_parse_challenges_empty(tmp_path):
    j = _make_judge(tmp_path)
    assert j._parse_challenges("no tags here") == []
    assert j._parse_challenges(
        "<challenges></challenges>"
    ) == []


@pytest.mark.asyncio
async def test_check_adv_batch_pending(tmp_path):
    j = _make_judge(tmp_path)
    await j.state.init_work("test.txt", "build something")

    task = Task(
        id="adv-1", description="Verify X",
        files=[], status=TaskStatus.PENDING,
    )
    await j.state.add_task(task)
    j._adv_task_ids = {"adv-1"}

    result = await j._check_adv_batch()
    assert result == "pending"


@pytest.mark.asyncio
async def test_check_adv_batch_pass(tmp_path):
    j = _make_judge(tmp_path)
    await j.state.init_work("test.txt", "build something")

    task = Task(
        id="adv-1", description="Verify X",
        files=[], status=TaskStatus.COMPLETED,
    )
    await j.state.add_task(task)
    j._adv_task_ids = {"adv-1"}

    result = await j._check_adv_batch()
    assert result == "pass"


@pytest.mark.asyncio
async def test_check_adv_batch_fail(tmp_path):
    j = _make_judge(tmp_path)
    await j.state.init_work("test.txt", "build something")

    t1 = Task(
        id="adv-1", description="Verify X",
        files=[], status=TaskStatus.COMPLETED,
    )
    t2 = Task(
        id="adv-2", description="Check Y",
        files=[], status=TaskStatus.FAILED,
        error="verification failed",
    )
    await j.state.add_task(t1)
    await j.state.add_task(t2)
    j._adv_task_ids = {"adv-1", "adv-2"}

    result = await j._check_adv_batch()
    assert result == "fail"


@pytest.mark.asyncio
async def test_run_adversarial_round(tmp_path):
    j = _make_judge(tmp_path)
    await j.state.init_work("test.txt", "build a web app")

    challenges_xml = (
        "<challenges>\n"
        "<challenge>Verify the server starts</challenge>\n"
        "<challenge>Check error handling works</challenge>\n"
        "<challenge>Verify tests pass cleanly</challenge>\n"
        "</challenges>"
    )

    with patch.object(
        j, "_run_adversarial_round",
        wraps=j._run_adversarial_round,
    ):
        with patch(
            "ship.judge.ClaudeCodeClient"
        ) as mock_cls:
            mock_client = AsyncMock()
            mock_client.execute = AsyncMock(
                return_value=(challenges_xml, "")
            )
            mock_cls.return_value = mock_client

            await j._run_adversarial_round()

    assert len(j._adv_task_ids) == 2
    all_tasks = await j.state.get_all_tasks()
    adv_tasks = [
        t for t in all_tasks
        if t.id in j._adv_task_ids
    ]
    assert len(adv_tasks) == 2
    assert all(
        t.status is TaskStatus.PENDING for t in adv_tasks
    )


@pytest.mark.asyncio
async def test_adv_fail_resets_counts(tmp_path):
    j = _make_judge(tmp_path)
    j.adv_round = 2
    j.refine_count = 5
    j.replan_count = 1

    t = Task(
        id="adv-1", description="Check X",
        files=[], status=TaskStatus.FAILED,
        error="found a bug",
    )
    await j.state.add_task(t)
    j._adv_task_ids = {"adv-1"}

    outcome = await j._check_adv_batch()
    assert outcome == "fail"

    # simulate the reset the run() loop would do
    j._adv_task_ids.clear()
    j.adv_round = 0
    j.refine_count = 0
    j.replan_count = 0

    assert j.adv_round == 0
    assert j.refine_count == 0
    assert j.replan_count == 0


@pytest.mark.asyncio
async def test_adv_init_fields(tmp_path):
    j = _make_judge(tmp_path)
    assert j.adv_round == 0
    assert j.max_adv_rounds == 3
    assert j._adv_task_ids == set()
    assert j._adv_attempts == 0
    assert j.max_adv_attempts == 3
    assert j._seen_challenges == set()


@pytest.mark.asyncio
async def test_adv_round_dedup(tmp_path):
    """seen challenges are filtered in subsequent rounds"""
    j = _make_judge(tmp_path)
    await j.state.init_work("test.txt", "build a web app")

    challenges_xml = (
        "<challenges>\n"
        "<challenge>Verify the server starts</challenge>\n"
        "<challenge>Check error handling works</challenge>\n"
        "<challenge>Verify tests pass cleanly</challenge>\n"
        "</challenges>"
    )

    with patch(
        "ship.judge.ClaudeCodeClient"
    ) as mock_cls:
        mock_client = AsyncMock()
        mock_client.execute = AsyncMock(
            return_value=(challenges_xml, "")
        )
        mock_cls.return_value = mock_client

        # first round picks 2
        gave_up = await j._run_adversarial_round()
        assert not gave_up
        assert len(j._adv_task_ids) == 2
        first_seen = set(j._seen_challenges)
        assert len(first_seen) == 2

        # second round: same challenges, only 1 novel
        j._adv_task_ids.clear()
        gave_up = await j._run_adversarial_round()
        assert not gave_up
        assert len(j._adv_task_ids) == 1
        assert len(j._seen_challenges) == 3


@pytest.mark.asyncio
async def test_adv_max_attempts(tmp_path):
    """stops after max_adv_attempts failures"""
    j = _make_judge(tmp_path)
    await j.state.init_work("test.txt", "build something")
    j._adv_attempts = 3  # already at max

    gave_up = await j._run_adversarial_round()
    assert gave_up is True


@pytest.mark.asyncio
async def test_check_adv_batch_missing_tasks(tmp_path):
    """returns pending when not all adv tasks found"""
    j = _make_judge(tmp_path)
    await j.state.init_work("test.txt", "build something")

    # add one task but reference two IDs
    task = Task(
        id="adv-1", description="Verify X",
        files=[], status=TaskStatus.COMPLETED,
    )
    await j.state.add_task(task)
    j._adv_task_ids = {"adv-1", "adv-missing"}

    result = await j._check_adv_batch()
    assert result == "pending"
