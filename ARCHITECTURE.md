# architecture

## overview

ship implements the planner-worker-judge pattern from
[cursor's blog post](https://cursor.com/blog/scaling-agents)
on scaling autonomous coding agents. goal-oriented execution:
runs until satisfied, then exits.

```
SPEC.md -> Validator -> Planner -> [task, task, task] -> Queue
                                                          |
                                  Worker <- Worker <- Worker <- Worker
                                                          |
                                                     State (JSON)
                                                          |
                              Judge -> Refiner -> Replanner -> exit
```

## components

### validator (`validator.py`)

checks design quality before planning. uses claude CLI to assess
whether the spec is specific enough to execute. rejects vague
designs to REJECTION.md with actionable gaps. accepted designs
produce PROJECT.md with a brief project summary.

### planner (`planner.py`)

reads design, breaks into tasks using claude code CLI. runs once
at startup. generates tasks with uuid, description, empty files
list, and pending status. falls back to line-based parsing if
JSON parsing fails. adds tasks to state and submits to queue.

### queue

asyncio.Queue holding pending tasks. unbounded. workers block on
queue.get(). not persisted -- regenerated from state on
continuation (`-c`).

### worker (`worker.py`)

fetches tasks from queue, executes via claude CLI, updates state.

each worker gets its own unique session ID (uuid4). the session
persists across tasks within the same worker via `--resume`,
giving the worker memory of previous work without collisions
between workers.

execution:
1. mark task as running
2. stream output from `claude -p <prompt> --model sonnet`
3. detect "reached max turns" in output -> mark failed
4. otherwise mark completed with output

workers run independently -- no inter-worker communication.
skills from `~/.claude/skills/` are loaded once at init and
injected into every task prompt.

### judge (`judge.py`)

three-level assessment: narrow, medium, wide.

polls state every 5s. on each cycle:
- **narrow**: judges each newly completed task individually
  (asks LLM "did this task actually work?")
- retries failed tasks (up to 10 times)
- when all tasks complete:
  - **medium**: refiner creates follow-up tasks (up to 10 rounds)
  - **wide**: replanner does full project assessment (up to 1 round)
- if no new tasks from either, marks work complete and exits

updates TUI status line and writes PROGRESS.md on each poll.

### refiner (`refiner.py`)

uses codex CLI (not claude) to critique the batch. reads
PROGRESS.md and task state, outputs `<task>...</task>` blocks
for follow-up work. up to 10 refinement rounds per run.

### replanner (`replanner.py`)

full project assessment against the original goal using claude
CLI. reads PLAN.md, PROGRESS.md, and task state. fires only
after refiner finds nothing. up to 1 replan round per run.

### state manager (`state.py`)

persists to `.ship/` as JSON:
- `tasks.json`: all tasks with metadata
- `work.json`: design_file, goal_text, is_complete, project_context

asyncio.Lock protects concurrent access. state mutations: lock
before read/write, save() under lock, copy before return.

### claude code client (`claude_code.py`)

wrapper around `claude` CLI subprocess. supports buffered and
streaming modes.

session reuse: accepts a session_id. first call uses
`--session-id`, subsequent calls use `--resume`. each component
(validator, planner, each worker, judge, replanner) gets its own
session_id to avoid collisions.

on timeout: kills subprocess. on cancellation (CancelledError):
kills subprocess and re-raises. traces all calls to
`.ship/log/trace.jl` (jsonlines).

runs with `--permission-mode bypassPermissions` and a whitelist
of common dev tools (bash commands, file operations).

## data flow

1. `main()` parses args, handles SIGINT/SIGTERM
2. new run:
   - validator assesses spec -> reject or accept
   - planner generates tasks from spec + PROJECT.md
   - state.init_work() creates work state
3. continuation (`-c`):
   - state.reset_interrupted_tasks() resets running -> pending
4. populate queue from pending tasks
5. spawn workers (one asyncio task each, capped to pending count)
6. workers pull from queue, execute, notify judge on completion
7. judge polls every 5s:
   - judges completed tasks, retries failures
   - refines when batch complete, replans if refiner empty
   - exits when satisfied
8. main cancels workers, gathers, prints summary

## task lifecycle

states (enum in `types_.py`):
- pending: created, not yet started
- running: worker executing
- completed: finished successfully
- failed: error during execution

transitions:
- pending -> running (worker picks up)
- running -> completed (worker success)
- running -> failed (error, timeout, max turns)
- failed -> pending (judge retry, up to 10 times)
- running -> pending (continuation after interruption)

## concurrency

all components run as asyncio tasks from main.

- queue: asyncio.Queue (no locks needed)
- state: asyncio.Lock
- workers: independent, no coordination
- judge: reads state, receives completion notifications
- each worker/component owns its own claude CLI session

shutdown: judge exits -> main cancels workers -> gather with
return_exceptions=True. SIGINT and SIGTERM both raise
KeyboardInterrupt. CancelledError in workers/client kills child
subprocesses before propagating.

## configuration

precedence: CLI args > env vars > .env file > defaults

defaults:
- num_workers: 4
- max_turns: 25
- task_timeout: 1200s
- log_dir: .ship/log
- data_dir: .ship

## file layout

```
ship/
  __main__.py    - entry point, click CLI, orchestration
  types_.py      - Task, TaskStatus, WorkState
  state.py       - StateManager with asyncio.Lock
  config.py      - loads .env + env vars
  claude_code.py - claude CLI wrapper
  codex_cli.py   - codex CLI wrapper
  planner.py     - design -> tasks
  validator.py   - design quality check
  worker.py      - task execution
  judge.py       - completion monitoring + refinement
  refiner.py     - codex-based follow-up tasks
  replanner.py   - full reassessment
  prompts.py     - all LLM prompt templates
  skills.py      - loads ~/.claude/skills/
  display.py     - TUI output + status line
```

runtime state (`.ship/`, gitignored):
- tasks.json, work.json
- log/ship.log, log/trace.jl

project root (LLM-visible):
- SPEC.md, PLAN.md, PROGRESS.md, LOG.md, PROJECT.md
