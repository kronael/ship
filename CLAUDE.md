# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

autonomous agent orchestration. planner-worker-judge pattern.

## build and run

```bash
make build              # uv sync
make install            # uv tool install
make test               # pytest
make right              # pyright + pytest
make clean              # rm cache + state
```

```bash
ship                    # auto-discover SPEC.md / spec.md / specs/*.md
ship <file>             # ship from file
ship <dir>              # ship from dir
ship <arg> <arg> ...    # args as context
ship -p [args...]       # [experimental] plan mode (see kronael/rsx)
ship -c                 # continue from last run
ship -w 8 -t 600 -m 10 # override workers/timeout/turns
ship -v                 # verbose (-v: details, -vv: debug)
ship -q                 # quiet (errors only)
ship -h                 # help
```

## defaults

- workers: 4
- max_turns: 25
- task_timeout: 1200s (20min, agents told the real value)
- spec discovery: SPEC.md > spec.md > specs/*.md
- verbosity: 1 (0=quiet, 1=default, 2=verbose, 3=debug)

## how it runs

1. validator checks spec -> rejects to REJECTION.md or writes PROJECT.md
2. planner runs once -> breaks design into tasks (with mode + worker assignment)
3. workers pull from queue, execute via claude CLI (parallel or sequential)
4. judge polls every 5s, updates TUI panel, retries failed tasks
5. when all complete: refiner (codex CLI) critiques batch, creates follow-up tasks
6. if refiner finds nothing: replanner (claude CLI) does full assessment vs goal
7. loop continues until no new tasks generated

## critical patterns

```python
if task.status is TaskStatus.PENDING:  # use 'is' not ==
```

state mutations: lock before read/write, save() under lock, copy before return.

config precedence: CLI args > env vars > .env file > defaults.

## shocking bits

- planner runs once at startup, not continuously
- queue not persisted, rebuilt from pending tasks on -c
- claude CLI called with `--permission-mode bypassPermissions` always
- refiner uses codex CLI (cheaper/faster), replanner uses claude CLI (deeper)
- workers told actual timeout from config
- failed tasks auto-retry up to 10 times (timeout is just cleanup)
- planner told "2 day tasks" to get smaller chunks
- skills from `~/.claude/skills/` injected into worker prompts
- planner can set execution mode (parallel/sequential) and pin tasks to workers
- subprocess cleanup: SIGTERM, wait 10s, then SIGKILL
- TUI panel refreshes in place every 5s (pacman-style, each task on own line)

## state

`.ship/` (internal, gitignored): tasks.json, work.json, log/ship.log, log/trace.jl
project root (LLM-visible): SPEC.md, PLAN.md, PROGRESS.md, LOG.md, PROJECT.md

## key files

- `__main__.py` - entry point, click CLI, main orchestrator
- `types_.py` - Task (with worker field), TaskStatus, WorkState (with execution_mode)
- `state.py` - StateManager with asyncio.Lock
- `config.py` - loads .env + env vars, verbosity int (0-3)
- `display.py` - TUI with pacman-style task panel, verbosity-gated events
- `planner.py` - design -> tasks + mode + worker assignments via claude CLI
- `validator.py` - rejects bad designs, writes PROJECT.md
- `worker.py` - executes tasks via ClaudeCodeClient
- `claude_code.py` - claude CLI wrapper with session reuse
- `codex_cli.py` - codex CLI wrapper (used by refiner)
- `judge.py` - polling orchestrator, triggers refiner/replanner
- `refiner.py` - quick batch critique via codex CLI
- `replanner.py` - deep goal assessment via claude CLI
- `prompts.py` - all LLM prompts in one place

## commit messages

`[section] message` - lowercase, imperative
