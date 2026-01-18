# building demiurg: autonomous coding with planner-worker-judge

we built demiurg to test cursor's planner-worker-judge pattern outside their IDE. turns out the pattern works brilliantly for command-line workflows, but the interesting lessons were in the details they didn't mention.

## the core idea

cursor's blog post on scaling agents described breaking goals into tasks, executing them in parallel, and polling for completion. simple pattern, proven at scale. we wanted to see if it worked using claude code CLI directly instead of their proprietary backend.

it does. but the devil's in the details.

## lesson 1: state location breaks everything

first implementation used global state at `~/.demiurg/data/`. seemed reasonable - why scatter state files everywhere?

problem: you can't run demiurg on two projects simultaneously. state mixing, task confusion, race conditions. debugging was hell.

**fix**: project-local `./.demiurg/` per directory. obvious in retrospect. now you can run 10 instances, no conflicts. state isolation isn't optional, it's foundational.

## lesson 2: streaming vs buffering changes user experience

original workers called `claude -p <task>` and buffered output. user saw:
```
working...
[30 seconds of silence]
working...
goal satisfied
```

terrifying. is it stuck? is it working? no feedback.

**fix**: stream claude's stdout line-by-line. now you see:
```
[worker-0] Create hello.py
  I've created hello.py with a greet function...
[worker-0] ✓ completed
```

same underlying execution, 10x better UX. streaming isn't about performance, it's about trust.

## lesson 3: types.py masks built-in types module

named dataclasses file `types.py`. seemed clean. then debugging got weird - `import types` wasn't importing what we expected in some contexts.

**fix**: `types_.py` with underscore suffix. ugly but unambiguous. naming conflicts with built-ins are silent killers. better to look ugly than fail mysteriously.

lesson: python's flat namespace means common names are landmines.

## lesson 4: timeout tuning is load-dependent

started with 30s timeout per task. seemed generous.

reality: simple tasks (create hello.py) finish in 10s. complex tasks (write comprehensive tests) need 45s. with 30s timeout, half the tasks were timing out despite being processable.

**fix**: 60s default. still enforces progress, rarely times out legitimate work. but the real insight is that timeout isn't a correctness parameter, it's a cost/reliability tradeoff. too low = spurious failures, too high = burning money on infinite loops.

cursor probably has dynamic timeouts based on task complexity. we went with static 60s because simpler.

## lesson 5: worker scaling is anti-linear

configured 4 workers by default (following cursor). makes sense - parallelism good.

problem: on 3-task projects, spawning 4 workers means 1 sits idle. on 1-task projects, 3 workers start then immediately exit.

**fix**: `workers = min(configured, pending_tasks)`. don't spawn workers with nothing to do.

the interesting bit: even with this fix, 4 workers isn't always optimal. task dependencies matter. if task B needs task A's output, parallel execution gains nothing. the planner doesn't model dependencies (cursor's doesn't either), so effective parallelism is often lower than worker count suggests.

future work: dependency analysis in planner to enable actual parallel speedup.

## lesson 6: .env vs TOML is a UX tradeoff

started with python-dotenv loading global + local config files. flexible, precedence clear.

problem: users don't know where to put config. `~/.demiurg/config`? `./.demiurg`? `.env`? too many options = confusion.

**fix**: just `.env` in project root, environment variables override. simpler mental model. global config wasn't needed - if you want global settings, use `~/.bashrc`.

lesson: flexibility is a cost. constrain choices to reduce cognitive load.

## lesson 7: progress visibility needs three levels

1. **macro**: N/M tasks completed
2. **meso**: which task is each worker executing
3. **micro**: what is claude doing right now

original version only had level 1. useless. can't tell if worker is stuck or just slow.

final version has all three:
```
progress: 2/5 tasks completed
workers: 4

[worker-0] Add error handling
  Adding try/catch blocks to handle edge cases...
[worker-0] ✓ completed
```

macro tells you overall progress, meso shows distribution, micro shows liveness. all three needed for trust.

## lesson 8: judge polling is surprisingly robust

judge polls state every 5s checking if all tasks complete. sounds naive - what about race conditions? what if task completes between polls?

turns out: doesn't matter. workers update state synchronously under async lock, judge reads state under same lock. polling is just a trigger for checking completion, not a synchronization primitive.

5s interval is arbitrary but works. shorter = more CPU, longer = slower exit. sweet spot seems to be 3-10s for human-scale workflows.

## lesson 9: claude code CLI is the right abstraction layer

we could have used anthropic API directly (streaming, cheaper, more control). chose to use claude code CLI instead.

**why**: claude code handles tool use, file operations, bash execution, context management. reimplementing that is months of work.

**tradeoff**: we're at mercy of claude's CLI stability. output format changes break us. but the velocity gain from not reimplementing tool orchestration is worth it.

lesson: build on the highest stable abstraction you can find.

## what we'd change

1. **dependency tracking**: planner should detect "write tests for foo.py" depends on "create foo.py"
2. **dynamic timeouts**: estimate task complexity from description, adjust timeout accordingly
3. **cost tracking**: show token usage per task, total cost per run
4. **partial results**: if task fails, save partial work instead of discarding
5. **interactive mode**: pause on errors, let user fix, resume

## what surprised us

- project-local state wasn't obvious until global state broke
- streaming made 10x UX difference with ~20 lines of code
- worker count auto-adjustment matters more than we expected
- types_ naming conflict bit us in subtle ways (not a crash, just confusion)
- users care more about progress visibility than execution speed

## conclusion

planner-worker-judge works outside cursor. pattern is sound. interesting bits are in state management, streaming, and UX polish.

if you're building agent orchestration: isolate state, stream everything, tune timeouts empirically, show progress at multiple granularities.

code at github.com/kronael/demiurg - 800 lines total, most of it state management and progress reporting.
