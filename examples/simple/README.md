# simple: manual spec workflow

write a spec, run ship, get working code.

## walkthrough

### 1. create project

```bash
mkdir my-tool && cd my-tool
git init
```

### 2. write SPEC.md

create `SPEC.md` in the project root. ship discovers it
automatically. see [SPEC.md](SPEC.md) in this directory
for a ready-to-run example.

the spec needs structured sections with concrete
acceptance criteria. ship's validator checks the spec
before planning -- vague specs get rejected to
`REJECTION.md`.

### 3. run ship

```bash
ship
```

ship runs through a pipeline:

```
SPEC.md -> validator -> planner -> workers -> judge -> verifier -> done
```

1. **validator** -- checks spec quality, rejects vague
   specs to REJECTION.md, writes PROJECT.md
2. **planner** -- breaks deliverables into tasks with
   dependencies, writes PLAN.md
3. **workers** -- parallel subagents execute tasks via
   claude CLI (up to 4 concurrent by default)
4. **judge** -- verifies each task, triggers refinement
   if needed
5. **verifier** -- adversarial challenges (up to 3
   rounds) to prove the objective is met

failed tasks auto-retry up to 10 times. dependency
chains cascade failures to blocked tasks.

### 4. check results

ship writes state to `.ship/` in the project root:

- `.ship/tasks.json` -- task breakdown and status
- `.ship/work.json` -- execution state
- `.ship/log/` -- per-task logs
- `PLAN.md` -- generated plan
- `PROGRESS.md` -- human-readable progress

### 5. continue if interrupted

if ship is interrupted (ctrl-c, timeout, crash):

```bash
ship -c
```

resumes from `.ship/` state. completed tasks are
skipped, running tasks restart.

## options

```bash
ship                 # discover SPEC.md, run
ship -c              # continue interrupted run
ship -w 2            # limit to 2 parallel workers
ship -t 1200         # 20min timeout per task
ship -m 25           # 25 agentic turns per task
ship -v              # verbose output
ship -vv             # debug output
ship specs/          # use specs from directory
ship -x              # enable codex refiner
```

## tips

- ship reads `SPEC.md` or `specs/*.md`
- be specific in deliverables -- "add pytest tests for
  all endpoints" not "add tests"
- use `**Accept**` fields so the judge can verify
- verification items should be runnable commands
- keep individual specs focused (one component each)
