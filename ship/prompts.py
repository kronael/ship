"""all LLM prompts in one place. uses str.format() for interpolation."""

VALIDATOR = """\
You are a strict design reviewer for Ship's planner-worker-judge flow.
Decide if the design is specific enough that the planner can generate \
concrete tasks and the workers can produce a clear, verifiable outcome.

Design:
{design_text}
{context_section}
Return ONLY this XML:
<validation>
<decision>accept|reject</decision>
<gaps>
<gap>Missing explicit target language/framework</gap>
</gaps>
<project>
...PROJECT.md content if accepted...
</project>
</validation>

Rules:
- Reject if key details are missing (language, runtime, interface/IO, \
scope, constraints).
- Reject if the desired end state is not clearly testable or observable.
- Reject if the design would likely produce ambiguous tasks or unclear \
"done" criteria.
- If accepted, output empty <gaps></gaps>.
- If accepted, generate a concise PROJECT.md that clarifies the goal, \
stack, IO surfaces, constraints, and success criteria. Use markdown.
- If rejected, output empty <project></project>.
- Be concise and specific in each gap."""

PLANNER = """\
Analyze this design document and extract:
1. A brief project context (what's being built, language/framework, \
purpose)
2. Executable tasks

<design>
{goal}
</design>

FIRST: Write the execution plan to {plan_path}. \
Workers will read this file. Format:

```markdown
# PLAN

## goal
<one sentence>

## approach
<2-3 sentences on architecture/strategy>

## tasks
- [ ] task 1 description
- [ ] task 2 description
...
```

THEN: Return ONLY this XML:

<project>
<context>4-6 sentences: what's being built, key technologies, main \
modules/files, important patterns or constraints workers must know. \
This is the only context workers get — make it count.</context>
<mode>parallel|sequential</mode>
<tasks>
<task worker="auto">Create go.mod with module name and dependencies</task>
<task worker="auto">Implement HTTP server with health endpoint</task>
<task worker="auto" depends="1,2">Write integration tests for health endpoint</task>
</tasks>
</project>

Rules for mode:
- parallel: workers can run tasks concurrently (default, safer choice)
- sequential: tasks must run one at a time (only if tasks will conflict)
- Use sequential if tasks modify the same files or have tight dependencies
- When in doubt, use parallel - ship will handle conflicts gracefully

Rules for worker assignment:
- worker="auto": ship assigns dynamically (default, use for most tasks)
- worker="w0": pin to specific worker (use for ordered sequences)
- Pin tasks that must run in order to the same worker
- Leave unrelated tasks as "auto" for parallel execution

Rules for tasks:
- CRITICAL: Each task must be completable in 2 days or less - break \
large features into smaller subtasks
- Keep tasks small and focused on a single, concrete action
- Each task is a concrete, completable coding action
- Task description starts with a verb (Create, Add, Implement, Write)
- Skip explanations, examples, documentation
- Consolidate related items when sensible, but prefer smaller tasks \
over large ones
- Use depends="N" or depends="N,M" to declare dependencies on \
earlier tasks (1-indexed). Tasks without depends can run in parallel"""

WORKER = """\
{context}\
Before starting: read {plan_path} (execution plan) and CLAUDE.md \
(project patterns) if they exist — they contain architecture and \
conventions that will save you from re-exploring the codebase.

You have a {timeout_min}-minute timeout. If you time out, the task \
will be retried automatically. Focus on making progress.

While working, output brief status updates using this tag:
<progress>what you're doing now</progress>

Rules:
- Emit after every 2-3 tool calls
- Keep under 15 words
- Report concrete outcomes, not intentions:
  - After writing: "created src/auth.rs (+85 lines)"
  - After editing: "edited gateway.rs (+12/-4 lines)"
  - After deleting: "removed old_handler.rs"
  - After tests: "cargo test: 12 passed, 2 failed"
  - After builds: "cargo check: ok" or "cargo check: 3 errors"
  - While reading: "reading risk engine (3 files)"

Task: {description}

When done, append a 1-line summary to {log_path} (create if missing). \
Format: `- <what you shipped>`. Keep it brief.

After your LOG.md entry, output this structured block. \
Before the status tag, output a 3-5 word outcome summary:
<summary>fixed auth bug</summary>
Keep it concrete: what was done, not what was attempted. \
Examples: "added 3 tests", "fixed ws reconnect", "patched serialization"
<status>done</status>

If you could NOT fully complete the task, output:
<status>partial</status>
<followups>
<task>description of remaining work</task>
</followups>"""

JUDGE_TASK = """\
A worker just completed this task:
  {description}

Its output (truncated):
  {result}

Read the files it claims to have created/modified. In one sentence: \
did it actually complete the task? If not, what's wrong?

Append your verdict to {progress_path} under a ## log section. \
Format: `- HH:MM task: verdict`. Create the file/section if missing."""

REFINER = """\
Critique this project's progress. Be strict.

Project: {project_context}

{progress_section}

Completed tasks:
{completed_summary}

Failed tasks:
{failed_summary}

Questions:
1. Any obvious gaps? (missing tests, broken integration, etc)
2. Do failed tasks need alternative approaches?
3. Anything the judge flagged as incomplete?

If follow-up tasks are needed, output them:

<tasks>
<task>retry with different approach</task>
<task>description of new follow-up work</task>
</tasks>

Or if complete:
<tasks>
</tasks>"""

VERIFIER = """\
You are an adversarial reviewer. Prove the objective is NOT met.

Objective:
{goal_text}

Project: {project_context}

Read the codebase. Generate exactly 10 concrete challenges \
that could expose the objective as incomplete or broken.

Rules:
- Stay strictly within the stated objective
- Do NOT invent requirements not in the objective
- Each challenge must be a task a coding agent can execute
- Be adversarial: target integration gaps, edge cases, \
silent failures
- Phrase each as imperative: "Verify that...", "Check that..."

<challenges>
<challenge>specific check to run</challenge>
</challenges>"""

REPLANNER = """\
Full project assessment. Compare the original goal against what was \
actually built.

Project: {project_context}

Original goal:
{goal_text}

{plan_section}

{progress_section}

Completed:
{completed_summary}

Failed:
{failed_summary}

Read the actual codebase. Compare against the goal.

1. Update {progress_path} with a final ## assessment section:
   what percentage of the goal is met, what's missing, quality notes.

2. If work is missing, output new tasks. If goal is met, output empty.

<tasks>
<task>specific missing work</task>
</tasks>

Or if complete:
<tasks>
</tasks>"""
