# Security policy

## Supported version

The latest commit on `main`. There are no releases yet.

## Report a vulnerability

Use GitHub's private vulnerability reporting: open the repository's Security tab and choose "Report a
vulnerability". Please do not open a public issue for a vulnerability, and do not attach real session records,
private paths or credentials to a report. A synthetic example is enough.

## What counts in particular

- Anything that lets file content, command text or a value reach a stored record or a report.
- Anything that makes the tool write outside its state folder, or use the network.
- A session record that makes the tool crash or hang.

## What the tool reads and stores

The tool reads the session records that coding-agent harnesses keep in your home folder, and nothing else. It
stores one file per run in its own state folder (`~/.local/state/stickyagents`, or the folder named by
`$STICKYAGENTS_HOME`), holding paths, hosts, command names and counts, never file content, command text or values.
Beside them it keeps a small index of the session files it has read (their paths, sizes and times), so that it
does not read an unchanged file again. It does not use the network, and no model is involved.

There is no bug bounty.
