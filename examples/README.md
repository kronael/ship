# ship examples

unattended harness for coding agents. give it a spec,
it builds the thing.

## install

```bash
pip install ship
# or from source
cd ship && make install
```

requires claude code CLI, authenticated.

## install planship skill

planship lets Claude Code write specs for you, then
launches ship automatically. copy the skill into your
Claude Code skills directory:

```bash
cp -r skills/planship ~/.claude/skills/
```

## two workflows

### manual spec ([simple/](simple/))

write a SPEC.md yourself, run `ship`. best when you
know exactly what you want.

```bash
mkdir my-project && cd my-project && git init
# write SPEC.md
ship
```

### planship ([advanced/](advanced/))

let Claude Code explore your codebase, draft specs,
then ship. best for larger features or unfamiliar
codebases.

```
/planship build a REST API with user auth
```

## spec format

ship reads `SPEC.md` or `specs/*.md`. each spec needs
deliverables with concrete acceptance criteria:

```markdown
# Component Name

## Goal
what this component delivers

## Deliverables

### 1. Feature name
- **Files**: src/foo.py, tests/test_foo.py
- **Accept**: testable criteria
- **Notes**: patterns to follow

## Constraints
- conventions, boundaries

## Verification
- [ ] how to know it works
```

see [simple/SPEC.md](simple/SPEC.md) for a runnable
example.
