"""The report on one run and the summary over many: first as data, then as plain text from that data.

A report holds paths, hosts, command names, counts and the rules' texts, nothing else. The limits come first:
most calls are shell commands, and what a shell command names is a mention, not a proven touch.
"""

from __future__ import annotations

import textwrap
from collections import Counter
from dataclasses import asdict

from .model import CALL_KINDS, SCHEMA, SEVERITIES, ZONES, Finding, Record

WIDTH = 100
NOTE = "Targets of shell commands are mentions, not proven touches."
OUTSIDE = tuple(zone for zone in ZONES if zone != "repo")
ROW = "  {:<12} {:>11} {:>12} {:>14}  "  # zone, exact reads, exact writes, shell mentions
PAD = " " * 18  # under a finding's title


def _ranked(counts: Counter) -> list[list]:
    """Most frequent first, then by name, so the order never depends on the order of the input."""
    return [[name, n] for name, n in sorted(counts.items(), key=lambda item: (-item[1], item[0]))]


def _limits(calls: int, shell: int) -> dict:
    share = round(shell / calls, 2) if calls else 0.0
    return {"calls": calls, "shell_calls": shell, "shell_share": share, "note": NOTE}


def build(record: Record, findings: list[Finding], history: list[Record]) -> dict:
    """The report on one run as data. Same input, same dict."""
    meta, events = record.meta, record.events
    calls = [e for e in events if e.kind == "call"]
    kinds = Counter(e.call_kind for e in calls)
    outside = {}
    for zone in OUTSIDE:
        touches = [e for e in events if e.kind == "touch" and e.zone == zone]
        if touches:
            exact = Counter(e.mode for e in touches if e.exact)
            folders = Counter("/".join(e.target.split("/")[:3]) for e in touches if e.target)
            outside[zone] = {
                "exact": {"read": exact["read"], "write": exact["write"]},
                "mentions": sum(not e.exact for e in touches),
                "top": _ranked(folders)[:5],
            }
    net = [e for e in events if e.kind == "net" and e.target]
    return {
        "schema": SCHEMA,
        "run": {
            "harness": meta.harness,
            "session": meta.session,
            "start": meta.start,
            "started": meta.started,
            "modes": list(meta.modes),
        },
        "limits": _limits(len(calls), kinds["shell"]),
        "calls": {
            **{kind: kinds[kind] for kind in CALL_KINDS},
            "sub": sum(e.sub for e in calls),
            "refused": sum(bool(e.refused) for e in calls),
            "unsandboxed": sum(bool(e.unsandboxed) and not e.refused for e in calls),
        },
        "outside_repo": outside,
        "network": {
            "exact": _ranked(Counter(e.target for e in net if e.exact)),
            "mentions": _ranked(Counter(e.target for e in net if not e.exact)),
        },
        "findings": [{**asdict(f), "examples": list(f.examples)} for f in findings],
        "history": {"runs": len(history)},
    }


def build_summary(records: list[Record], findings: dict[str, list[Finding]]) -> dict:
    """The summary over many runs as data. `findings` is keyed by "harness/session"."""
    calls = shell = 0
    zones = {zone: Counter() for zone in OUTSIDE}
    hosts, rules, rule_runs, rule_count = Counter(), {}, Counter(), Counter()
    for record in records:
        kinds = [e.call_kind for e in record.events if e.kind == "call"]
        calls, shell = calls + len(kinds), shell + kinds.count("shell")
        touches = (e for e in record.events if e.kind == "touch" and e.zone in zones)
        for zone, how in {(e.zone, "exact" if e.exact else "mentions") for e in touches}:
            zones[zone][how] += 1
        hosts.update({e.target for e in record.events if e.kind == "net" and e.target})
        for f in findings.get(f"{record.meta.harness}/{record.meta.session}", []):
            rules[f.rule] = f
            rule_runs[f.rule] += 1
            rule_count[f.rule] += f.count

    def runs(n: int) -> dict:
        return {"runs": n, "share": round(n / len(records), 2) if records else 0.0}

    found = [
        {
            "rule": rule,
            "severity": f.severity,
            "title": f.title,
            "advice": f.advice,
            "runs": rule_runs[rule],
            "count": rule_count[rule],
        }
        for rule, f in rules.items()
    ]
    found.sort(key=lambda f: (SEVERITIES.index(f["severity"]), -f["runs"], f["rule"]))
    top = sorted(found, key=lambda f: (-f["runs"], -f["count"], f["rule"]))[:3]
    return {
        "schema": SCHEMA,
        "runs": len(records),
        "harnesses": dict(sorted(Counter(r.meta.harness for r in records).items())),
        **_limits(calls, shell),
        "zones": {z: {"exact": runs(n["exact"]), "mentions": runs(n["mentions"])} for z, n in zones.items()},
        "network": _ranked(hosts)[:10],
        "findings": found,
        "top": [f["rule"] for f in top],
    }


