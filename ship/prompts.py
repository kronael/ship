"""all LLM prompts in one place. uses str.format() for interpolation."""

VALIDATOR = """\
You are a strict design reviewer for Ship's planner-worker-judge flow.
Decide if the design is specific enough that the planner can generate \
concrete tasks and the workers can produce a clear, verifiable outcome.

Design:
{design_text}

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

FIRST: Write a PLAN.md file to the project root. This is the execution \
plan that workers will follow. Format:

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
<context>Brief 1-2 sentence description of what's being built and key \
technologies</context>
<tasks>
<task>Create go.mod with module name and dependencies</task>
<task>Implement HTTP server with health endpoint</task>
</tasks>
</project>

Rules for tasks:
- CRITICAL: Each task must be completable in 2 days or less - break \
large features into smaller subtasks
- Keep tasks small and focused on a single, concrete action
- Each task is a concrete, completable coding action
- Task description starts with a verb (Create, Add, Implement, Write)
- Skip explanations, examples, documentation
- Consolidate related items when sensible, but prefer smaller tasks \
over large ones"""

WORKER = """\
{context}\
{skills}\
You have a {timeout_min}-minute timeout. If you time out, the task \
will be retried automatically. Focus on making progress.

Task: {description}

When done, append a 1-line summary to LOG.md (create if missing). \
Format: `- <what you shipped>`. Keep it brief."""

JUDGE_TASK = """\
A worker just completed this task:
  {description}

Its output (truncated):
  {result}

Read the files it claims to have created/modified. In one sentence: \
did it actually complete the task? If not, what's wrong?

Append your verdict to PROGRESS.md under a ## log section. \
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

If follow-up tasks are needed, output them. If done, output empty.

<tasks>
<task>description of follow-up work</task>
</tasks>

Or if complete:
<tasks>
</tasks>"""

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

1. Update PROGRESS.md with a final ## assessment section:
   what percentage of the goal is met, what's missing, quality notes.

2. If work is missing, output new tasks. If goal is met, output empty.

<tasks>
<task>specific missing work</task>
</tasks>

Or if complete:
<tasks>
</tasks>"""
