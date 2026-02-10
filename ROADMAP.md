# ROADMAP

ship toward minimal task queue sharing coordination for agent work.

## vision

ship becomes a lightweight, shareable task queue that multiple AI agents
(claude, codex, copilot, local models) can pull work from and push results
to. the planner-worker-judge pattern stays, but the queue becomes the
shared contract between heterogeneous agents.

## landscape

### frameworks compared

| framework | pattern | queue | parallel | state | complexity | lock-in |
|-----------|---------|-------|----------|-------|------------|---------|
| **langgraph** | state graph DAG | graph routing | excellent | checkpointed | high | langchain ecosystem |
| **crewai** | role-based teams | event hierarchy | good | crew state | medium | crewai framework |
| **autogen/ag2** | conversation swarms | message passing | moderate | external | medium | microsoft ecosystem |
| **temporal** | durable workflows | durable queues | excellent | event sourced | high | temporal server |
| **prefect** | dynamic workflows | work queues | good | result cache | medium | prefect server |
| **celery** | distributed tasks | message broker | good | external | medium | redis/rabbitmq |
| **ship** | planner-worker-judge | asyncio.Queue | good | json files | **low** | **none** |

### where ship has an edge

1. **zero infrastructure**: no redis, no rabbitmq, no temporal server, no
   database. json files in `.ship/`. run it in any directory, immediately.

2. **zero framework**: 800 lines of python. no DSL to learn, no graph
   syntax, no role definitions, no conversation patterns. read the code
   in 20 minutes.

3. **CLI-native**: agents are CLI processes (claude, codex). not SDK
   objects, not API wrappers, not framework plugins. anything with a
   CLI can be a worker.

4. **project-local state**: `.ship/` per directory. run 10 instances on
   10 projects. no shared database, no coordination server, no port
   conflicts.

5. **goal-oriented**: runs until done, exits. not a daemon, not a
   service, not a platform. the opposite of infrastructure creep.

6. **heterogeneous agents**: planner uses claude, refiner uses codex.
   workers can use any CLI. no single-vendor lock-in.

### where others have an edge

- **langgraph**: conditional routing, checkpointed state recovery,
  production observability. ship has none of these.
- **temporal**: durable execution surviving crashes, automatic retries
  with backoff, multi-node distribution. ship is single-node only.
- **crewai**: role-based delegation, structured agent collaboration,
  enterprise tooling. ship has flat task parallelism.
- **celery**: battle-tested message broker, priority queues, rate
  limiting, monitoring dashboards. ship has asyncio.Queue.

### the gap ship fills

most frameworks solve the **general agent orchestration** problem:
arbitrary graphs, complex routing, persistent infrastructure.

ship solves the **coding agent coordination** problem specifically:
take a design, break it into tasks, execute them in parallel via CLI
agents, refine the result, exit. no infrastructure required.

the frameworks above are overkill for "run 4 claude instances on a
task list and check if they're done." ship is exactly right-sized.

## phases

### phase 1: shareable queue protocol (current focus)

make the task queue a shared contract that external agents can
participate in.

- [ ] define queue protocol: tasks.json schema as contract
- [ ] add file-based locking (fcntl/flock) for multi-process safety
- [ ] add `ship enqueue <description>` CLI for external task submission
- [ ] add `ship dequeue` CLI for external workers to pull tasks
- [ ] add `ship status` CLI for monitoring
- [ ] document the protocol so any CLI tool can participate

**outcome**: any process can enqueue/dequeue tasks via CLI or by
reading/writing tasks.json directly.

### phase 2: pluggable workers

decouple worker execution from claude CLI specifically.

- [ ] worker config: command template per worker type
- [ ] support codex, aider, openai-agents as worker backends
- [ ] worker capability tags (language, framework, domain)
- [ ] task routing based on capability matching
- [ ] worker health checks (timeout, crash detection)

**outcome**: `ship -w claude:2,codex:2` runs mixed worker pools.

### phase 3: lightweight persistence

graduate from json files to something multi-process safe without
requiring infrastructure.

- [ ] sqlite backend (single file, WAL mode, no server)
- [ ] atomic task transitions (PENDING->RUNNING under transaction)
- [ ] task history and audit log
- [ ] resume from any point (not just interrupted runs)
- [ ] garbage collection for old task data

**outcome**: `.ship/state.db` replaces json files. still zero
infrastructure, but ACID-safe.

### phase 4: coordination primitives

add minimal coordination without becoming a workflow engine.

- [ ] task dependencies (A blocks B)
- [ ] task groups (all in group must complete)
- [ ] priority levels (critical, normal, low)
- [ ] resource locks (only one agent writes to file X)
- [ ] git worktree isolation per worker

**outcome**: planner can express "write tests after implementation"
and workers won't conflict on shared files.

### phase 5: observability

minimal monitoring without requiring external infrastructure.

- [ ] `ship watch` - live terminal dashboard
- [ ] structured log output (jsonl)
- [ ] cost tracking per task (token usage from CLI output)
- [ ] task duration statistics
- [ ] webhook notifications (completion, failure)

**outcome**: know what's happening, what it costs, and when it's done.

## non-goals

these are explicitly out of scope:

- **web UI**: terminal is the interface
- **multi-node**: single machine only. use proper infrastructure
  (temporal, celery) if you need distributed execution
- **agent framework**: ship is a task queue, not an SDK for building
  agents. agents are external CLI processes
- **continuous daemon**: runs to completion, exits. not a service
- **marketplace/plugins**: workers are CLI commands, not plugins
- **LLM API integration**: always wraps CLI tools, never calls APIs
  directly. let the CLI tools handle auth, streaming, context

## design principles

1. **json is the protocol**: tasks.json is human-readable, git-diffable,
   and any language can read/write it
2. **CLI is the interface**: both for humans and for agent processes
3. **project-local everything**: no global state, no shared services
4. **exit when done**: goal-oriented, not infrastructure
5. **800 lines or less per module**: if it gets bigger, it's doing too much
