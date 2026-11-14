# AGENTS.md

`stickyagents` shows what coding-agent runs touch. It reads the session records a harness already keeps and
reports what each run did outside its repository: folders, hosts, credential-like paths and commands outside the
sandbox. It is the first step towards a fence around agent runs: see what runs do, then decide what they should not.

## Checks

Run them before you hand over; CI runs the same.

```sh
make check      # everything below
make lint       # ruff check and format check (ruff is pinned in the Makefile)
make test       # python3 -m unittest, standard library only
```

## Rules of this project

- Standard library only at run time. No dependency, no network call, no subprocess, no telemetry.
- Never store or print file content, command text or any value: paths, hosts and command names only.
- No model takes part in recording or judging. Same input, same report.
- One module per harness under `src/stickyagents/readers/`. Nothing outside a reader knows a harness's format.
- Test data is synthetic. Never commit a real session record, a real path under a real home folder, or a real name.
- The tool stays small enough to read. `tests/test_project_rules.py` enforces the size bound (a limit on all
  of `src/stickyagents/` and a lower one for each reader), and also the no-network and standard-library rules.

## Structure

- `src/stickyagents/`: the tool. `readers/` holds one reader per harness.
- `skills/stickyagents/`: the skill, in the open Agent Skills format (`SKILL.md`).
- `tests/`: unittest, with synthetic fixtures under `tests/fixtures/`.
- `docs/`: formats (`format.md`), rules (`rules.md`), harnesses (`harnesses.md`) and known errors.
- `specs/`: the specs.

## Specs

A larger change starts with a spec under `specs/NNN-<name>/`: `spec.md` says what and why, `plan.md` how. The
first one, `specs/001-run-report`, describes the current design.

## Known errors

`docs/known-errors.md`: read it before you start; add an entry when you hit something another agent could hit
here.

## Working here

- One change per branch and pull request.
- Tests come with the change.
- Never weaken a test or a check to get green. Fix the cause, or say in the pull request why the check is wrong.
- Read `docs/known-errors.md` first.
