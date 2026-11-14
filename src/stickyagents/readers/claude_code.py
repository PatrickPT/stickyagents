"""Reader for Claude Code.

A session is one JSON-lines file, `~/.claude/projects/<folder>/<session>.jsonl`. Its subagents write their own
files under `<session>/subagents/agent-*.jsonl`; older versions put their lines into the session file with
`isSidechain` true. Both end up in the session's Run, marked `sub`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path

from stickyagents.model import Run, RunMeta, ToolCall

NAME = "claude-code"
STATE_DIRS = ("~/.claude",)

KINDS = {
    **dict.fromkeys(("Read", "Grep", "Glob", "NotebookRead", "LS"), "read"),
    **dict.fromkeys(("Edit", "Write", "MultiEdit", "NotebookEdit"), "write"),
    **dict.fromkeys(("Bash", "PowerShell", "Monitor"), "shell"),
    "WebFetch": "fetch",
    "WebSearch": "search",
}
PATH_KEYS = ("file_path", "path", "notebook_path")
# How the harness words a call the user turned down. Records from before `toolDenialKind` show nothing else.
USER_REFUSED = "The user doesn't want to proceed with this tool use"


def find(home: Path) -> list[Path]:
    """Every session record under this home folder. Subagent files are read with their session, not alone."""
    files = (home / ".claude" / "projects").glob("*/*.jsonl")
    return sorted(p for p in files if p.is_file() and not p.name.startswith("agent-"))


def read(path: Path, home: Path) -> list[Run]:
    """The session in this file as one Run; [] if it holds no conversation. Never raises on bad input."""
    meta = RunMeta(NAME, re.sub(r"[^A-Za-z0-9_-]", "_", path.stem), start="", source=str(path), state_dirs=STATE_DIRS)
    calls: list[ToolCall] = []
    modes: list[str] = []
    conversation = False
    subagents = sorted(path.with_suffix("").glob("subagents/**/agent-*.jsonl"))
    for file, sub in [(path, False), *((p, True) for p in subagents)]:
        by_id: dict[str, ToolCall] = {}
        for rec in _records(file):
            time = _text(rec.get("timestamp")) or None
            meta.started = meta.started or time
            meta.start = meta.start or _text(rec.get("cwd"))
            mode = _text(rec.get("permissionMode"))
            if mode and mode not in modes:
                modes.append(mode)
            # Other line types (such as api-request-blob) repeat messages; only these two are the conversation.
            if rec.get("type") == "assistant":
                conversation = True
                for item in _items(rec, "tool_use"):
                    key = item.get("id") if isinstance(item.get("id"), str) else None
                    if key in by_id:
                        continue
                    calls.append(_call(item, time, sub or rec.get("isSidechain") is True))
                    if key:
                        by_id[key] = calls[-1]
            elif rec.get("type") == "user":
                conversation = True
                decision = rec.get("permissionDecision")
                denied = "toolDenialKind" in rec or (
                    isinstance(decision, dict) and decision.get("decision") == "reject"
                )
                for item in _items(rec, "tool_result"):
                    call = by_id.get(item.get("tool_use_id")) if isinstance(item.get("tool_use_id"), str) else None
                    if call and (denied or (item.get("is_error") is True and _refusal_text(item.get("content")))):
                        call.refused = True
    if not conversation:
        return []
    meta.modes = tuple(modes)
    calls.sort(key=lambda call: call.time or "")  # stable: subagent calls fall in between the session's own
    return [Run(meta, calls)]


def _call(item: dict, time: str | None, sub: bool) -> ToolCall:
    """One `tool_use` item as a ToolCall. Only the fields its kind needs are taken from the input."""
    tool = _text(item.get("name"))
    args = item.get("input") if isinstance(item.get("input"), dict) else {}
    call = ToolCall(tool=tool, kind=KINDS.get(tool, "other"), time=time, sub=sub)
    if call.kind in ("read", "write"):
        call.paths = tuple(args[key] for key in PATH_KEYS if _text(args.get(key)))
    elif call.kind == "shell":
        call.command = _text(args.get("command")) or None
        call.unsandboxed = args.get("dangerouslyDisableSandbox") is True
    elif call.kind == "fetch":
        call.url = _text(args.get("url")) or None
    return call


def _records(path: Path) -> Iterator[dict]:
    """The JSON objects of a file, one per line. Broken lines are skipped; an unreadable file gives none."""
    try:
        with path.open(encoding="utf-8", errors="replace") as lines:
            for line in lines:
                try:
                    rec = json.loads(line)
                except (ValueError, RecursionError):
                    continue
                if isinstance(rec, dict):
                    yield rec
    except OSError:
        return


def _items(rec: dict, kind: str) -> list[dict]:
    """The content items of one type in a line's message."""
    message = rec.get("message")
    content = message.get("content") if isinstance(message, dict) else None
    return [i for i in content if isinstance(i, dict) and i.get("type") == kind] if isinstance(content, list) else []


def _refusal_text(content: object) -> bool:
    """Whether a tool result (a string or a list of text items) starts with the harness's refusal sentence."""
    if isinstance(content, list):
        content = next((i.get("text") for i in content if isinstance(i, dict) and i.get("type") == "text"), "")
    return _text(content).startswith(USER_REFUSED)


def _text(value: object) -> str:
    """The value if it is a string, else "". Records are outside input: no field is trusted to have its type."""
    return value if isinstance(value, str) else ""
