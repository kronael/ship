# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

autonomous agent orchestration implementing cursor's planner-worker-judge pattern for goal-oriented code generation.

## build and run

```bash
make build              # uv sync (install deps)
make install            # install as uv tool
make test               # pytest
make right              # pyright + pytest
make clean              # remove cache and state
```

run from git:
```bash
uvx github.com/kronael/demiurg design.txt
```

run locally:
```bash
demiurg design.txt      # new run
demiurg -c              # continue from last run
```

## critical patterns

### enum checking
```python
if task.status is TaskStatus.PENDING:  # use 'is' not ==
```

### state mutations
- ALWAYS acquire lock before reading/writing state
- ALWAYS call save() while holding write lock
- ALWAYS copy data structures before returning (prevent mutation)

### config loading
- loads from ./.env if exists (via python-dotenv)
- environment variables override .env settings
- all settings optional with defaults
- no global config files (project-local .env only)
- no API key needed (uses claude code CLI session)

### continuation flow
```python
if args.cont:
    await state.reset_interrupted_tasks()  # running → pending
    pending = await state.get_pending_tasks()
    for task in pending:
        await queue.put(task)
```

### planner implementation
uses ClaudeCodeClient to parse design files:
- calls `claude -p <prompt> --model sonnet` with JSON output request
- prompt asks for actionable tasks with priority/complexity
- parses JSON array of tasks
- falls back to simple line-based parsing on error
- 60s timeout for parsing

### worker implementation
uses ClaudeCodeClient (claude_code.py):
- client isolated in claude_code.py for reuse as library
- spawns `claude -p <prompt> --model sonnet`
- runs in cfg.target_dir (current working directory)
- 30s timeout per task (configurable in client)
- claude code has full tool access (read/write files, bash, etc)
- returns stdout from claude CLI
- worker.py:_do_work() is now single line: self.claude.execute()

## shocking patterns

**judge exits (not continuous)**: judge task completes when goal satisfied, triggering main() to cancel workers and exit. no daemon mode, no http server - just runs until done.

**no queue persistence**: queue regenerated from pending tasks on continuation. only task state persisted to disk.

**single planner at startup**: planner runs once at startup to break design into tasks using Claude CLI, then exits. no continuous planning, no cycles.

**async locks everywhere**: state manager uses asyncio.Lock for all mutations. no sync primitives in async code.

**in-memory queue**: asyncio.Queue used for task coordination. workers block on queue.get(), no polling.

## architecture

### entry point
- `demiurg.__main__:run` is the entry point (defined in pyproject.toml)
- `__main__.py` contains the actual implementation

### execution flow
1. parse args (design file path or -c for continuation)
2. load config from env/.demiurg files
3. init state manager (loads from ./.demiurg/)
4. if new run:
   - planner.plan_once() parses design file into tasks
   - state.init_work() creates work.json
5. if continuation (-c):
   - load existing work.json
   - reset interrupted tasks (running → pending)
6. populate queue from pending tasks
7. spawn workers (default 4) and judge
8. workers pull tasks from queue and execute
9. judge polls every 5s, exits when all tasks complete
10. main() cancels workers and exits

### task states
explicit enum in types_.py:
- PENDING: created, not started
- RUNNING: worker executing
- COMPLETED: finished successfully
- FAILED: error during execution

transitions:
- pending → running (worker starts)
- running → completed (success)
- running → failed (error/timeout)
- running → pending (continuation after interrupt)

### state persistence
all state at ./.demiurg/ (project-local, not global):
- tasks.json: array of all tasks with metadata
- work.json: design_file, goal_text, is_complete
- log/: execution logs

state written on every change (within lock).
each project has isolated state in its own ./.demiurg/ directory.

### key files
- `__main__.py`: entry point, orchestrates planner/workers/judge
- `config.py`: load config from environment variables
- `state.py`: StateManager with async locks for task/work persistence
- `types_.py`: Task, TaskStatus, WorkState dataclasses (underscore avoids masking built-in types)
- `planner.py`: parse design file into tasks (runs once)
- `worker.py`: execute tasks from queue using ClaudeCodeClient
- `claude_code.py`: isolated client for calling claude code CLI (reusable)
- `judge.py`: poll for completion every 5s, exit when done

## package structure

- package name: `demiurg`
- command name: `demiurg`
- internal module: `demiurg/` (no __init__.py needed)
- entry point: `demiurg.__main__:run`

## configuration

loads from ./.env (project-local) + environment variables:

all optional (with defaults):
- NUM_WORKERS=4
- NUM_PLANNERS=2 (unused in current implementation)
- TARGET_DIR=. (working directory)
- LOG_DIR={TARGET_DIR}/.demiurg/log
- DATA_DIR={TARGET_DIR}/.demiurg
- PORT=8080 (unused in current implementation)

no API key required - uses authenticated claude code CLI session.

state is project-local by default (isolated per project).
all state in ./.demiurg/ (gitignored).

## commit messages

format: `[section] message`
- lowercase, imperative mood
- no Co-Authored-By tags
- example: `[config] use .env format instead of TOML`
