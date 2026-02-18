# advanced: planship workflow

let Claude Code explore your codebase, design specs,
then ship automatically.

## install planship

the planship skill must be in `~/.claude/skills/`:

```bash
cp -r skills/planship ~/.claude/skills/
```

verify it's loaded -- in Claude Code, `/planship`
should autocomplete.

## walkthrough

### 1. open project in Claude Code

```bash
cd my-project
claude
```

### 2. invoke planship

```
/planship build a REST API with user auth
```

natural language goal. planship handles the rest.

### 3. what planship does

1. **explore** -- reads codebase, existing specs,
   project structure, CLAUDE.md
2. **draft** -- designs deliverables with concrete
   acceptance criteria per component
3. **ask** -- presents the plan, asks if you want one
   spec per component or a single combined spec
4. **write specs** -- creates `specs/<name>.md` files
   with structured sections (Goal, Deliverables,
   Constraints, Verification)
5. **launch ship** -- runs `ship` against the generated
   specs

### 4. ship executes

once planship writes the specs, ship takes over with
the full pipeline:

```
specs/*.md -> validator -> planner -> workers -> judge -> verifier
```

watch progress in real-time. ship writes `PROGRESS.md`
and `.ship/log/` as it runs.

### 5. iterate

planship works incrementally. it detects existing specs
and shipped work, only plans and ships the delta:

```
/planship add rate limiting to the auth endpoints
```

reads the existing code (including what ship just
built), drafts new specs for the delta, ships again.

## when to use planship vs manual spec

**planship:**
- high-level goal, details not designed yet
- unfamiliar codebase, want Claude to explore first
- feature touches many files, want automatic spec
  decomposition

**manual spec:**
- know exactly what you want built
- small, well-scoped feature
- want full control over deliverables and constraints

## options

planship passes flags through to ship:

```
/planship build X -w 2      # limit workers
/planship build X -x        # enable codex refiner
```
