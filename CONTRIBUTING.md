# contributing to demiurg

contributions welcome. keep it simple.

## quick start

```bash
git clone https://github.com/kronael/demiurg
cd demiurg
make build
make test
```

## development workflow

1. fork the repository
2. create feature branch: `git checkout -b feature-name`
3. make changes (follow patterns in CLAUDE.md)
4. run tests: `make test`
5. run type checking: `make right`
6. commit with clear message: `git commit -m "add feature X"`
7. push and open pull request

## code style

follow patterns in CLAUDE.md:

- explicit enum states (use `is` not `==`)
- async locks for all state mutations
- validation before persistence
- 80 char line limit (max 120)
- single import per line

## testing

- add tests for new features
- unit tests in `demiurg/test_*.py`
- run `make test` before committing
- run `make right` for type checking

## commit messages

- lowercase, imperative mood
- format: "[section] message"
- example: "[worker] add timeout handling"
- no Co-Authored-By tags

## documentation

update relevant docs:
- README.md for user-facing changes
- CLAUDE.md for development patterns
- ARCHITECTURE.md for design changes
- SPEC.md for requirements changes

## bug reports

open issue with:
- demiurg version
- python version
- steps to reproduce
- expected vs actual behavior
- relevant logs from ./.demiurg/log/

## feature requests

open issue describing:
- use case (what problem does it solve?)
- proposed solution (how would it work?)
- alternatives considered

## pull request checklist

- [ ] tests pass (`make test`)
- [ ] type checking passes (`make right`)
- [ ] documentation updated
- [ ] commit message follows format
- [ ] changes align with project goals (see SPEC.md)

## questions

open a GitHub issue or discussion.

## license

by contributing, you agree to license your contributions under MIT license (see LICENSE).
