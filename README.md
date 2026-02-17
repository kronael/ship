# ship

unattended harness for coding agents. planner-worker-judge
on the command line.

## install

```bash
make install    # uv tool install
```

requires claude code CLI and codex CLI, both authenticated.

## usage

```bash
ship                 # reads SPEC.md
ship spec.txt        # specify design file
ship mydir/          # ship from directory
ship -c              # continue interrupted run
ship -w 8            # 8 workers (default: 4)
ship -t 600          # 10min timeout per task (default: 1200s)
ship -m 10           # 10 agentic turns per task (default: 25)
ship -v              # verbose (show prompts/responses)
ship -x              # enable codex refiner
ship -p              # [experimental] plan mode
```

`-x` enables the codex refiner. without it, ship runs workers +
replan only. with `-x`, codex critiques completed work and generates
follow-up tasks between cycles.

plan mode (`-p`) is experimental. see
[kronael/rsx](https://github.com/kronael/rsx) for example usage.

## how it works

```
SPEC.md -> validator -> planner -> workers -> judge -> refiner -> done
```

1. **validator** checks design quality, rejects to REJECTION.md or
   writes PROJECT.md
2. **planner** breaks design into tasks (runs once)
3. **workers** execute tasks in parallel via claude CLI, each with
   its own session
4. **judge** monitors completion, judges each task, triggers
   refinement
5. **refiner** (requires `-x`) analyzes results via codex CLI,
   creates follow-up tasks
6. **replanner** runs if refiner finds nothing (or `-x` not set),
   catches missed work

workers get skills from `~/.claude/skills/` injected into prompts.
failed tasks auto-retry up to 10 times.

ctrl+c kills child processes and exits cleanly (SIGINT/SIGTERM
both handled).

## state

`.ship/` directory: tasks.json, work.json, log/

## config

optional `.env` in project root:

```
NUM_WORKERS=4
TASK_TIMEOUT=1200
MAX_TURNS=25
```

CLI args override env vars override .env file.

## build

```bash
make build    # uv sync
make test     # pytest
make right    # pyright + pytest
make clean    # rm cache + state
```

## starship

the `starship` Claude Code skill (`~/.claude/skills/starship/`)
plans a project inside Claude, writes SPEC.md, then calls `ship`
to execute. use `/starship <goal>` in Claude Code.

See SPEC.md for specification, ARCHITECTURE.md for architecture.

## license

MIT
