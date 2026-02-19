# Changelog

## 0.6.0 (2026-02-19)

### Added
- `ClaudeError.partial`: buffered stdout saved when timeout occurs
- `ClaudeError.session_id`: session ID captured on error for resume
- `ClaudeError` non-zero exit: exit code included in error message
- `ClaudeCodeClient.summarize()`: resumes interrupted session via
  `--resume`, returns done/remaining/blockers summary
- `execute()` uses `--output-format json` to capture session_id from
  each response line

### Changed
- `worker.py`: `progress_log` and `session_id` hoisted before try block
  so they are available in except handlers
- `on_progress` callback accumulates into `progress_log`
- on `ClaudeError`: calls `summarize()` if session_id available, else
  falls back to `partial` or `progress_log` tail
- failed tasks store result so replanner receives signal on what failed

## 0.5.0 (2026-02-18)

### Added
- adversarial verification: after replanning, verifier generates 10 challenges per
  round, picks 2, queues as worker tasks; up to 3 rounds / 3 attempts total;
  challenges deduped across rounds to avoid repetition
- task dependency parsing: `depends="N"` and `depends="N,M"` attributes in planner
  XML (1-indexed); resolved to UUIDs before queuing; tasks without `depends` can
  run in parallel
- `<progress>` tag support: workers emit `<progress>what you're doing</progress>`
  tags; displayed live in TUI at verbosity ≥1 via `on_progress` callback
- git diff summary on task completion: `_git_head()` snapshots HEAD before task,
  `_git_diff_stat()` appends `(N files, +ins/-del)` to LOG.md and TUI event
- streaming stdout: `execute()` reads claude stdout line-by-line instead of
  waiting for `proc.communicate()`; enables real-time progress display

### Changed
- session management removed: `ClaudeCodeClient` no longer manages session IDs,
  `--session-id`/`--resume` flags eliminated; `execute()` returns `(output, "")`
- skills injection removed from worker prompts; WORKER prompt now instructs agents
  to read PLAN.md and CLAUDE.md directly at task start
- task_timeout default: 2400s (was 1200s, 40min)
- max_turns default: 50 (was 25)
- sequential mode: explicit `-w` flag now overrides auto-reduction to 1 worker
- sliding window TUI: shows running tasks + next N pending (not full list)
- PLANNER context prompt expanded: requests 4-6 sentence project summary for workers
- refiner gated behind `-x`/`--codex` flag (already added in 0.4.0, now documented)
- VERSION 0.5.0

### Removed
- plan mode (`-p`/`--plan` flag) removed
- session resume logic from worker (`task.session_id` carry-over)
- `session_id` parameters from `Planner`, `Validator`, `Judge`, `Replanner`

## 0.4.0 (2026-02-17)

### Added
- `-x`/`--codex` flag: enable codex refiner (off by default)
  - without `-x`, ship runs workers + replan only
  - with `-x`, codex critiques completed work and generates follow-ups
  - config: `use_codex` in Config, gated in Judge

### Changed
- project version bumped to 0.4.0 in `pyproject.toml`
- lockfile metadata refreshed for editable `ship` package version

## 0.3.0 (2026-02-16)

### Changed
- each worker gets unique session ID (no shared session collisions)
- workers reuse sessions across tasks via --resume within same worker
- default task_timeout: 1200s (was 120s)
- default max_turns: 25 (was 5)
- permission mode: bypassPermissions (was acceptEdits)
- spec discovery: SPEC.md > spec.md > specs/*.md (was DESIGN.md)

### Added
- validator step before planning (rejects vague designs)
- refiner (codex CLI) + replanner (claude CLI) after workers finish
- three-level judge: per-task, batch refinement, full replanning
- failed task auto-retry up to 10 times
- SIGINT/SIGTERM handling with subprocess cleanup
- CancelledError kills child processes before propagating
- skills injection from ~/.claude/skills/
- TUI status line with live progress
- PROGRESS.md written on each judge poll
- plan mode (-p, experimental)
- verbose mode (-v)
- trace logging to .ship/log/trace.jl

## 0.2.0 (2026-01-29)

### Changed
- CLI migrated from argparse to click
- default design file: DESIGN.md (no positional arg required)
- default max_turns: 5 (was unlimited)
- default task_timeout: 120s (configurable via -t/--timeout)

### Added
- CLI flags: -f/--file, -c/--continue, -w/--workers, -t/--timeout, -m/--max-turns
- TASK_TIMEOUT config (env var and CLI flag)

### Removed
- TARGET_DIR config (always uses current directory)
- PORT config (unused, no HTTP server)
- NUM_PLANNERS config (unused, single planner)

## 0.1.0

initial release with planner-worker-judge architecture.
