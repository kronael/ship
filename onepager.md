# demiurg: autonomous coding agent

Reads design file, breaks into tasks, executes in parallel using Claude Code CLI, exits when complete.

## what it does

- reads design.txt with bullet-point tasks
- planner generates task breakdown using Claude
- 4 workers (configurable) execute tasks in parallel
- each worker spawns `claude -p <task> --model sonnet`
- judge polls every 5s, exits when all tasks complete
- state persisted to ./.demiurg/ (project-local)

## key features

**parallel execution:**
- 4 workers run simultaneously (configurable)
- tasks run independently without coordination
- no shared locks between workers

**project isolation:**
- each project has ./.demiurg/ state directory
- multiple demiurg instances can run on different projects
- no global state mixing

**continuation:**
- `demiurg -c` resumes from checkpoint
- running tasks reset to pending on restart
- no lost work on interruption

## how it works

```bash
# create design file
cat > design.txt <<EOF
- create fastapi server with /health endpoint
- add GET /users endpoint with pagination
- add POST /users endpoint with validation
- write pytest tests for all endpoints
- add openapi documentation
EOF

# run demiurg (once)
demiurg design.txt

# it will:
# 1. parse design.txt into 5 tasks using claude
# 2. spawn 4 workers, execute tasks in parallel
# 3. each worker calls: claude -p "<task>" --model sonnet
# 4. judge polls every 5s, exits when all tasks complete
# 5. you have a working API server
```

## comparison

| approach | parallelization | supervision | state persistence |
|----------|-----------------|-------------|-------------------|
| manual coding | none | constant | none |
| chatgpt | none (sequential) | constant | none |
| cursor | none (one task at a time) | per-task | project files |
| demiurg | 4 workers | none (runs to completion) | ./.demiurg/ |

## architecture

based on cursor's scaling agents blog:
- **planner**: reads design file, creates tasks (runs once at startup)
- **workers**: execute tasks in parallel using claude code CLI
- **judge**: polls every 5s, exits when goal satisfied

pattern proven at scale by cursor, implemented for command-line use.

## requirements

- claude code CLI installed (`claude --version`)
- python 3.12+
- that's it

## installation

```bash
# run directly from github
uvx github.com/kronael/demiurg design.txt

# or install globally
make install
demiurg design.txt
```

## use cases

- boilerplate generation (APIs, CLIs, scripts)
- migrations and transformations
- test suite creation
- documentation generation
- repetitive coding tasks

not suitable for:
- creative problem solving (use claude code directly)
- debugging (use IDE)
- small one-off changes (edit manually)

## implementation details

- runs until done, then exits (not daemon)
- planner runs once at startup
- workers timeout after 30s per task
- queue regenerated from pending tasks on continuation
- state isolated per project (./.demiurg/)
