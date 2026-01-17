# demiurg

autonomous coding agent using planner-worker-judge pattern.

based on cursor's blog: https://cursor.com/blog/scaling-agents

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

loads from (highest priority first):
1. environment variables
2. ./.demiurg (local project)
3. ~/.demiurg/config (global)

.env format (all optional):
```bash
NUM_WORKERS=4
TARGET_DIR=.
```

## architecture

goal-oriented execution:
1. planner reads design file, generates tasks (once at start)
2. workers execute tasks in parallel (4 by default)
   - each worker spawns `claude -p <task> --model sonnet`
   - claude code has full tool access (read/write files, bash, etc)
3. judge polls completion every 5s, exits when done

state persisted to ./.demiurg/ (tasks.json, work.json, log/).
each project has isolated state - no global mixing.

see SPEC.md for specification, ARCHITECTURE.md for architecture, blog.md for background.

## build

```bash
make build    # uv sync (install deps)
make install  # install as uv tool
make test     # pytest
make right    # pyright + pytest
make clean    # remove cache and state
```
