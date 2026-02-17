# Changelog

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
