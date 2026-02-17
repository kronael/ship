# architecture

## overview

ship implements planner-worker-judge pattern from cursor's blog post on scaling autonomous coding agents (https://cursor.com/blog/scaling-agents). goal-oriented execution: runs until satisfied, then exits.

```
SPEC.md → Validator → Planner → [task, task, task] → Queue
                                                        ↓
                                    Worker ← Worker ← Worker ← Worker
                                                        ↓
                                                    State (JSON)
                                                        ↓
                                    Judge → Refiner → Replanner → exit when complete
```

## components

### validator

checks spec quality before planning.

reads design file(s), validates specificity using claude code CLI.

outputs:
- accept/reject decision
- gaps list (if rejected → REJECTION.md)
- PROJECT.md (if accepted, clarifies goal/stack/io/constraints)

uses ClaudeCodeClient, sonnet model, 60s timeout.

### planner

reads validated spec + PROJECT.md, breaks into tasks using claude code CLI.

runs once at startup. generates:
- unique id (uuid) per task
- description (e.g., "create function foo()")
- worker assignment (auto | w0 | w1 | ...)
- execution mode (parallel | sequential)
- empty files list (populated by worker)
- status (pending)

execution mode:
- parallel: workers run concurrently (default, safer)
- sequential: single worker, tasks one at a time (for tight dependencies)

worker assignment:
- auto: ship assigns dynamically (default)
- w0/w1/etc: pin task to specific worker (for ordered sequences)

uses ClaudeCodeClient to parse design file, writes PLAN.md.

adds tasks to state and submits to queue.

### queue

asyncio.Queue holding pending tasks. unbounded (no maxsize).

workers block on queue.get() until task available.

no persistence - regenerated from state on continuation.

### worker

fetches tasks from queue, executes them, updates state.

execution flow:
1. check task.worker field - skip if pinned to different worker
2. mark task as running
3. spawn `claude -p <task.description> --model sonnet --permission-mode bypassPermissions` in current directory
4. inject skills from ~/.claude/skills/ into prompt
5. claude code has full tool access (read/write files, bash, grep, etc)
6. stream output (shown at verbosity ≥3)
7. mark task as completed with claude's stdout

on error: mark task as failed with error message.

1200s timeout per task (configurable via TASK_TIMEOUT or -t flag).

workers run independently - no inter-worker communication.

each worker maintains session across tasks for conversation continuity.

### judge

polling orchestrator with multi-tier critique.

polls state every 5s, updates TUI panel.

responsibilities:
1. judge completed tasks (narrow: "did this work?")
2. retry failed tasks (up to 10 times)
3. update TUI panel with task statuses
4. when all complete:
   - call refiner (medium: "missing pieces?")
   - if refiner finds nothing, call replanner (wide: "meets goal?")
   - if no new tasks, mark complete and exit

uses ClaudeCodeClient for per-task judgments (own session).

### refiner

quick batch critique using codex CLI (cheaper/faster than claude).

reads:
- PROGRESS.md (includes judge verdicts)
- recent completed tasks (last 10)
- recent failed tasks (last 5)

asks:
1. any obvious gaps? (missing tests, broken integration)
2. do failed tasks need alternative approaches?
3. anything the judge flagged as incomplete?

outputs:
- follow-up tasks (if gaps found)
- empty (if batch looks good)

uses CodexClient, 60s timeout.

### replanner

deep assessment comparing goal vs reality, using claude CLI.

reads:
- original goal from SPEC.md
- PLAN.md (original plan)
- PROGRESS.md (execution history)
- actual codebase files

asks:
- what percentage of goal is met?
- what's missing?
- quality issues?

outputs:
- tasks for missing work (if goal not met)
- empty (if goal satisfied)

updates PROGRESS.md with final assessment section.

