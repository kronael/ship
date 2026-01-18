# specification

## goal

demonstrate planner-worker-judge pattern for scaling autonomous agents to large codebases, based on cursor's blog post.

goal-oriented execution: runs until satisfied, then exits (not a daemon).

## requirements

### execution model

- one-off execution (not continuous daemon)
- single planner at startup (generates all tasks upfront)
- workers execute tasks until complete
- judge polls for completion, exits when done
- no http api (removed for simplicity)
- no cycles (runs once until complete)

### agent coordination

- planner runs once at startup
- workers execute tasks independently without coordination
- judge polls state and exits when complete
- no locks between agents (only state manager uses asyncio.Lock)

### task management

- tasks have explicit states: pending, running, completed, failed
- tasks persist to disk (survive restart)
- queue unbounded, regenerated from pending tasks on continuation
- workers block on empty queue (no polling)

### state persistence

- all state stored as json files at ./.demiurg/ (project-local)
- tasks.json contains all task metadata
- work.json contains design_file, goal_text, is_complete flag
- state written on every change
- state loaded on startup
- each project has isolated state directory

### concurrency

- single planner (runs once)
- configurable number of workers (default 4)
- single judge (polls every 5s)
- graceful shutdown on KeyboardInterrupt
- asyncio task cancellation propagates to workers

### configuration

- .env config files (not toml)
- precedence: env vars > ./.demiurg > ~/.demiurg/config
- all settings have defaults (no required API keys)
- uses claude code CLI session for authentication

### logging

- unix timestamp format (2026/01/16 08:00:00)
- lowercase messages
- logs to ./.demiurg/log/demiurg.log (project-local)
- configurable log directory

## constraints

- single node only (no distributed coordination)
- in-memory queue (regenerated from state)
- python with asyncio (not Go)
- uses claude code CLI (not direct API calls)
- no git operations (workers use claude code CLI which has git access)
- no sub-planner spawning
- no conflict resolution
- no task retry logic
- no http api

## non-goals

- production deployment
- horizontal scaling
- high availability
- direct LLM API integration (uses claude code CLI instead)
- version control integration (relies on claude code CLI git access)
- web ui
- metrics collection
- observability platform integration

this is a demonstration implementation for learning the planner-worker-judge pattern.
