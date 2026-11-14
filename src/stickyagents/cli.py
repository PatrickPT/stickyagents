"""The command line: scan the harnesses found, store what runs touched, report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, normalise, readers, report, rules, store, zones
from .model import Record

NOTES = {"no_session": "without a readable session", "unreadable": "could not be read"}


def _stamp(source: Path) -> list[int]:
    """A source's mtime and size, and its write-ahead log's; a read-only open touches only `-shm`, so not that."""
    own, wal = source.stat(), source.with_name(source.name + "-wal")
    return [own.st_mtime_ns, own.st_size, *([wal.stat().st_mtime_ns, wal.stat().st_size] if wal.exists() else [])]


def scan(home: Path) -> dict[str, int]:
    """Read every session source that changed since the last scan and store its runs. Returns counts."""
    seen_file = store.base() / "sources.json"
    try:
        seen = json.loads(seen_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    counts = {"sources": 0, "unchanged": 0, "no_session": 0, "unreadable": 0, "runs": 0}
    for reader in readers.load():
        for source in reader.find(home):
            counts["sources"] += 1
            key = f"{reader.NAME}:{zones.tilde(str(source), str(home))}"
            try:
                stamp = _stamp(source)
                if seen.get(key) == stamp:
                    counts["unchanged"] += 1
                    continue
                runs = [run for run in reader.read(source, home) if run.calls]
                for run in runs:
                    run.meta.siblings = zones.find_siblings(run.meta.start)
                    store.save(normalise.normalise(run, str(home)))
                after = _stamp(source)  # reading a database can create its log; that is no change of the source
                seen[key] = after if after[:2] == stamp[:2] else stamp
            except Exception:  # noqa: BLE001 - one bad source must not stop the scan; it is counted and reported
                counts["unreadable"] += 1
                continue
            counts["runs"] += len(runs)
            counts["no_session"] += not runs
    store.private_dir(store.base())
    store.write_private(seen_file, json.dumps(seen, sort_keys=True))
    return counts


def same_repo(a: Record, b: Record) -> bool:
    one, other = a.meta.start, b.meta.start  # a run without a start folder belongs to no repo
    return bool(one and other) and (one == other or one in b.meta.siblings or other in a.meta.siblings)


def history(record: Record, records: list[Record]) -> list[Record]:
    """Earlier runs of the same repo: what "first seen" is measured against."""
    started = record.meta.started or ""
    return [r for r in records if r is not record and same_repo(r, record) and (r.meta.started or "") < started]


def pick(records: list[Record], session: str | None, folder: str) -> Record | None:
    """The run asked for: by session id, else the newest that started in or above this folder."""
    if session:
        matches = [r for r in records if r.meta.session.startswith(session)]
    else:
        under = (r for r in records if r.meta.start)
        matches = [r for r in under if folder == r.meta.start or folder.startswith(r.meta.start.rstrip("/") + "/")]
    return matches[-1] if matches else None


def _print(data: dict, text: str, as_json: bool) -> None:
    print(json.dumps(data, indent=2, sort_keys=True) if as_json else text.rstrip("\n"))


def main(argv: list[str] | None = None, home: Path | None = None, folder: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="stickyagents", description="See what your agents got their fingers on.")
    parser.add_argument("--version", action="version", version=f"stickyagents {__version__}")
    commands = parser.add_subparsers(dest="command")
    one = commands.add_parser("report", help="what one run touched (default: the newest run of this folder)")
    one.add_argument("--session", help="a session id, or its first characters")
    one.add_argument("--json", action="store_true", help="the report as data")
    many = commands.add_parser("summary", help="all recorded runs (the default command)")
    many.add_argument("--json", action="store_true", help="the summary as data")
    commands.add_parser("harnesses", help="the harnesses this version reads, and how many session sources each has")
    args = parser.parse_args(argv)
    home = home or Path.home()

    if args.command == "harnesses":
        for reader in readers.load():
            print(f"{reader.NAME}: {len(reader.find(home))} session sources")
        return 0

    counts = scan(home)
    parts = [f"{counts['unchanged']} unchanged", *(f"{counts[k]} {text}" for k, text in NOTES.items() if counts[k])]
    print(
        f"Scanned {counts['sources']} session sources ({', '.join(parts)}); {counts['runs']} runs recorded.",
        file=sys.stderr,
    )
    records = store.load_all()

    if args.command == "report":
        where = zones.tilde(str(folder or Path.cwd()), str(home))
        record = pick(records, args.session, where)
        if record is None:
            wanted = f"session {args.session}" if args.session else f"a run that started in or above {where}"
            print(f"No record of {wanted}. Run `stickyagents summary` to see what is recorded.", file=sys.stderr)
            return 1
        earlier = history(record, records)
        data = report.build(record, rules.evaluate(record, earlier), earlier)
        _print(data, report.render(data), args.json)
        return 0

    if not records:
        print("No sessions found. Run `stickyagents harnesses` to see where it looks.", file=sys.stderr)
        return 1
    findings = {f"{r.meta.harness}/{r.meta.session}": rules.evaluate(r, history(r, records)) for r in records}
    data = report.build_summary(records, findings)
    _print(data, report.render_summary(data), getattr(args, "json", False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
