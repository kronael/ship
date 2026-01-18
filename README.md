# demiurg

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)

autonomous coding agent using planner-worker-judge pattern.

based on cursor's blog: https://cursor.com/blog/scaling-agents

## quick example

```bash
# create design file
cat > design.txt <<EOF
- Create hello.py with main function
- Add greeting message "Hello from demiurg!"
- Make file executable
EOF

# run demiurg
uvx github.com/kronael/demiurg design.txt

# demiurg will:
# 1. parse design.txt into tasks
# 2. execute tasks in parallel using Claude Code
# 3. exit when complete

# result: working hello.py created automatically
python hello.py  # Hello from demiurg!
```

## installation

```bash
# run directly
uvx github.com/kronael/demiurg design.txt

# or install
make install
demiurg design.txt
```

## usage

```bash
# run on design file
demiurg design.txt

# continue interrupted work
demiurg -c

# design file format (plain text)
- Create function foo()
- Add tests for foo()
- Document foo()
```

runs until goal satisfied, then exits. no daemon, no http server.

## requirements

- claude code CLI installed and authenticated
- run `claude --version` to verify

## configuration

create `.env` in project root (optional):

```bash
NUM_WORKERS=4
TARGET_DIR=.
```

or set environment variables in shell (overrides .env):
```bash
export NUM_WORKERS=8
demiurg design.txt
```

all settings optional with defaults. see `.env.example` for full list.

## architecture

goal-oriented execution:
1. planner reads design file, generates tasks (once at start)
2. workers execute tasks in parallel (4 by default)
   - each worker spawns `claude -p <task> --model sonnet`
   - claude code has full tool access (read/write files, bash, etc)
3. judge polls completion every 5s, exits when done

state persisted to ./.demiurg/ (tasks.json, work.json, log/) in each project.
each project has isolated state - no global mixing.

see SPEC.md for specification, ARCHITECTURE.md for architecture details.

## examples

see `examples/` directory:
- `hello-world.txt` - minimal example
- `fastapi-server.txt` - complete REST API with tests
- `cli-tool.txt` - CLI tool with subcommands

run an example:
```bash
demiurg examples/fastapi-server.txt
```

## build

```bash
make build    # uv sync (install deps)
make install  # install as uv tool
make test     # pytest
make right    # pyright + pytest
make clean    # remove cache and state
```

## contributing

see [CONTRIBUTING.md](CONTRIBUTING.md) for development setup and guidelines.

## license

MIT - see [LICENSE](LICENSE)
