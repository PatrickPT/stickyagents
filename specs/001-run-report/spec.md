# Feature Specification: See what agent runs touch (recorder and reporter, smallest version)

**Feature Branch**: `spec/001-run-report`

**Created**: 2026-11-13

**Status**: Accepted

**Input**: Before anyone can put a fence around agent runs, they need to know what runs do. A first measurement over real sessions showed that most tool calls are shell commands and that nearly every session touches something outside its repository.

## Summary

One command reads the session records the harness already keeps and says what each run touched: how often it left
its repo and where to, which hosts it used, which credential-like paths appeared, and what was refused. It stores a
small normalised record per run, so later runs can be compared with earlier ones. Fixed rules turn findings into
risks and recommendations.

There is no fence in this version and nothing is blocked. The report is the evidence a fence will later be built
from. No model takes part in recording or judging.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Report on one run (Priority: P1)

After a session, the user asks "what did this run touch?" and gets a short report.

**Why this priority**: It is the whole point: sight before rules.

**Independent Test**: Run a session that reads a file in another folder of the home folder and writes one scratch
file. The report counts one read under "home", with that folder named, and one write under "scratch".

**Acceptance Scenarios**:

1. **Given** a finished or running session, **When** the user asks for its report, **Then** it shows: tool calls
   and the share that are shell commands; touches outside the repo, counted per zone (sibling worktrees, scratch,
   the agent's own state, home, system, credential-like), with the most-touched folders of each zone; network channels; refusals; commands run outside the sandbox.
2. **Given** a touch made with a file tool, **When** it is reported, **Then** it counts as exact. **Given** a path or
   host that only appears in a shell command's text, **Then** it is reported apart, labelled "mentioned in shell".
3. **Given** any report, **When** it is read, **Then** it contains paths, hosts and command names only: no file
   content, no command text, no values. The home folder is shown as `~`.
4. **Given** the same session, **When** the report runs twice, **Then** the output is identical.

---

### User Story 2 - First report with nothing to set up (Priority: P1)

A new user runs one command and gets a report over the sessions already on their machine.

**Why this priority**: "Really easy" decides whether anyone tries it. Reading existing records needs no install into
the harness and gives a result in the first minute.

**Independent Test**: On a machine with past sessions and a fresh clone of the tool, one command prints a summary
over all sessions and writes one stored record per session.

**Acceptance Scenarios**:

1. **Given** past sessions, **When** the command runs, **Then** it prints a summary across them and names the three
   most frequent findings.
2. **Given** a session record it can't parse, **When** the command runs, **Then** it skips that session, says so,
   and continues.

---

### User Story 3 - Risks and recommendations (Priority: P2)

Each finding carries a severity and one piece of advice, from a fixed table.

**Why this priority**: A count tells what happened; the user also wants to know what to do about it.

**Independent Test**: A session whose shell text names a private SSH key yields the finding "A credential-like path
was named in a shell command" with the advice from the table; removing that command from the input removes the finding.

**Acceptance Scenarios**:

1. **Given** a finding, **When** it is reported, **Then** it shows its rule's id, severity and advice.
2. **Given** a new rule, **When** it is added, **Then** it is one table entry and one test.

---

### User Story 4 - Compare with earlier runs (Priority: P2)

The report marks what is new: "first run in this repo that wrote to the home folder".

**Why this priority**: Leaving the repo is normal; what matters is leaving it in a new way. History gives that
without asking a model to predict anything.

**Independent Test**: With ten stored runs that never used host X, an eleventh that does is reported with
"first seen: host X".

**Acceptance Scenarios**:

1. **Given** stored records for a repo, **When** a run is reported, **Then** zones, hosts and credential-like paths
   not seen in earlier runs of that repo are marked as first seen.
2. **Given** no earlier runs, **When** a run is reported, **Then** nothing is marked and the report says the history
   is empty.

---

### User Story 5 - Other agents can read it (Priority: P3)

A reviewing agent or a pipeline reads the same result as data.

**Why this priority**: Wanted for automated review of agent runs; needs nothing beyond a stable file.

**Independent Test**: The stored record and the report's data form validate against the documented shape.

**Acceptance Scenarios**:

1. **Given** a run, **When** a tool asks for its report as data, **Then** it gets the same content as the text
   report, in a documented shape with a version number.

---

### Edge Cases

- A session works in a worktree or changes folder midway: the repo is where the session started; other worktrees of
  the same repo count as their own zone, not as "home".
- Subagents: their calls belong to the run and are marked as such.
- The harness has deleted old session records: stored records keep the history.
- A shell command hides its target (a script, a variable): nothing is reported for it. The report states this limit
  on its first lines, with the share of calls that were shell commands.
- A secret typed inline in a command: never stored, because command text isn't stored.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The tool MUST read the harness's own session records and need no change to the harness.
- **FR-011**: Each harness MUST be supported by one reader that turns its records into the same neutral form.
  Zones, rules and reports MUST NOT depend on the harness. This version ships readers for Claude Code, Pi and
  opencode, each checked against real session records.
- **FR-002**: It MUST write one normalised record per run to a folder in the user's home, outside every repo: one
  line per event, with its kind (call, touch, net, cmd or flag), time and tool, and by kind the call kind, zone,
  mode and path, or the host, command name or flag.
- **FR-003**: It MUST NOT store or print file content, command text or any value; command names, paths and hosts
  only. From shell text it takes a path only when the path is a whole word of the command, never from option
  values, quoted text or patterns, and keeps at most its first four segments.
- **FR-004**: It MUST keep exact touches (file tools) and shell mentions apart in records and reports.
- **FR-005**: Zones MUST be decided by fixed rules from the path and the session's start folder.
- **FR-006**: Risks and advice MUST come from a table of rules, each with id, severity and advice.
- **FR-007**: It MUST report commands that ran outside the harness's sandbox and sessions that ran without
  permission prompts, where the session record shows it.
- **FR-008**: The report MUST come as text and as data with the same content, and state its limits first.
- **FR-009**: It MUST send nothing anywhere: no network use at all.
- **FR-010**: A skill MUST let the user ask for the report from inside a session; the same command MUST work from
  a plain shell.

### Key Entities

- **Run**: one session, with its start folder, harness and time.
- **Event**: one touch, mention or refusal inside a run.
- **Zone**: in-repo, sibling worktree, scratch, agent state, home, system, credential-like. Decided from the path
  alone, so that the same record gives the same report on any day. There is no "other repo" zone, because telling a
  repo from a folder needs a look at the file system; the report names the folders touched under "home" instead.
- **Rule**: a condition over events with severity and advice.
- **Finding**: a rule that matched in a run, with its count.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a fresh clone to the first report over past sessions takes under 2 minutes and one command.
- **SC-002**: Over a large set of past sessions on one machine the tool runs to the end in under a minute and skips none without
  saying so.
- **SC-003**: On 10 sessions checked by hand, every file-tool touch outside the repo appears in the report, and none
  is invented.
- **SC-004**: A test plants a marker value in a command and in a file that a session reads; the marker appears in no
  record and no report.
- **SC-005**: After two weeks of use the user can write the first fence for one repo from the reports alone: the
  zones and hosts normal runs need, and the ones they don't.
- **SC-006**: The tool stays under 1,600 lines without tests, standard library only, and a reader for a new
  harness is one module of under 150 lines plus one fixture test.

## Assumptions

- **Session records as the source.** They hold every tool call, but their formats are not documented interfaces
  and may change. Each reader is one small module, so it can be replaced, later also by a harness's hooks.
- **Three harnesses in this version**: Claude Code, Pi and opencode, because real records of them were at hand to
  check against. Codex and others follow as contributed readers.
- **Shell stays rough in this version.** Exact shell touches need something below the shell (the sandbox or the
  operating system). That arrives with the fence, which reports what it refuses.
- **Out of this version**: the fence itself, blocking, hooks, prediction by a model, further harnesses, a server or
  MCP interface, a picture of the result.
