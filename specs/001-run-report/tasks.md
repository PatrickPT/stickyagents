# Tasks: See what agent runs touch

One block per part of [plan.md](plan.md). `[P]` marks parts that touch separate files and can be built in parallel.

## Contract

- [x] T001 `model.py`: the shared types; `readers/__init__.py`: `load()`

## Parts

- [x] T002 [P] `zones.py`, `shell.py`, `normalise.py` with tests (US1; FR-003, FR-004, FR-005)
- [x] T003 [P] `readers/claude_code.py` with a synthetic fixture and tests (FR-001, FR-011)
- [x] T004 [P] `readers/pi.py` and `readers/opencode.py` with fixtures and tests (FR-011)
- [x] T005 [P] `rules.py` and `report.py` with tests (US1, US3, US4; FR-006, FR-007, FR-008)
- [x] T006 [P] `store.py` with tests (FR-002)

## Integration

- [x] T007 `cli.py` with tests: scan, report, harnesses (US1, US2, US5; FR-009, FR-010)
- [x] T008 `skills/stickyagents/SKILL.md`
- [x] T009 Tests for the project rules: no network module is imported; a planted marker value appears in no record
      and no report (SC-004); line counts (SC-006)
- [x] T010 README: install, first run, what a report looks like, how to add a reader
- [x] T011 Run on real session records: SC-001, SC-002 and SC-003 checked by hand
