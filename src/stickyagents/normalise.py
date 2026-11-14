"""From a reader's tool calls to the events that are stored.

This is where command text and URLs end: only command names, paths, hosts and flags go on.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime, timedelta

from . import shell
from .model import Event, Record, Run, ToolCall
from .zones import classify, tilde

_SAFE = re.compile(r"[A-Za-z0-9_.:-]{1,64}")  # a tool name or mode may be model-written text: keep only names
_TIME = re.compile(r"(\d{4}-\d\d-\d\d)[T ](\d\d:\d\d:\d\d)(?:[.,](\d+))?(?:Z|([+-])(\d\d)(?::?(\d\d))?)?", re.I)


def _utc(text: str | None) -> str | None:
    """An ISO 8601 time as UTC with milliseconds and a Z (a time without a zone counts as UTC); None if unreadable."""
    match = _TIME.fullmatch(text.strip()) if isinstance(text, str) else None
    if not match:
        return None
    day, clock, fraction, sign, hours, minutes = match.groups()
    try:
        moment = datetime.fromisoformat(f"{day}T{clock}") - (-1 if sign == "-" else 1) * timedelta(
            hours=int(hours or 0), minutes=int(minutes or 0)
        )
    except (ValueError, OverflowError):  # OverflowError: a time at the edge of the calendar
        return None
    return f"{moment:%Y-%m-%dT%H:%M:%S}.{(fraction or '0').ljust(3, '0')[:3]}Z"


def _cut(shown: str, exact: bool) -> str:
    """A mention keeps four path segments (~/a/b/c, /a/b/c/d): shell text is free text, so the rest is dropped."""
    return shown if exact else "/".join(shown.split("/")[: 4 if shown.startswith("~") else 5])


def _events(call: ToolCall, run: Run, home: str) -> list[Event]:
    tool = call.tool if _SAFE.fullmatch(call.tool) else "other"
    common = {"tool": tool, "time": _utc(call.time), "sub": call.sub}
    events = [Event("call", **common, call_kind=call.kind, unsandboxed=call.unsandboxed, refused=call.refused)]
    if call.refused:
        return events

    def touches(paths: tuple[str, ...], mode: str, exact: bool) -> list[Event]:
        places = filter(None, (classify(path, run.meta, home) for path in paths))
        return [Event("touch", **common, exact=exact, mode=mode, zone=z, target=_cut(s, exact)) for z, s in places]

    if call.kind in ("read", "write"):
        events += touches(call.paths, call.kind, True)
    elif call.kind == "shell" and call.command:
        facts = shell.parse(call.command)  # everything from shell text is a mention, never exact
        events += [Event("cmd", **common, exact=False, target=name) for name in facts.commands]
        events += touches(facts.paths, "mention", False)
        events += [Event("net", **common, exact=False, target=host) for host in facts.hosts]
        events += [Event("flag", **common, exact=False, target=flag) for flag in facts.flags]
    elif call.kind == "fetch":
        host = shell.url_host(call.url or "")
        events += [Event("net", **common, target=host)] if host else []
    elif call.kind == "search":
        events.append(Event("net", **common, target="web search"))
    return events


def normalise(run: Run, home: str) -> Record:
    """The record of a run: one `call` event per tool call, then what the call touched, used or named.

    The meta is a copy with the home folder shown as ~. Same run, same record.
    """
    meta = replace(
        run.meta,
        started=_utc(run.meta.started),
        modes=tuple(mode for mode in run.meta.modes if _SAFE.fullmatch(mode)),
        start=tilde(run.meta.start, home),
        source=tilde(run.meta.source, home),
        siblings=tuple(tilde(folder, home) for folder in run.meta.siblings),
    )
    return Record(meta, [event for call in run.calls for event in _events(call, run, home)])
