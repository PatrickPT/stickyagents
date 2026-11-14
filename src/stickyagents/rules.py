"""The rules: a fixed table that turns a run's events into findings, each with a severity and one piece of advice.

A rule only looks at events and at earlier runs of the same repo. No model takes part, so the same record
always gives the same findings.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .model import SEVERITIES, Event, Finding, Record

# Permission modes that mean "no prompts", in the harnesses' own words.
NO_PROMPT_MODES = ("bypassPermissions", "yolo", "full-auto", "danger-full-access")

# Files that run code or grant access at every login, and folders whose content does.
STARTUP_FILES = (
    "~/.bashrc ~/.bash_profile ~/.bash_login ~/.profile ~/.zshrc ~/.zprofile ~/.zshenv ~/.config/fish/config.fish "
    "~/.ssh/authorized_keys ~/.ssh/config ~/.gitconfig /etc/profile"
).split()
STARTUP_DIRS = ("~/.config/systemd", "~/.config/autostart", "/etc/systemd", "/etc/profile.d")
STARTUP_PREFIXES = ("/etc/cron",)  # /etc/crontab, /etc/cron.d, /etc/cron.daily, ...

SETTINGS_FILES = "settings.json settings.local.json config.json config.toml config.yaml hooks.json".split()

Match = Callable[[Record, list[Record]], list[str]]


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str  # one of SEVERITIES
    title: str
    advice: str
    match: Match  # the matching targets, one entry per occurrence


def _startup(event: Event) -> bool:
    target = event.target or ""
    under = any(target == d or target.startswith(d + "/") for d in STARTUP_DIRS)
    return target in STARTUP_FILES or under or target.startswith(STARTUP_PREFIXES)


def _harness_settings(event: Event) -> bool:
    """A file of the harness's own settings, which change what later runs may do, or one under a hooks folder."""
    parts = (event.target or "").split("/")
    return parts[-1] in SETTINGS_FILES or "hooks" in parts[:-1]


def _touch(test: Callable[[Event], bool]) -> Match:
    return lambda record, _history: [e.target for e in record.events if e.kind == "touch" and e.target and test(e)]


def _flag(name: str) -> Match:
    return lambda record, _history: [name for e in record.events if e.kind == "flag" and e.target == name]


def _unsandboxed(record: Record, _history: list[Record]) -> list[str]:
    """A refused call did not run, so it is no finding."""
    return [e.tool for e in record.events if e.kind == "call" and e.unsandboxed and not e.refused]


def _no_prompts(record: Record, _history: list[Record]) -> list[str]:
    return [mode for mode in record.meta.modes if mode in NO_PROMPT_MODES]


def _first_seen(key: Callable[[Event], str | None]) -> Match:
    """What `key` gives for this run's events and for no event of an earlier run. Nothing without history."""

    def match(record: Record, history: list[Record]) -> list[str]:
        if not history:
            return []
        seen = {key(e) for earlier in history for e in earlier.events}
        return [k for e in record.events if (k := key(e)) is not None and k not in seen]

    return match


RULES: tuple[Rule, ...] = (
    Rule(
        "C001",
        "critical",
        "A credential-like path was read or written with a file tool",
        "Check what the file holds. If it is a live credential, rotate it and keep such files away from agent runs.",
        _touch(lambda e: e.exact and e.zone == "credential"),
    ),
    Rule(
        "C002",
        "high",
        "A credential-like path was named in a shell command",
        "Check whether the agent needs this credential. If it does, give it one that is scoped to this repo and "
        "short-lived, instead of your personal one.",
        _touch(lambda e: not e.exact and e.zone == "credential"),
    ),
    Rule(
        "W001",
        "high",
        "A file tool wrote outside the repo",
        "Check that each write was intended. A run should write inside its repo and scratch folders only; "
        "make other changes yourself.",
        _touch(lambda e: e.exact and e.mode == "write" and e.zone in ("home", "system")),
    ),
    Rule(
        "W002",
        "critical",
        "A startup or key file was written with a file tool",
        "Review the file and undo any change you did not ask for. These files run code or grant access at "
        "every login, so keep them out of the agent's reach.",
        _touch(lambda e: e.exact and e.mode == "write" and _startup(e)),
    ),
    Rule(
        "W003",
        "high",
        "A startup or key file was named in a shell command",
        "Check whether the command changed the file: naming it is not proof of a write. If it did, review the change.",
        _touch(lambda e: not e.exact and _startup(e)),
    ),
    Rule(
        "W004",
        "high",
        "A file tool changed the harness's own settings",
        "Review the change and undo it if you did not ask for it. Settings and hooks decide what later runs may "
        "do, so keep them out of the agent's reach.",
        _touch(lambda e: e.exact and e.mode == "write" and e.zone == "agent-state" and _harness_settings(e)),
    ),
    Rule(
        "S001",
        "high",
        "A shell command ran outside the harness's sandbox",
        "Check which commands needed this. Allow those by name and keep everything else inside the sandbox.",
        _unsandboxed,
    ),
    Rule(
        "S002",
        "medium",
        "The session ran without permission prompts",
        "Run without prompts only inside a sandbox or on a machine you can throw away. Elsewhere, keep the "
        "prompts and allow routine commands by name.",
        _no_prompts,
    ),
    Rule(
        "S003",
        "high",
        "A shell command used sudo",
        "Do not give agent runs root. Run the privileged step yourself, from a script you have read.",
        _flag("sudo"),
    ),
    Rule(
        "S004",
        "high",
        "A download was piped into a shell",
        "Download the script to a file and read it before running it. Pin a version or checksum if the step repeats.",
        _flag("pipe-to-shell"),
    ),
    Rule(
        "G001",
        "medium",
        "A force push was named in a shell command",
        "Check the remote branch for lost commits. Protect shared branches against force pushes on the server.",
        _flag("force-push"),
    ),
    Rule(
        "G002",
        "medium",
        "A push to main was named in a shell command",
        "Check what reached main. Protect the branch, so that changes arrive through pull requests only.",
        _flag("push-main"),
    ),
    Rule(
        "H001",
        "medium",
        "First seen in this repo: a zone outside the repo",
        "Check why this run needed a place that no earlier run touched. The report lists the folders in this zone.",
        _first_seen(lambda e: e.zone if e.kind == "touch" and e.zone != "repo" else None),
    ),
    Rule(
        "H002",
        "medium",
        "First seen in this repo: a network host or channel",
        "Check that the host belongs to the task. Allow it for this repo only if later runs keep needing it.",
        _first_seen(lambda e: e.target if e.kind == "net" else None),
    ),
    Rule(
        "H003",
        "high",
        "First seen in this repo: a credential-like path",
        "Check why this run reached for a credential that earlier runs did not need. "
        "Rotate it if you cannot explain the access.",
        _first_seen(lambda e: e.target if e.kind == "touch" and e.zone == "credential" else None),
    ),
)


def evaluate(record: Record, history: list[Record]) -> list[Finding]:
    """One finding per rule that matched, most severe first. `history`: earlier runs of the same repo."""
    findings = []
    for rule in RULES:
        targets = rule.match(record, history)
        if targets:
            examples = tuple(dict.fromkeys(targets))[:5]  # distinct, in first-seen order
            findings.append(Finding(rule.id, rule.severity, rule.title, rule.advice, len(targets), examples))
    return sorted(findings, key=lambda f: (SEVERITIES.index(f.severity), f.rule))
