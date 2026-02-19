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
                                    Judge → Refiner → Replanner → Adversarial → exit when complete
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
- depends attribute (parsed from XML: `depends="N"`)
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
2. mark task as running, notify judge
3. spawn `claude -p <task.description> --model sonnet --permission-mode bypassPermissions` in current directory
4. prompt instructs worker to read PLAN.md and CLAUDE.md before starting
5. claude code has full tool access (read/write files, bash, grep, etc)
6. stream stdout line-by-line; on_progress callback fires on `<progress>` XML tags
7. parse output for `<status>`, `<summary>`, `<followups>` XML tags
8. if XML tags missing, call claude.reformat(session_id) to retry formatting
9. mark task as completed with result and summary
10. notify judge; append git diff stats to LOG.md entry

on error (ClaudeError):
- if session_id available: resume session via claude.summarize() for progress summary
- else if partial output: use partial as result
- else: use last `<progress>` tags from progress_log
- mark task failed with error + result_text

2400s timeout per task (configurable via TASK_TIMEOUT or -t flag).

workers run independently - no inter-worker communication.

### judge

polling orchestrator with multi-tier critique.

polls state every 5s, updates TUI panel.

maintains a completed queue: workers call notify_completed() when done;
judge drains it each poll cycle and calls _judge_task() for each.

responsibilities:
1. drain completed queue, judge each task via claude (writes to PROGRESS.md)
2. retry failed tasks (up to 10 times)
3. cascade failure: tasks exhausting retries mark dependent tasks as cascade-failed
4. update TUI sliding window: running tasks + next N pending
5. when all complete:
   - call refiner if use_codex enabled (medium: "missing pieces?")
   - if refiner finds nothing (or skipped), call replanner (wide: "meets goal?")
   - if replanner exhausted, run adversarial verification rounds
   - if no new tasks from any stage, mark complete and exit

adversarial verification (_run_adversarial_round):
- generates 10 challenges per round, picks 2 at random
- queues selected challenges as tasks
- deduplicates challenges across rounds
- 3 rounds max, 3 attempts max per round

### refiner

quick batch critique using codex CLI (cheaper/faster than claude).

only runs when use_codex is enabled (-x flag).

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
- PROGRESS.md (execution history with per-task judgments)
- actual codebase files

asks:
- what percentage of goal is met?
- what's missing?
- quality issues?

outputs:
- tasks for missing work (if goal not met)
- empty (if goal satisfied)

updates PROGRESS.md with final assessment section.

uses ClaudeCodeClient, sonnet model, 90s timeout.

### state manager

persists to ./.ship/ as json files (project-local):
- tasks.json: array of all tasks with metadata + worker field
- work.json: design_file, goal_text, execution_mode, is_complete flag
- log/ship.log: structured logging
- log/trace.jl: json-lines trace of all LLM calls

async locks (asyncio.Lock) protect concurrent access.

loads existing state on startup for continuation.

### display

TUI with sliding window task panel.

verbosity levels:
- 0 (-q): errors only
- 1 (default): panel + lifecycle events
- 2 (-v): + worker events, refiner/replanner info
- 3 (-vv): + raw prompts, streamed output

panel refreshes every 5s: running tasks + next N pending (sliding window).
status: `done`, `FAIL`, `w0 ...` (running on worker 0), `-` (pending).
task rows show summary text (from `<summary>` tag) when available.
non-tty: one line per state change.

## data flow

1. main() parses args (design file, inline text, or -c flag)
2. load config (CLI args > env vars > .env > defaults)
3. acquire ship.lock (exclusive, non-blocking) — bail if already running
4. set display.verbosity
5. if new run:
   - validator.validate() checks spec
   - planner.plan_once() generates tasks + mode + worker assignments
   - state.init_work() creates work state
6. if continuation:
   - state.reset_interrupted_tasks() resets running → pending
7. check execution mode, cap workers to 1 if sequential (unless -w overrides)
8. populate queue from pending tasks
9. spawn workers + judge as async tasks
10. main waits for judge to complete
11. judge polls every 5s:
    - drain completed queue, judge each task
    - retry failed tasks; cascade after 10 retries
    - update TUI sliding window
    - when all complete: refiner (if -x) → replanner → adversarial → done
12. on judge exit: cancel workers, print failed task summary, shutdown

## task lifecycle

states (explicit enum in types_.py):
- pending: created, not yet started
- running: worker executing
- completed: finished successfully
- failed: error during execution

transitions:
- pending → running (worker.execute start)
- running → completed (worker.execute success)
- running → failed (worker.execute error or partial)
- running → pending (continuation after interruption)
- failed → pending (retry, up to 10 times)
- failed → cascade-failed (dependent task blocked after retry exhaustion)

## concurrency model

all agents run as asyncio tasks spawned from main.

coordination:
- queue uses asyncio.Queue (no locks needed)
- state manager uses asyncio.Lock
- workers don't coordinate with each other
- judge receives completion notifications via notify_completed()

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

single .md spec file gets a slug-based data dir: `ship foo.md` → `.ship/foo/`.
this allows multiple specs to coexist without clobbering each other.

continuation: `ship SPEC.md` (creates state), `^C` (interrupt), `ship -c` (resumes from pending tasks).

## persistence format

tasks.json: array of task objects with id, description, files, status, worker,
created_at, started_at, completed_at, retries, error, result, summary.

work.json: design_file, goal_text, project_context, execution_mode,
is_complete, started_at, last_updated_at.

## configuration precedence

1. defaults (hardcoded in config.py)
2. ./.env (project-local .env file, optional)
3. environment variables
4. CLI args (highest priority)

uses python-dotenv to load .env files from project root only.
no global config files - all config is project-local.

defaults:
- num_workers: 4
- max_turns: 50 (agentic turns per task)
- task_timeout: 2400 (seconds)
- use_codex: false (refiner disabled unless -x)
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
- refiner: fast sanity check after each batch (codex is cheaper, opt-in via -x)
- replanner: deep verification only if refiner finds nothing (claude is thorough)

most runs complete after replanner. adversarial is fallback for edge cases.

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
- refiner stage (codex quick critique, opt-in)
- replanner stage (claude deep assessment)
- adversarial verification (challenge-based task generation after replanning)
- execution mode (parallel/sequential)
- worker assignment (auto/pinned)
- verbosity levels (0-3)
- TUI sliding window panel
- progress tag callbacks during streaming
- summary tag parsing (worker output → TUI display)
- error recovery: session resume for summary on failure
- reformat on missing XML tags
- cascade failure propagation to dependent tasks
- lock file preventing concurrent runs
- git diff summary in LOG.md per task
- slug-based state dirs for multi-spec coexistence

see CLAUDE.md for commit conventions and development patterns.
