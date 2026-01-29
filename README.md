# demiurg

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

autonomous coding agent using planner-worker-judge pattern.

implements [cursor's battle-tested architecture](https://cursor.com/blog/scaling-agents) on the command line.

## quick start

```bash
# create design file
cat > SPEC.md <<EOF
- Create hello.py with main function
- Add greeting message "Hello from demiurg!"
- Make file executable
EOF

# run demiurg (reads SPEC.md by default)
demiurg

# result: working hello.py created automatically
python hello.py  # Hello from demiurg!
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
# run with default SPEC.md
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
| | | design file (positional) | SPEC.md |
| -f | --file | design file (like make -f) | SPEC.md |
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

goal-oriented execution:
1. planner reads design file, generates tasks (once at start)
2. workers execute tasks in parallel (4 by default)
   - each worker spawns `claude -p <task> --model sonnet`
   - claude code has full tool access (read/write files, bash, etc)
3. judge polls completion every 5s, exits when done

state persisted to ./.demiurg/ (tasks.json, work.json, log/) in each project.

see SPEC.md for specification, ARCHITECTURE.md for details.

## examples

see `examples/` directory:
- `hello-world.txt` - minimal example
- `fastapi-server.txt` - complete REST API with tests
- `cli-tool.txt` - CLI tool with subcommands

run an example:
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
