"""The shared types. Readers produce Run; everything after normalise works on Record."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

SCHEMA = 1

CALL_KINDS = ("read", "write", "shell", "fetch", "search", "other")
ZONES = ("credential", "repo", "sibling", "scratch", "agent-state", "home", "system")
EVENT_KINDS = ("call", "touch", "net", "cmd", "flag")
MODES = ("read", "write", "mention")
FLAGS = ("sudo", "pipe-to-shell", "force-push", "push-main")
SEVERITIES = ("critical", "high", "medium", "low")


@dataclass
class ToolCall:
    """One tool call as a harness recorded it. `command` and `url` never leave memory."""

    tool: str  # the harness's own name for the tool
    kind: str  # one of CALL_KINDS
    time: str | None = None  # ISO 8601, as recorded
    paths: tuple[str, ...] = ()  # read/write: the paths as given (absolute, relative or ~/)
    command: str | None = None  # shell: the command text
    url: str | None = None  # fetch: the URL
    sub: bool = False  # made by a subagent
    unsandboxed: bool = False  # shell: asked to run outside the harness's sandbox
    refused: bool = False  # the harness or the user refused the call


@dataclass
class RunMeta:
    harness: str  # the reader's NAME
    session: str  # the harness's session id; safe as a file name
    start: str  # the folder the session started in (absolute in a Run, with ~ in a Record)
    started: str | None = None  # ISO 8601 time of the first record
    source: str = ""  # where the session record lives
    modes: tuple[str, ...] = ()  # permission modes the record shows, in the harness's words
    state_dirs: tuple[str, ...] = ()  # the harness's own folders, as ~/...
    siblings: tuple[str, ...] = ()  # other worktrees of the same repo, if known


@dataclass
class Run:
    """What a reader returns."""

    meta: RunMeta
    calls: list[ToolCall] = field(default_factory=list)


@dataclass(frozen=True)
class Event:
    """One stored fact about a run. Fields that don't apply to the kind stay None.

    call:  call_kind, unsandboxed, refused         one per tool call
    touch: mode, zone, target (a path, home as ~)  exact for file tools, a mention for shell text
    net:   target (a host, or a channel such as "git remote")
    cmd:   target (a command name seen in shell text)
    flag:  target (one of FLAGS)
    """

    kind: str  # one of EVENT_KINDS
    tool: str
    time: str | None = None
    sub: bool = False
    exact: bool = True
    call_kind: str | None = None
    unsandboxed: bool | None = None
    refused: bool | None = None
    mode: str | None = None  # one of MODES
    zone: str | None = None  # one of ZONES
    target: str | None = None

    def to_json(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}

    @classmethod
    def from_json(cls, data: dict) -> Event:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class Record:
    """What is stored: every path shown with the home folder as ~."""

    meta: RunMeta
    events: list[Event] = field(default_factory=list)


@dataclass(frozen=True)
class Finding:
    rule: str  # the rule's id, such as "C001"
    severity: str  # one of SEVERITIES
    title: str
    advice: str
    count: int
    examples: tuple[str, ...] = ()  # at most five targets
