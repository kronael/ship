# demiurg

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

autonomous coding agent using planner-worker-judge pattern.

implements [cursor's battle-tested architecture](https://cursor.com/blog/scaling-agents) on the command line.

## quick start

```bash
# create design file
cat > DESIGN.md <<EOF
# my-project

Build a hello world CLI tool in Python.

## Tasks
- Create hello.py with main function
- Add greeting message
- Make file executable
EOF

# run demiurg (reads DESIGN.md by default)
demiurg

# result: working hello.py created automatically
python hello.py
```

## installation

```bash
# run directly
uvx github.com/kronael/demiurg

# or install
make install
demiurg
```

## usage

```bash
# run with default DESIGN.md
demiurg

# specify design file
demiurg -f spec.txt
demiurg spec.txt       # positional also works

# continue interrupted work
demiurg -c

# tune execution
demiurg -w 8           # 8 parallel workers (default: 4)
demiurg -t 300         # 5 min timeout per task (default: 120s)
demiurg -m 10          # 10 max turns per task (default: 5)
```

### CLI options

| Flag | Long | Description | Default |
|------|------|-------------|---------|
| | | design file (positional) | DESIGN.md |
| -f | --file | design file (like make -f) | DESIGN.md |
| -c | --continue | resume from last run | - |
| -w | --workers | parallel workers | 4 |
| -t | --timeout | task timeout (seconds) | 120 |
| -m | --max-turns | max agentic turns per task | 5 |

## requirements

- claude code CLI installed and authenticated
- run `claude --version` to verify

## configuration

create `.env` in project root (optional):

```bash
NUM_WORKERS=4
TASK_TIMEOUT=120
MAX_TURNS=5
```

CLI args override env vars. all settings optional with defaults.

## architecture

```
DESIGN.md → Planner → Tasks → Workers → Refiner → More Tasks? → Done
                ↓         ↓         ↓           ↓
          (extracts   (parallel  (analyzes   (up to 3
           context)    Claude)    results)    rounds)
```

1. **planner** - parses DESIGN.md, extracts project context and tasks
2. **workers** - execute tasks in parallel using Claude CLI
3. **judge** - monitors completion, triggers refinement
4. **refiner** - analyzes completed work, creates follow-up tasks

### skills injection

demiurg automatically loads skills from `~/.claude/skills/` and injects them into worker prompts. workers use relevant skills based on project context.

supported skill formats:
- `~/.claude/skills/go/SKILL.md` - directory with SKILL.md
- `~/.claude/skills/python.md` - single file

skills are injected as context, not slash commands. workers see patterns and use them automatically.

### project context

planner extracts project context from DESIGN.md:
- what's being built
- tech stack (language, framework)
- key patterns

this context is injected into every worker prompt, enabling automatic skill selection.

### refinement loop

after all tasks complete, the refiner analyzes results:
- are there obvious follow-up tasks? (tests, fixes, docs)
- do failed tasks need alternative approaches?

up to 3 refinement rounds run automatically. no manual intervention needed.

## state

state persisted to `./.demiurg/`:
- `tasks.json` - task list with status
- `work.json` - project context, completion state
- `log/` - execution logs

each project has isolated state. safe to run multiple demiurg instances in different directories.

## examples

see `examples/` directory:
- `hello-world.txt` - minimal example
- `fastapi-server.txt` - complete REST API with tests
- `cli-tool.txt` - CLI tool with subcommands

```bash
demiurg -f examples/fastapi-server.txt
```

## build

```bash
make build    # uv sync (install deps)
make install  # install as uv tool
make test     # pytest
make right    # pyright + pytest
make clean    # remove cache and state
```

## license

MIT - see [LICENSE](LICENSE)
