# stickyagents

**See what your coding agents got their fingers on.**

Coding agents run with your access. After a session you know what they changed in the repository, because git
shows it. You don't know what else they touched: which folders outside the repo, which hosts, which key files.

`stickyagents` reads the session records your agent harness (Claude Code, Pi or opencode) already keeps and tells
you. One command, nothing to install into the harness, nothing sent anywhere. A sample report, with invented data:

```text
$ stickyagents report
stickyagents: claude-code run 0a1b2c3d in ~/project, started 2026-01-05T10:00:00.000Z
212 tool calls, 158 (75%) were shell commands. Targets of shell commands are mentions, not proven
touches.
Calls by kind: read 31, write 8, shell 158, fetch 0, search 0, other 15. By subagents 0, refused 0,
outside the sandbox 0.

Outside the repo
  zone         exact reads exact writes shell mentions  top folders
  credential             1            0              2  ~/.ssh/id_ed25519 (3)
  scratch                0            3             21  /tmp/build (24)
  home                   4            0              9  ~/Code/other-project (13)

Network: no host or channel recorded.

Findings
  critical  C001  A credential-like path was read or written with a file tool (1x)
                  e.g. ~/.ssh/id_ed25519
                  Check what the file holds. If it is a live credential, rotate it and keep such
                  files away from agent runs.
  high      C002  A credential-like path was named in a shell command (2x)
                  e.g. ~/.ssh/id_ed25519
                  Check whether the agent needs this credential. If it does, give it one that is
                  scoped to this repo and short-lived, instead of your personal one.

No earlier runs in this repo: nothing is marked as first seen.
```

## Run it

You need `uv`, which provides `uvx`.

```sh
uvx --from git+https://github.com/PatrickPT/stickyagents stickyagents          # every run on this machine
uvx --from git+https://github.com/PatrickPT/stickyagents stickyagents report   # the newest run that started here
```

From a clone, `PYTHONPATH=src python3 -m stickyagents.cli` does the same with Python 3.10 or newer alone. `--json`
gives the report as data, `--session <id>` picks one run, and `stickyagents harnesses` shows what it finds.

## What you get

- **A report per run and a summary over all runs**: touches outside the repo by zone, network hosts, refusals, and
  commands that left the sandbox.
- **Findings with advice** from [fixed rules](docs/rules.md). No model is involved: the same run always gives the
  same report.
- **History**: each run is compared with earlier runs of the same repo, and what is new is marked as first seen.
- **Three harnesses today**. [How well each is covered, and how to add one](docs/harnesses.md).
- **An agent skill** in [`skills/stickyagents`](skills/stickyagents/SKILL.md), in the open Agent Skills format: copy
  the folder into your agent's skills and ask "what did this run touch?".

## What it can and cannot see

A call to a file tool is an exact touch. A shell command is only text: the report can say that a command *named* a
path or a host, not that it read or reached it. Most agent work goes through the shell, so every report states that
share on its first lines and keeps the two kinds apart.

## Privacy

`stickyagents` uses the standard library only and never opens a network connection. It stores paths, hosts and
command names, with your home folder written as `~`, and never file content, command text or values. Records live
in `~/.local/state/stickyagents`, readable by you alone. [The stored format](docs/format.md) is documented.

## Where this is going

This is the first step towards a fence around agent runs: see what runs do, then decide what they should not do.
The next step is a fence built from these reports and enforced by a sandbox, which also gives exact sight into
the shell.

## Contributing

The project is young and small on purpose. A reader for another harness is the most useful first contribution.
See [CONTRIBUTING.md](CONTRIBUTING.md), and [SECURITY.md](SECURITY.md) for reporting a vulnerability.
Everyone who takes part follows the [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).

## License

[Apache-2.0](LICENSE).
