# ship

autonomous coding agent. planner-worker-judge pattern on the command line.

## install

```bash
make install    # uv tool install
```

requires claude code CLI and codex CLI, both authenticated.

## usage

```bash
ship                 # reads SPEC.md
ship spec.txt        # specify design file
ship -c              # continue interrupted run
ship -w 8            # 8 workers (default: 4)
ship -t 600          # 10min timeout per task (default: 1200s)
ship -m 10           # 10 agentic turns (default: 25)
ship -v              # verbose (show prompts/responses)
```

## how it works

```
DESIGN.md -> validator -> planner -> workers -> refiner -> done
```

1. **validator** checks design quality. rejects to REJECTION.md or writes PROJECT.md
2. **planner** breaks design into tasks (runs once)
3. **workers** execute tasks in parallel via claude CLI
4. **judge** polls completion, triggers refinement
5. **refiner** analyzes results via codex CLI, creates follow-up tasks
6. **replanner** runs if refiner finds nothing, catches missed work

workers get skills from `~/.claude/skills/` injected into their prompts.

## state

stored in `.ship/`: tasks.json, work.json, log/

## config

optional `.env` in project root:

```
NUM_WORKERS=4
TASK_TIMEOUT=1200
MAX_TURNS=25
```

CLI args override env vars.

## build

```bash
make build    # uv sync
make test     # pytest
make right    # pyright + pytest
make clean    # rm cache + state
```

## license

MIT