def _n(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _fill(text: str, first: str = "", rest: str | None = None) -> str:
    """Wrap to WIDTH. A path that is longer than a line is broken, never allowed past the edge."""
    rest = first if rest is None else rest
    return textwrap.fill(text, WIDTH, initial_indent=first, subsequent_indent=rest, break_on_hyphens=False)


def _pairs(ranked: list[list]) -> str:
    return ", ".join(f"{name} ({n})" for name, n in ranked) or "-"


def _limits_line(limits: dict) -> str:
    share = round(limits["shell_share"] * 100)
    calls = _n(limits["calls"], "tool call")
    return _fill(f"{calls}, {limits['shell_calls']} ({share}%) were shell commands. {limits['note']}")


def _finding(f: dict, count: str) -> list[str]:
    head = f"  {f['severity']:<8}  {f['rule']}  "
    lines = [_fill(f"{f['title']} ({count})", head, PAD)]
    if f.get("examples"):
        lines.append(_fill("e.g. " + ", ".join(f["examples"][:3]), PAD))
    return [*lines, _fill(f["advice"], PAD)]


def render(data: dict) -> str:
    """The report on one run as plain text for a terminal: limits first, then where, then what to do."""
    run, calls, net = data["run"], data["calls"], data["network"]
    started = f", started {run['started']}" if run["started"] else ""
    kinds = ", ".join(f"{kind} {calls[kind]}" for kind in CALL_KINDS)
    lines = [
        _fill(f"stickyagents: {run['harness']} run {run['session'][:8]} in {run['start']}{started}"),
        _limits_line(data["limits"]),
        _fill(
            f"Calls by kind: {kinds}. By subagents {calls['sub']}, refused {calls['refused']}, "
            f"outside the sandbox {calls['unsandboxed']}."
        ),
    ]
    if run["modes"]:
        lines.append(_fill("Permission modes recorded: " + ", ".join(run["modes"]) + "."))
    if data["outside_repo"]:
        lines += ["", "Outside the repo", ROW.format("zone", "exact reads", "exact writes", "shell mentions")]
        lines[-1] += "top folders"
        for zone, z in data["outside_repo"].items():
            first = ROW.format(zone, z["exact"]["read"], z["exact"]["write"], z["mentions"])
            lines.append(_fill(_pairs(z["top"]), first, " " * len(first)))
    else:
        lines += ["", "Outside the repo: no touch recorded. As far as the record shows, the run stayed in its repo."]
    if net["exact"] or net["mentions"]:
        lines += ["", "Network"]
        for key, label in (("exact", "Fetches and searches"), ("mentions", "Mentioned in shell")):
            if net[key]:
                lines.append(_fill(f"{label}: {_pairs(net[key])}", "  ", "    "))
    else:
        lines += ["", "Network: no host or channel recorded."]
    lines += ["", "Findings"] if data["findings"] else ["", "No findings."]
    for f in data["findings"]:
        lines += _finding(f, f"{f['count']}x")
    earlier = data["history"]["runs"]
    if earlier:
        lines += ["", f"Compared with {_n(earlier, 'earlier run')} in this repo."]
    else:
        lines += ["", "No earlier runs in this repo: nothing is marked as first seen."]
    return "\n".join(lines) + "\n"


def render_summary(data: dict) -> str:
    """The summary over many runs as plain text, in the same order as the report on one run."""
    harnesses = ", ".join(f"{name} {n}" for name, n in data["harnesses"].items())
    lines = [_fill(f"stickyagents: {_n(data['runs'], 'run')}" + (f" ({harnesses})" if harnesses else ""))]
    lines += [_limits_line(data), "", "Outside the repo: runs with at least one touch"]
    lines.append(f"  {'zone':<12} {'file tools (exact)':>18} {'shell mentions':>16}")
    for zone, z in data["zones"].items():
        exact, mentions = (f"{v['runs']} ({round(v['share'] * 100)}%)" for v in (z["exact"], z["mentions"]))
        lines.append(f"  {zone:<12} {exact:>18} {mentions:>16}")
    lines += ["", _fill(f"Network, by number of runs: {_pairs(data['network'])}", "", "  ")]
    if not data["findings"]:
        return "\n".join([*lines, "", "No findings."]) + "\n"
    by_rule = {f["rule"]: f for f in data["findings"]}
    lines += ["", "Findings, the most frequent first"]
    for place, rule in enumerate(data["top"], 1):
        f = by_rule[rule]
        lines.append(_fill(f"{f['title']} ({f['runs']} of {_n(data['runs'], 'run')})", f"  {place}. {rule}  ", PAD))
    lines += ["", "All findings"]
    for f in data["findings"]:
        lines += _finding(f, f"{_n(f['runs'], 'run')}, {f['count']}x")
    return "\n".join(lines) + "\n"
