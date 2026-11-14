"""Reader for opencode, version 2.

One SQLite database, `~/.local/share/opencode/opencode.db`, holds every session: a row in `session_v2` (`id`,
`parent_id`, `directory`, `agent`, `time_created`) and its messages in `session_message` (`type`, `seq`, `data`
as JSON). An assistant message's `content` lists items; one of type `tool` has `name` and `state` (`status`,
`input`, and `error` if it failed).

A subagent runs in a session of its own that names its parent: its calls go into the parent's Run, marked `sub`.
The database is opened read-only and never written. Commands the user runs with `!` are not tool calls.
Sessions of version 1 (tables `session`, `message`, `part`) are not read.
"""

from __future__ import annotations

import json
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from stickyagents.model import Run, RunMeta, ToolCall

NAME = "opencode"
STATE_DIRS = ("~/.local/share/opencode", "~/.config/opencode", "~/.local/state/opencode", "~/.cache/opencode")

# Version 2's tool names (seen in real records: shell, grep, read), then the names version 1 used.
KINDS = {
    **dict.fromkeys(("read", "grep", "glob", "list"), "read"),
    **dict.fromkeys(("write", "edit", "patch", "apply_patch", "multiedit"), "write"),
    **dict.fromkeys(("shell", "bash"), "shell"),
    "webfetch": "fetch",
    "websearch": "search",
}
PATH_KEYS = ("path", "filePath")
# A patch is one text for several files; these of its lines name them.
PATCH_FILE = re.compile(r"^\*\*\* (?:Add File|Update File|Delete File|Move to): (.+?)\s*$", re.MULTILINE)
# How a call that a permission rule or the user turned down shows: the error's type, or version 1's sentences.
REFUSED_TYPE = "permission.rejected"
REFUSED_TEXT = ("The user rejected permission", "The user has specified a rule which prevents you")
SESSIONS = "SELECT id, parent_id, directory, agent, time_created FROM session_v2 ORDER BY time_created, id"
MESSAGES = (
    "SELECT session_id, time_created, data FROM session_message WHERE type = 'assistant' ORDER BY time_created, seq"
)


def find(home: Path) -> list[Path]:
    """The database under this home folder, if there is one: one source for all sessions."""
    db = home / ".local" / "share" / "opencode" / "opencode.db"
    return [db] if db.is_file() else []


def read(path: Path, home: Path) -> list[Run]:
    """One Run per session in the database; [] if it isn't opencode's. Never raises on bad input."""
    try:
        with closing(sqlite3.connect(f"{path.absolute().as_uri()}?mode=ro", uri=True)) as db:
            db.execute("PRAGMA query_only = 1")
            db.text_factory = lambda raw: raw.decode("utf-8", "replace")  # one bad row must not end the read
            return _runs(db, str(path))
    except (sqlite3.Error, OSError, ValueError):
        return []


def _runs(db: sqlite3.Connection, source: str) -> list[Run]:
    sessions = {row[0]: row for row in db.execute(SESSIONS).fetchall() if isinstance(row[0], str) and row[0]}
    runs: dict[str, Run] = {}
    for sid, parent, directory, agent, created in sessions.values():
        if parent not in sessions:  # a session of its own; one with a parent is a subagent's
            modes = (agent,) if _text(agent) else ()
            meta = RunMeta(NAME, re.sub(r"[^A-Za-z0-9_-]", "_", sid), _text(directory), _iso(created), source)
            meta.modes, meta.state_dirs = modes, STATE_DIRS
            runs[sid] = Run(meta)
    for sid, created, data in db.execute(MESSAGES).fetchall():
        root, message = _root(sid, sessions), _json(data)
        if root not in runs:
            continue
        meta, agent = runs[root].meta, _text(message.get("agent"))
        if agent and root == sid and agent not in meta.modes:
            meta.modes += (agent,)  # the agent ("build", "plan") is what carries the permissions
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for item in (i for i in content if isinstance(i, dict) and i.get("type") == "tool"):
            call = _call(item, _iso(created), sub=root != sid)
            if call:
                runs[root].calls.append(call)
    return list(runs.values())


def _root(sid: object, sessions: dict) -> object:
    """The session a subagent's session belongs to: up the parents, as far as they are known."""
    seen = set()
    while sid in sessions and sessions[sid][1] in sessions and sid not in seen:
        seen.add(sid)
        sid = sessions[sid][1]
    return sid


def _call(item: dict, time: str | None, sub: bool) -> ToolCall | None:
    """One tool item as a ToolCall; None while its input was still being written (it never ran)."""
    state = item.get("state") if isinstance(item.get("state"), dict) else {}
    tool, args = _text(item.get("name")), state.get("input")
    if not tool or not isinstance(args, dict):
        return None
    own = item.get("time") if isinstance(item.get("time"), dict) else {}
    error = state.get("error") if isinstance(state.get("error"), dict) else {}
    call = ToolCall(tool=tool, kind=KINDS.get(tool, "other"), time=_iso(own.get("created")) or time, sub=sub)
    call.refused = state.get("status") == "error" and (
        error.get("type") == REFUSED_TYPE or _text(error.get("message")).startswith(REFUSED_TEXT)
    )
    if call.kind in ("read", "write"):
        call.paths = tuple(args[key] for key in PATH_KEYS if _text(args.get(key)))
        if not call.paths and call.kind == "write":
            call.paths = tuple(PATCH_FILE.findall(_text(args.get("patchText"))))
    elif call.kind == "shell":
        call.command = _text(args.get("command")) or None
    elif call.kind == "fetch":
        call.url = _text(args.get("url")) or None
    return call


def _json(text: object) -> dict:
    """A JSON column as a dict; {} if it is broken or something else."""
    try:
        value = json.loads(text)  # type: ignore[arg-type]
    except (ValueError, TypeError, RecursionError):
        return {}
    return value if isinstance(value, dict) else {}


def _iso(ms: object) -> str | None:
    """Milliseconds since 1970, as opencode stores times, in ISO 8601 (UTC)."""
    if isinstance(ms, bool) or not isinstance(ms, (int, float)):
        return None
    try:
        stamp = datetime.fromtimestamp(ms / 1000, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value: object) -> str:
    """The value if it is a string, else "". Records are outside input: no field is trusted to have its type."""
    return value if isinstance(value, str) else ""
