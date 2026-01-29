# Changelog

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
