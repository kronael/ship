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
ship                 # reads DESIGN.md
ship -f spec.txt     # specify design file
ship -c              # continue from last run
ship -w 8 -t 600     # 8 workers, 10min timeout
ship -v              # verbose mode
```

## defaults

- workers: 4
- max_turns: 25
- task_timeout: 1200s (20min, agents told the real value)
- design file: DESIGN.md

## how it runs

1. validator checks DESIGN.md -> rejects to REJECTION.md or writes PROJECT.md
2. planner runs once -> breaks design into tasks
3. workers pull from queue, execute via claude CLI in parallel
4. judge polls every 5s, triggers refinement when all done
5. refiner (codex CLI) creates follow-up tasks
6. replanner runs if refiner finds nothing

## critical patterns

```python
if task.status is TaskStatus.PENDING:  # use 'is' not ==
```

state mutations: lock before read/write, save() under lock, copy before return.

config precedence: CLI args > env vars > .env file > defaults.

## shocking bits

- planner runs once at startup, not continuously
- queue not persisted, rebuilt from pending tasks on -c
- claude CLI called with `--permission-mode acceptEdits` always
- refiner uses codex CLI (not claude)
- workers told actual timeout from config
- failed tasks auto-retry up to 10 times (timeout is just cleanup)
- planner told "2 day tasks" to get smaller chunks
- skills from `~/.claude/skills/` injected into worker prompts

## state

all in `.ship/`: tasks.json, work.json, log/

## key files

- `__main__.py` - entry point, click CLI, orchestration
- `types_.py` - Task, TaskStatus (PENDING/RUNNING/COMPLETED/FAILED), WorkState
- `state.py` - StateManager with asyncio.Lock
- `config.py` - loads .env + env vars
- `planner.py` - design -> tasks via claude CLI
- `validator.py` - rejects bad designs, writes PROJECT.md
- `worker.py` - executes tasks via ClaudeCodeClient
- `claude_code.py` - claude CLI wrapper
- `judge.py` - polls completion
- `refiner.py` - follow-up tasks via codex CLI
- `replanner.py` - missed work via claude CLI

## commit messages

`[section] message` - lowercase, imperative
