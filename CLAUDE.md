# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

autonomous agent orchestration. planner-worker-judge pattern.

## build and run

```bash
make build              # uv sync
make install            # uv tool install
make test               # pytest
make lint               # pre-commit run -a
make right              # pyright only
make clean              # rm cache + state
```

```bash
ship                    # auto-discover SPEC.md / spec.md / specs/*.md
ship <file>             # ship from file
ship <dir>              # ship from dir
ship <arg> <arg> ...    # args as context
ship -c                 # continue from last run
ship -k                 # validate spec only (exit 0/1)
ship -w 8 -t 600 -m 10 # override workers/timeout/turns
ship -x                 # enable refiner (codex CLI critique)
ship -v                 # verbose (-v: details, -vv: debug)
ship -q                 # quiet (errors only)
ship -h                 # help
```

## defaults

- workers: 4
- max_turns: 50
- task_timeout: 2400s (40min, agents told the real value)
- spec discovery: SPEC.md > spec.md > specs/*.md
- verbosity: 1 (0=quiet, 1=default, 2=verbose, 3=debug)

## how it runs

1. validator checks spec -> rejects to .ship/REJECTION.md or writes PROJECT.md; result cached in .ship/validated (SHA256)
2. planner runs once -> breaks design into tasks (with mode + worker assignment)
3. workers pull from queue, execute via claude CLI (parallel or sequential)
4. judge polls every 5s, updates TUI panel, retries failed tasks
5. when all complete: refiner (codex CLI) critiques batch if -x enabled, creates follow-up tasks
6. if refiner finds nothing: replanner (claude CLI) does full assessment vs goal
7. if replanner exhausted: adversarial verifier generates challenges as tasks (3 rounds max)
8. loop continues until no new tasks generated

## critical patterns

```python
if task.status is TaskStatus.PENDING:  # use 'is' not ==
```

state mutations: lock before read/write, save() under lock, copy before return.

config precedence: CLI args > env vars > .env file > defaults.

## shocking bits

- `-k` runs validation then exits: 0=accepted, 1=rejected; writes .ship/validated cache
- stale state (no work.json/tasks.json) is wiped silently on fresh run; real previous state prompts [c/N/q]
- validation cache (.ship/validated) skips the LLM call entirely if spec SHA256 matches
- rejection gaps printed to stdout at verbosity >= 1; full rejection text at >= 2
- planner runs once at startup, not continuously
- queue not persisted, rebuilt from pending tasks on -c
- claude CLI called with `--permission-mode bypassPermissions` always
- refiner uses codex CLI (cheaper/faster), replanner uses claude CLI (deeper)
- refiner only runs when -x flag is set (use_codex: bool in config)
- workers told actual timeout from config
- failed tasks auto-retry up to 10 times (timeout is just cleanup)
- planner told "2 day tasks" to get smaller chunks
- planner can set execution mode (parallel/sequential) and pin tasks to workers
- sequential mode: -w flag overrides the auto-reduction to 1 worker
- subprocess cleanup: SIGTERM, wait 10s, then SIGKILL
- TUI sliding window: shows running tasks + next N pending (not all tasks)
- workers read PLAN.md and CLAUDE.md before executing their task
- execute() streams stdout line-by-line; on_progress fires on `<progress>` tags
- `_parse_output` returns a 3-tuple `(status, followups, summary)` — not a dataclass yet
- git diff stats (_git_head + _git_diff_stat) appended to LOG.md after each task
- adversarial verifier: 10 challenges/round, picks 2 random, queues as tasks; deduped across rounds
- refiner/replanner/verifier timeouts are inconclusive (retry), not treated as success; attempt counters only increment on successful calls
- final done/total count uses post-run task list — total grows as replanned tasks are added during execution

## state

`.ship/` (internal, gitignored): tasks.json, work.json, validated, log/ship.log, log/trace.jl
project root (LLM-visible): SPEC.md, PLAN.md, PROGRESS.md, LOG.md, PROJECT.md

## key files

- `__main__.py` - entry point, click CLI, main orchestrator (v0.6.5)
- `types_.py` - Task (with worker field), TaskStatus, WorkState (with execution_mode)
- `state.py` - StateManager with asyncio.Lock
- `config.py` - loads .env + env vars, verbosity int (0-3), use_codex bool
- `display.py` - TUI with sliding window task panel, verbosity-gated events
- `planner.py` - design -> tasks + mode + worker assignments via claude CLI
- `validator.py` - rejects bad designs, writes PROJECT.md
- `worker.py` - executes tasks via ClaudeCodeClient, appends git diff to LOG.md
- `claude_code.py` - claude CLI wrapper, streams stdout, fires on_progress callbacks
- `codex_cli.py` - codex CLI wrapper (used by refiner)
- `judge.py` - polling orchestrator, triggers refiner/replanner/adversarial
- `refiner.py` - quick batch critique via codex CLI
- `replanner.py` - deep goal assessment via claude CLI
- `prompts.py` - all LLM prompts in one place

## commit messages

`[section] message` - lowercase, imperative
