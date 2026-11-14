"""Stored records: one JSON-lines file per run. The first line is the meta, then one event per line.

They are kept apart from the harness's own records so that history survives when a harness deletes old sessions.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import asdict
from pathlib import Path

from .model import SCHEMA, Event, Record, RunMeta


def base() -> Path:
    """Where records live: $STICKYAGENTS_HOME, else the XDG state folder."""
    explicit = os.environ.get("STICKYAGENTS_HOME")
    if explicit:
        return Path(explicit)
    state = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(state) / "stickyagents"


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120] or "unknown"


def path_for(harness: str, session: str) -> Path:
    return base() / "runs" / _safe(harness) / f"{_safe(session)}.jsonl"


def private_dir(path: Path) -> None:
    """Create `path` and the folders from base() down to it, each mode 700 even if it existed."""
    base().mkdir(parents=True, exist_ok=True)
    for folder in (base(), *reversed([p for p in path.parents if base() in p.parents]), path):
        folder.mkdir(exist_ok=True)
        folder.chmod(0o700)


def write_private(target: Path, text: str) -> None:
    """Write `target` mode 600 in one step: a temp file beside it, then a replace. No temp file is left behind."""
    handle, temp = tempfile.mkstemp(dir=target.parent, prefix=".tmp-")  # mkstemp gives mode 600
    os.close(handle)
    try:
        Path(temp).write_text(text, encoding="utf-8")  # the file exists, so its mode stays
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise


def save(record: Record) -> Path:
    """Write a run's record in one step, replacing an earlier one of the same harness and session."""
    target = path_for(record.meta.harness, record.meta.session)
    private_dir(target.parent)
    lines = [json.dumps({"schema": SCHEMA, **asdict(record.meta)}, sort_keys=True)]
    lines += [json.dumps(event.to_json(), sort_keys=True) for event in record.events]
    write_private(target, "\n".join(lines) + "\n")
    return target


def load(path: Path) -> Record | None:
    """One stored record, or None if the file is broken or of another schema."""
    try:
        with open(path, encoding="utf-8") as lines:
            head = json.loads(lines.readline())
            if head.pop("schema", None) != SCHEMA:
                return None
            fields = RunMeta.__dataclass_fields__
            meta = RunMeta(**{k: tuple(v) if isinstance(v, list) else v for k, v in head.items() if k in fields})
            events = [Event.from_json(json.loads(line)) for line in lines if line.strip()]
    except (OSError, ValueError, TypeError, AttributeError):  # AttributeError: a line that is no object
        return None
    return Record(meta, events)


def load_all() -> list[Record]:
    """Every stored record, oldest first."""
    records = [record for path in sorted((base() / "runs").glob("*/*.jsonl")) if (record := load(path))]
    return sorted(records, key=lambda r: (r.meta.started or "", r.meta.harness, r.meta.session))
