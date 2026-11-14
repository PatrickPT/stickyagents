# Implementation Plan: See what agent runs touch

**Branch**: `feat/001-run-report` | **Date**: 2026-11-13 | **Spec**: [spec.md](spec.md)

## Summary

A reader per harness turns session records into neutral tool calls. One normaliser turns tool calls into events
(zones for paths, facts from shell text). Events are stored per run. Fixed rules give findings; a report shows one
run, a summary shows many. No model, no network, standard library only.

## Technical Context

**Language/Version**: Python 3.10 or newer, standard library only (`sqlite3` for opencode's records)

**Storage**: one JSON-lines file per run under `${STICKYAGENTS_HOME:-${XDG_STATE_HOME:-~/.local/state}/stickyagents}`,
mode 600 in a folder of mode 700

**Testing**: `unittest`, synthetic fixtures under `tests/fixtures/`; `make check` (ruff, tests)

**Target Platform**: Linux and macOS

**Constraints**: no network use; no file content, command text or values stored or printed; same input, same output

## Flow

```text
harness records ──reader──▶ Run(meta, tool calls) ──normalise──▶ Record(meta, events) ──store──▶ runs/<harness>/<id>.jsonl
                                                                        │
                                                    rules.evaluate(record, history) ──▶ findings
                                                                        │
                                                          report.build / render ──▶ text and data
```

## Modules and their contracts

All in `src/stickyagents/`. A module only uses what is listed here from the others.

### `model.py` (the shared types)

- `ToolCall`: `time`, `tool` (the harness's name for it), `kind` (`read`, `write`, `shell`, `fetch`, `search`,
  `other`), `paths`, `command` (shell text, in memory only), `url`, `sub` (made by a subagent), `unsandboxed`,
  `refused`.
- `RunMeta`: `harness`, `session`, `start` (the folder the session started in), `started`, `source`, `modes`
  (permission modes the record shows, in the harness's words), `state_dirs`, `siblings`.
- `Run`: `meta` and `calls`. What a reader returns; paths are absolute.
- `Event`: `kind` (`call`, `touch`, `net`, `cmd`, `flag`) with `time`, `tool`, `sub`, `exact`, and by kind: `call_kind`,
  `unsandboxed`, `refused` (call); `mode` (`read`, `write`, `mention`), `zone`, `target` (touch); `target` (net: host
  or channel; cmd: command name; flag: pattern id).
- `Record`: `meta` and `events`. What is stored; every path is shown with the home folder as `~`.
- `Finding`: `rule`, `severity`, `title`, `advice`, `count`, `examples` (at most five targets).

### `readers/` (one module per harness)

Each reader module has `NAME`, `STATE_DIRS` (the harness's own folders, as `~/…`), `find(home) -> list[Path]` and
`read(path, home) -> list[Run]`: the sessions in that source, since one database can hold many. `read` returns an
empty list for something that isn't a session and never raises on bad input. `readers.load()` returns the reader modules. Nothing outside a reader knows a harness's format, and a reader
knows nothing about zones or rules.

### `zones.py`

`classify(path, meta, home) -> (zone, shown)`, or `None` when the path is no touch, and `find_siblings(start)` for the
other worktrees of a repo. Zones, first match wins: `credential` (a fixed pattern table), `repo`
(under `meta.start`), `sibling` (under a folder in `meta.siblings`), `scratch` (temp folders), `agent-state` (under
`meta.state_dirs`), `home`, `system`. `/dev/*` is no touch, except `/dev/shm`, which is scratch. `shown` has the home folder as `~`.

### `shell.py`

`parse(command) -> ShellFacts(commands, paths, hosts, flags)`: command names per pipeline segment (heredoc bodies
and assignments skipped), absolute and `~/` path tokens, hosts from URLs and channels from known network commands
(`gh`, `git push`, `curl`, `ssh`, `npm`, `pip`, …), and flags: `sudo`, `pipe-to-shell`, `force-push`, `push-main`.
Everything from here is a mention, never exact.

### `normalise.py`

`normalise(run, home) -> Record`: one `call` event per tool call; `touch` events for file tools (exact) and for
shell paths (mention); `net` events for fetches (exact), searches and shell hosts (mention); `cmd` and `flag`
events from shell facts. It drops `command` and `url` beyond the host.

### `store.py`

`base() -> Path`, `save(record) -> Path` (atomic, idempotent per harness and session), `load_all() -> list[Record]`.
First line of a file is the meta with `schema: 1`, then one event per line.

### `rules.py`

`RULES`: a list of `Rule(id, severity, title, advice, match)`. `evaluate(record, history) -> list[Finding]`, most
severe first. `history` holds earlier records of the same `start` folder or its siblings. First rules: a credential
path read by a file tool; a credential path named in shell; a file-tool write to the home folder or the system; a
command outside the sandbox; a session without permission prompts; `sudo`; a download piped to a shell; a startup
or key file written with a file tool or named in shell text; a write to the harness's own settings; a force push or
push to `main`; a zone, host or credential path first seen in this repo.

### `report.py`

`build(record, findings, history) -> dict` and `render(data) -> str` for one run; `build_summary(records, findings)
-> dict` and `render_summary(data) -> str` for many. The dict has `schema: 1`. Limits come first in the text: the
share of calls that were shell commands, and that shell targets are mentions.

### `cli.py`

`stickyagents` (scan every harness found, store, print the summary), `stickyagents report [--session ID] [--json]`
(the newest run that started in or above the current folder), `stickyagents summary`, `stickyagents harnesses`.
Scanning skips a source whose modification time and size are unchanged since the last scan (kept in `sources.json`
in the state folder).

### `skills/stickyagents/SKILL.md`

The open Agent Skills format. It tells an agent to run `stickyagents report` and pass the output on unchanged.

## Complexity Tracking

| Addition | Why needed | Simpler alternative rejected because |
|---|---|---|
| Three readers instead of one | The tool is meant to be vendor neutral, and a seam with one implementation isn't tested | One reader would bake Claude Code's shapes into the model |
| A stored record beside the harness's own | History for "first seen", and harnesses delete old sessions | Re-reading sessions each time loses history |
