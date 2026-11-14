# Formats

What is stored, and what a report is made of. Both carry paths, hosts, command names and counts, never file content,
command text or values.

## The stored record

One JSON-lines file per run, `runs/<harness>/<session>.jsonl` under the state folder, mode 600. Keys are sorted.
Beside `runs/`, `sources.json` lists each session file already read, by path (home as `~`) with its modification time
and size, so that an unchanged file is not read again.

**Line 1, the meta:** `schema` (1), `harness`, `session`, `start` (the folder the run started in), `started`,
`source` (where the harness keeps the session), `modes` (permission modes, in the harness's words), `state_dirs`
(the harness's own folders), `siblings` (other worktrees of the repo). Home folders are shown as `~`.
`started` and every event `time` are UTC with milliseconds, such as `2026-02-04T09:00:00.000Z`. `started` is null
when the record has no readable time; an event without one has no `time` key.

**Every other line, one event.** Fields that do not apply are left out. Always there: `kind`, `tool` (the harness's
tool name, or `other` when it is not a plain name), `sub` (made by a subagent), `exact` (false when it comes from
shell text). Then by `kind`:

| kind | fields | meaning |
|---|---|---|
| `call` | `call_kind` (`read`, `write`, `shell`, `fetch`, `search`, `other`), `unsandboxed`, `refused` | one per tool call |
| `touch` | `mode` (`read`, `write`, `mention`), `zone`, `target` | a path; exact for file tools, a mention for shell text, which keeps four path segments (`~` counts as one) |
| `net` | `target` | a host, or a channel such as `git remote` or `web search` |
| `cmd` | `target` | a command name seen in shell text |
| `flag` | `target` | `sudo`, `pipe-to-shell`, `force-push` or `push-main` |

Zones: `credential`, `repo`, `sibling`, `scratch`, `agent-state`, `home`, `system`.

## The report on one run (`stickyagents report --json`)

Top-level keys: `schema` (1), `run` (`harness`, `session`, `start`, `started`, `modes`), `limits` (`calls`,
`shell_calls`, `shell_share`, `note`), `calls` (a count per call kind, and `sub`, `refused`, `unsandboxed`; a refused
call is not counted as unsandboxed), `outside_repo` (per zone: `exact` with `read` and `write`, `mentions`, and `top`
folders as `[folder, count]`), `network` (`exact` and `mentions`, each a list of `[host, count]`), `findings` (each
`rule`, `severity`, `title`, `advice`, `count`, `examples`) and `history` (`runs`, the earlier runs compared with).

## The summary (`stickyagents summary --json`)

Top-level keys: `schema` (1), `runs`, `harnesses` (runs per harness), `calls`, `shell_calls`, `shell_share`, `note`
(the same limits as above), `zones` (per zone outside the repo: `exact` and `mentions`, each with `runs` and
`share`), `network` (up to ten `[host, runs]`), `findings` (each `rule`, `severity`, `title`, `advice`, `runs`,
`count`) and `top` (the ids of the three most frequent rules).
