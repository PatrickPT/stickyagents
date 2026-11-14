"""Reader for Pi (the pi-mono coding agent).

A session is one JSON-lines file, `~/.pi/agent/sessions/--<folder>--/<time>_<id>.jsonl`. Its first line is the
header (`type: session`, with `id`, `timestamp`, `cwd`); a later line of type `message` whose message has the role
`assistant` holds content items, among them `{"type": "toolCall", "name", "arguments"}`.

Pi asks for no permission and has no sandbox or subagents of its own, so the record shows no modes, refusals,
unsandboxed commands or subagent calls. Commands the user runs with `!` are not tool calls and are left out.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from stickyagents.model import Run, RunMeta, ToolCall

NAME = "pi"
STATE_DIRS = ("~/.pi",)

# Pi's built-in tools. Any other tool is unknown here: kind "other", with no paths and no command.
KINDS = {
    **dict.fromkeys(("read", "grep", "find", "ls"), "read"),
    **dict.fromkeys(("write", "edit"), "write"),
    "bash": "shell",
}


def find(home: Path) -> list[Path]:
    """Every session file under this home folder."""
    return sorted(p for p in (home / ".pi" / "agent" / "sessions").rglob("*.jsonl") if p.is_file())


def read(path: Path, home: Path) -> list[Run]:
    """The session in this file as one Run; [] if it doesn't start with a session header. Never raises on bad input."""
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    meta: RunMeta | None = None
    calls: list[ToolCall] = []
    for line in lines:
        try:
            entry = json.loads(line)
        except (ValueError, RecursionError):
            continue
        if not isinstance(entry, dict):
            continue
        if meta is None:  # the first line that parses must be the header
            if entry.get("type") != "session" or not _text(entry.get("id")):
                return []
            session = re.sub(r"[^A-Za-z0-9_-]", "_", entry["id"])
            started = _iso(entry.get("timestamp"))
            meta = RunMeta(NAME, session, _text(entry.get("cwd")), started, source=str(path), state_dirs=STATE_DIRS)
            continue
        message = entry.get("message") if entry.get("type") == "message" else None
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        time = _iso(entry.get("timestamp")) or _iso(message.get("timestamp"))
        content = message.get("content") if isinstance(message.get("content"), list) else []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "toolCall":
                calls.append(_call(_text(item.get("name")), item.get("arguments"), time))
    return [Run(meta, calls)] if meta else []


def _call(tool: str, args: object, time: str | None) -> ToolCall:
    """A ToolCall with the fields its kind needs. An unknown tool keeps neither a path nor a command."""
    args = args if isinstance(args, dict) else {}
    call = ToolCall(tool=tool, kind=KINDS.get(tool, "other"), time=time)
    if call.kind in ("read", "write") and _text(args.get("path")):
        call.paths = (args["path"],)
    elif call.kind == "shell" and _text(args.get("command")):
        call.command = args["command"]
    return call


def _iso(value: object) -> str | None:
    """A time as ISO 8601: text as recorded, a number (milliseconds, or seconds if small) converted to UTC."""
    if isinstance(value, str):
        return value or None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        stamp = datetime.fromtimestamp(value / 1000 if value > 1e11 else value, tz=timezone.utc)
    except (ValueError, OverflowError, OSError):
        return None
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _text(value: object) -> str:
    """The value if it is a string, else "". Records are outside input: no field is trusted to have its type."""
    return value if isinstance(value, str) else ""