uses ClaudeCodeClient (reuses judge's session ID), sonnet model, 90s timeout.

### state manager

persists to ./.ship/ as json files (project-local):
- tasks.json: array of all tasks with metadata + worker field
- work.json: design_file, goal_text, execution_mode, is_complete flag
- log/ship.log: structured logging
- log/trace.jl: json-lines trace of all LLM calls

async locks (asyncio.Lock) protect concurrent access.

loads existing state on startup for continuation.

### display

TUI with pacman-style task panel.

verbosity levels:
- 0 (-q): errors only
- 1 (default): panel + lifecycle events
- 2 (-v): + worker events, refiner/replanner info
- 3 (-vv): + raw prompts, streamed output

panel format (refreshes every 5s):
```
  [ 1/19] setup database schema           done
  [ 2/19] create user model               w0 ...
  [ 3/19] implement auth middleware        -

  2/19 (10%), 1 running executing
```

status indicators:
- done: completed
- FAIL: failed
- w0 ...: running on worker 0
- -: pending

lifecycle events with colors:
- cyan spinner (⟳): ongoing operations
- green check (✓): completed steps

non-tty: prints one line per state change (no panel rewriting).

## data flow

1. main() parses args (design file or -c flag)
2. load config (CLI args > env vars > .env > defaults)
3. set display.verbosity
4. if new run:
   - validator.validate() checks spec
   - planner.plan_once() generates tasks + mode + worker assignments
   - state.init_work() creates work state
5. if continuation:
   - state.reset_interrupted_tasks() resets running → pending
6. check execution mode, cap workers to 1 if sequential
7. populate queue from pending tasks
8. spawn workers + judge as async tasks
9. main waits for judge to complete
10. judge polls every 5s:
    - judge completed tasks
    - retry failed tasks
    - update TUI panel
    - when all complete: refiner → replanner → done
11. on judge exit: cancel workers, shutdown

## task lifecycle

states (explicit enum in types_.py):
- pending: created, not yet started
- running: worker executing
- completed: finished successfully
- failed: error during execution

transitions:
- pending → running (worker.execute start)
- running → completed (worker.execute success)
- running → failed (worker.execute error)
- running → pending (continuation after interruption)
- failed → pending (retry, up to 10 times)

## concurrency model

all agents run as asyncio tasks spawned from main.

coordination:
- queue uses asyncio.Queue (no locks needed)
- state manager uses asyncio.Lock
- workers don't coordinate with each other
- judge only reads state

shutdown:
- SIGINT/SIGTERM: cancel all async tasks
- subprocess cleanup: SIGTERM, wait 10s, then SIGKILL
- judge exits when complete
- main() cancels worker tasks
- gather with return_exceptions=True waits for cancellation

no coordination between workers - eliminates cursor's lock bottleneck.

## continuation model

state tracks interrupted work:
- work.json stores design_file, goal_text, execution_mode
- running tasks reset to pending on startup
- queue regenerated from pending tasks
- workers continue from last checkpoint

continuation flow:
```bash
# start work
ship SPEC.md  # creates work.json, generates tasks

# interrupt (ctrl-c)
^C

# continue
ship -c  # loads work.json, resets running tasks, resumes
```

## session management

- validator: one-shot, no session reuse
- planner: one-shot, no session reuse
- workers: each worker maintains its own session across tasks (per-worker session_id)
- judge: own session for per-task judgments (separate UUID)
- replanner: reuses judge's original session ID from main (sequential execution, no conflict)
- refiner: uses codex CLI (no claude sessions)

sessions enable conversation continuity - later tasks can reference earlier work.

## persistence format

tasks.json:
```json
[
  {
    "id": "uuid",
    "description": "create function foo()",
    "files": [],
    "status": "completed",
    "worker": "auto",
    "created_at": "2026-02-11T08:00:00Z",
    "started_at": "2026-02-11T08:00:05Z",
    "completed_at": "2026-02-11T08:00:06Z",
    "retries": 0,
    "error": "",
    "result": "created foo() in main.py"
  }
]
```

work.json:
```json
{
  "design_file": "SPEC.md",
  "goal_text": "- Create function foo()\n- Add tests",
  "project_context": "Go web server with REST API",
  "execution_mode": "parallel",
  "is_complete": false,
  "started_at": "2026-02-11T08:00:00Z",
  "last_updated_at": "2026-02-11T08:05:00Z"
}
```

## configuration precedence

1. defaults (hardcoded in config.py)
2. ./.env (project-local .env file, optional)
3. environment variables
4. CLI args (highest priority)

uses python-dotenv to load .env files from project root only.
no global config files - all config is project-local.

defaults:
- num_workers: 4
- max_turns: 25 (agentic turns per task)
- task_timeout: 1200 (seconds)
- verbosity: 1 (0=quiet, 1=default, 2=verbose, 3=debug)
- log_dir: .ship/log
- data_dir: .ship

## logging

unix format: "Feb 11 10:34:26"

logs to: .ship/log/ship.log (project-local)

lowercase messages, capitalize error names only.

trace: .ship/log/trace.jl (json-lines format, one LLM call per line)

## why codex for refiner?

two-tier critique trades cost for quality:
- refiner: fast sanity check after each batch (codex is cheaper)
- replanner: deep verification only if refiner finds nothing (claude is thorough)

most runs complete after refiner. replanner is fallback for complex cases.

## simplifications

compared to cursor's blog post, this implementation omits:
- continuous daemon mode (one-off execution instead)
- http api (removed for simplicity)
- multiple planners (single planner at startup)
- git operations (workers can use git via bash tool)
- queue persistence (regenerated from state)
- conflict resolution (workers can bump into each other)
- dynamic task prioritization (fifo queue)
- multi-node coordination (single machine only)

compared to cursor, this implementation adds:
- validator stage (checks spec quality before planning)
- refiner stage (codex quick critique)
- replanner stage (claude deep assessment)
- execution mode (parallel/sequential)
- worker assignment (auto/pinned)
- verbosity levels (0-3)
- TUI panel (pacman-style task display)

implementation status:
- workers: fully implemented using claude code CLI
- planner: fully implemented using claude code CLI
- validator: fully implemented
- judge: fully implemented (polling + multi-tier critique)
- refiner: fully implemented using codex CLI
- replanner: fully implemented using claude CLI
- state: fully implemented
- display: fully implemented (TUI panel + verbosity)
- claude_code.py: reusable client for calling claude code CLI
- codex_cli.py: reusable client for calling codex CLI

these simplifications make the system suitable for learning the pattern and autonomous coding, not production use.

## future simplifications

the architecture has evolved organically. potential consolidations:

1. merge planner/replanner: both do "goal → tasks", just different inputs
2. move polling to __main__.py: judge is really the orchestrator loop
3. single LLM client: replace codex_cli + claude_code with unified client
4. explicit state machine: task transitions could be more formal
5. worker assignment in __main__.py: planner decides, main enforces

see CLAUDE.md for commit conventions and development patterns.
