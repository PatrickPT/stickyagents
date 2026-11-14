# Harnesses

`stickyagents` reads the session records that coding-agent harnesses keep on disk. Each harness has one reader.
The readers are not equally well backed, and this page says how well each one is.

## What is read today

**Claude Code.** Well covered: checked against many real sessions. Subagent files, refusals and permission modes
are read.

**Pi.** Lightly covered: checked against little real data. The `grep` tool, permission modes and refusals were
not seen in real data. Pi has no permission prompts, sandbox or subagents of its own, so the reader reports no
modes, refusals or unsandboxed commands.

**opencode.** Thinly covered: checked against very little real data. Only the shell, read and grep tools have been
seen in real records. Other tool names, the refusal markers and the link to a subagent come from the project's source
and have not been seen in real records. Treat its reports as a first look.

If a report from one of these readers looks wrong, open an issue with a synthetic sample of the record shape.

## Add a harness

A reader is one module under `src/stickyagents/readers/`. It has four parts, described in
`src/stickyagents/readers/__init__.py`:

- `NAME`: the harness's name, such as `"claude-code"`.
- `STATE_DIRS`: the harness's own folders, as `~/...`.
- `find(home)`: every session source found under the home folder, as a list of paths.
- `read(path, home)`: the sessions in that source, as a list of `Run`. It returns an empty list when the file is
  not a session, and it never raises on bad input.

A `Run` holds a `RunMeta` and a list of `ToolCall`, both defined in `src/stickyagents/model.py`. Each `ToolCall`
has a `kind`, and the kind decides which fields you fill:

| kind | fields |
|---|---|
| `read`, `write` | `paths`, as the harness recorded them |
| `shell` | `command`, and `unsandboxed` when the call asked to leave the sandbox |
| `fetch` | `url` |
| `search` | none beyond `tool` |
| `other` | none beyond `tool` |

Also set `tool` (the harness's own name), `time`, `sub` (made by a subagent) and `refused` where the record shows
them. `command` and `url` stay in memory; the normaliser drops them.

A reader must not:

- decide zones or apply rules. It reports what the record says, and nothing after it needs the harness's format;
- keep anything beyond what `ToolCall` holds, such as file content or output;
- import the network, `subprocess` or a package outside the standard library.

You need a test with a synthetic fixture under `tests/fixtures/`: invented paths, invented ids, no real session.
See `tests/test_reader_claude_code.py` for the shape. A reader stays under 150 lines; the test
`tests/test_project_rules.py` checks it. When it works, add the module name to `MODULES` in
`src/stickyagents/readers/__init__.py`. Nothing else changes.

## Wanted next

Codex CLI, Gemini CLI, Cursor's agent and Aider. If you use one of them, a synthetic sample of its record format
is already a useful contribution; see the harness issue form.
