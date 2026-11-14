# Rules

Each rule is one entry in the `RULES` table in `src/stickyagents/rules.py`. A finding is "exact" when it comes from
a file-tool call, and a "mention" when it comes from a path-like word in a shell command, which is not proof that
the command touched anything. The H rules compare a run with earlier runs of the same repo, so they give no finding
until the tool has stored earlier runs.

| Id | Severity | Title | Advice |
|---|---|---|---|
| C001 | critical | A credential-like path was read or written with a file tool | Check what the file holds. If it is a live credential, rotate it and keep such files away from agent runs. |
| C002 | high | A credential-like path was named in a shell command | Check whether the agent needs this credential. If it does, give it one that is scoped to this repo and short-lived, instead of your personal one. |
| W001 | high | A file tool wrote outside the repo | Check that each write was intended. A run should write inside its repo and scratch folders only; make other changes yourself. |
| W002 | critical | A startup or key file was written with a file tool | Review the file and undo any change you did not ask for. These files run code or grant access at every login, so keep them out of the agent's reach. |
| W003 | high | A startup or key file was named in a shell command | Check whether the command changed the file: naming it is not proof of a write. If it did, review the change. |
| W004 | high | A file tool changed the harness's own settings | Review the change and undo it if you did not ask for it. Settings and hooks decide what later runs may do, so keep them out of the agent's reach. |
| S001 | high | A shell command ran outside the harness's sandbox | Check which commands needed this. Allow those by name and keep everything else inside the sandbox. |
| S002 | medium | The session ran without permission prompts | Run without prompts only inside a sandbox or on a machine you can throw away. Elsewhere, keep the prompts and allow routine commands by name. |
| S003 | high | A shell command used sudo | Do not give agent runs root. Run the privileged step yourself, from a script you have read. |
| S004 | high | A download was piped into a shell | Download the script to a file and read it before running it. Pin a version or checksum if the step repeats. |
| G001 | medium | A force push was named in a shell command | Check the remote branch for lost commits. Protect shared branches against force pushes on the server. |
| G002 | medium | A push to main was named in a shell command | Check what reached main. Protect the branch, so that changes arrive through pull requests only. |
| H001 | medium | First seen in this repo: a zone outside the repo | Check why this run needed a place that no earlier run touched. The report lists the folders in this zone. |
| H002 | medium | First seen in this repo: a network host or channel | Check that the host belongs to the task. Allow it for this repo only if later runs keep needing it. |
| H003 | high | First seen in this repo: a credential-like path | Check why this run reached for a credential that earlier runs did not need. Rotate it if you cannot explain the access. |
