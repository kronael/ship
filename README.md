# ship

unattended harness for coding agents. planner-worker-judge
on the command line.

## install

```bash
make install    # uv tool install
```

requires claude code CLI, authenticated. codex CLI optional
(only for `-x` refiner).

## usage

```bash
ship <file>          # ship from design file
ship specs/          # ship from specs directory
ship "add auth"      # inline goal text
ship -f              # wipe state and start fresh
ship -k              # validate spec only (exit 0/1)
ship -n 8            # 8 workers (default: 4)
ship -t 1200         # 20min timeout per task (default: 2400s)
ship -m 25           # 25 agentic turns per task (default: 50)
ship -p "use stdlib only"  # inject override into all LLM calls
ship -v              # verbose (show prompts/responses)
ship -x              # enable codex refiner
```

continuation is automatic: if state exists and spec is unchanged,
ship resumes from where it left off. if spec changed, an LLM call
decides whether to keep completed tasks or replan from scratch.
use `-f` to force a fresh run.

`-x` enables the codex refiner. without it, ship runs workers +
replan only. with `-x`, codex critiques completed work and generates
follow-up tasks between cycles.

## how it works

```
specs/*.md -> validator -> planner -> workers -> judge -> verifier -> done
```

1. **validator** checks design quality. rejects to `.ship/REJECTION.md`
   or writes PROJECT.md. caches spec SHA256 in `.ship/validated`;
   subsequent runs skip re-validation if spec unchanged.
2. **planner** breaks deliverables into tasks, writes PLAN.md
3. **workers** execute tasks via claude CLI, each in its own session.
   streams NDJSON events via `--output-format stream-json`, parses
   `<progress>` tags for live status, tracks git diff stats per task.
   parses `<summary>` from output for TUI.
4. **judge** monitors completion, judges each task, triggers
   refinement cycles. retries failed tasks up to 10 times, then
   cascades failure to dependent tasks.
5. **refiner** (requires `-x`) analyzes results via codex CLI,
   creates follow-up tasks
6. **replanner** runs if refiner finds nothing (or `-x` not set),
   catches missed work
7. **verifier** runs adversarial challenges (up to 3 rounds) to
   prove the objective is met before marking complete

on spec change (hash differs from saved state): LLM decides whether
to keep completed tasks and add new ones, or replan from scratch.

on error: worker resumes session for a progress summary, or falls
back to last `<progress>` tags seen. if output is missing XML tags,
worker calls `claude.reformat()` to retry formatting.

ctrl+c kills child processes and exits cleanly (SIGINT/SIGTERM
both handled). a lock file prevents concurrent runs on the same
state dir.

## planship

the `planship` Claude Code skill (`~/.claude/skills/planship/`)
plans a project inside Claude, writes `specs/*.md`, then calls
`ship` to execute. use `/planship <goal>` in Claude Code.

works incrementally: detects existing specs and shipped work,
only plans and ships the delta.

## specs format

ship reads the file or directory passed on the cmdline. each spec file should have
deliverables with concrete acceptance criteria:

```markdown
# Component Name

## Goal
what this component delivers

## Deliverables

### 1. Feature name
- **Files**: src/foo.rs, tests/foo_test.rs
- **Accept**: testable criteria
- **Notes**: patterns to follow

## Constraints
- conventions, boundaries

## Verification
- [ ] how to know it works
```

## state

`.ship/` directory: tasks.json, work.json, log/

single .md arg gets its own slug dir: `ship foo.md` → `.ship/foo/`.

## config

optional `.env` in project root:

```
NUM_WORKERS=4
TASK_TIMEOUT=2400
MAX_TURNS=50
```

CLI args override env vars override .env file.

## build

```bash
make build    # uv sync
make test     # unit tests (<5s, skips smoke)
make smoke    # smoke tests (real CLI calls)
make lint     # pre-commit run -a
make right    # pyright only
make clean    # rm cache + state
```

dev deps (pytest, pyright, ruff, pre-commit) are in `[dependency-groups] dev`
in pyproject.toml. install with `uv sync --group dev`.

## license

MIT
