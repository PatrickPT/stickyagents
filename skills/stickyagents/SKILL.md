---
name: stickyagents
description: Report what a coding-agent run touched outside its repository (folders, hosts, credential-like paths, commands outside the sandbox), from the session records the harness keeps. Use when asked what a run or session touched, whether it left the repo, what agents have been doing on this machine, or for a risk report on agent runs.
---

# stickyagents

`stickyagents` reads the session records of the agent harness and reports what runs touched. It uses fixed rules,
makes no network calls and stores no file content, command text or values.

## One run

For the newest run that started in this folder or in a folder above it (this is not necessarily the session you
are in):

```sh
stickyagents report
```

For another run, give the session id or its first characters: `stickyagents report --session <id>`.

## All runs on this machine

```sh
stickyagents summary
```

## As data

Add `--json` to either command when another tool or agent will read the result.

## If the command is missing

Run it straight from the repository, with nothing installed:

```sh
uvx --from git+https://github.com/PatrickPT/stickyagents stickyagents report
```

## How to pass the result on

- Show the report as it is. Do not shorten the limits at its top: they say how much of the run was shell commands,
  whose targets are mentions and not proven touches.
- Do not add findings of your own and do not soften the ones listed. The findings come from fixed rules.
- If asked what to do next, quote the advice lines of the findings.
