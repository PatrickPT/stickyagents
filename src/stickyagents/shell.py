"""What the text of a shell command names: commands, paths, hosts and a few risky patterns.

Text only: nothing is run or looked up. Everything found here is a mention, never an exact touch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urlsplit

_LEAD = frozenset("if then else elif do while until { !".split())  # a command may follow in the same segment
_STOP = frozenset("for case esac done fi } in function select".split())  # no command in this segment
# Wrappers to look through, each with its one-letter options that take a value.
_WRAPPERS = {
    "sudo": "ugpChDRT",
    "doas": "uC",
    "env": "uCS",
    "timeout": "sk",
    "xargs": "nIPLsdEa",
    "exec": "a",
} | dict.fromkeys(("time", "nohup", "command", "pkexec"), "")
_SHELLS = ("sh", "bash", "zsh", "dash")
_INTERPRETERS = (*_SHELLS, "python", "python3")
_FETCHERS = ("curl", "wget")
_VALUE_OPTIONS = ("-C", "-c", "--git-dir", "--work-tree", "--prefix", "--context")  # may stand before a subcommand
_GIT_REMOTE = {"push", "fetch", "pull", "clone", "ls-remote"}
# Commands whose http(s) arguments are hosts they talk to, by subcommand (None: any). Other URLs are just text.
_URL_COMMANDS: dict[str, set[str] | None] = {
    **dict.fromkeys("curl wget http httpie npm pnpm yarn npx brew ssh scp rsync".split()),
    **dict.fromkeys(("pip", "pip3", "pipx"), {"install"}),
    **dict.fromkeys(("docker", "podman"), {"pull", "push"}),
    "git": _GIT_REMOTE | {"remote"},
    "uv": {"pip install", "add", "tool install"},
}
# Channels a command uses even when it names no URL: commands, subcommands (None: any), channel.
_CHANNELS = (
    ("gh", None, "github.com (gh)"),
    ("git", _GIT_REMOTE, "git remote"),
    ("npm pnpm yarn", {"install", "i", "ci", "add", "update", "upgrade", "dlx", "create", "publish"}, "npm registry"),
    ("npx", None, "npm registry"),
    ("yarn", {""}, "npm registry"),  # bare `yarn` installs
    ("pip pip3 pipx", None, "pypi"),
    ("uv", {"pip", "add", "sync"}, "pypi"),
    ("cargo", {"install", "add", "build", "fetch"}, "crates.io"),
    ("go", {"get", "install", "mod download"}, "go proxy"),
    ("docker podman", {"pull", "push", "run", "build"}, "container registry"),
    ("brew", None, "homebrew"),
    ("apt apt-get dnf yum apk", None, "os packages"),
)
_NAME = re.compile(r"[A-Za-z0-9_.+][A-Za-z0-9_.+-]*")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*\+?=")
_HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*[\"']?([A-Za-z_]\w*)")
_HTTP = re.compile(r"https?://[^\s'\"`<>]+", re.I)
_HOSTNAME = re.compile(r"[a-z0-9:][a-z0-9._:-]*")
_HOME = re.compile(r"\$\{?HOME\}?(?=/)")
# A path is a whole word that starts with / or ~/ (never after =), or the target of a redirection.
_PATH = re.compile(r"~?/[^\s'\"`;|&<>(){}\[\]$*?!,:=\\#^]+")
_REDIRECT = re.compile(r"(?:^(?:\d+|&))?(?:>>?|<)&?")
_DEVNET = re.compile(r"/dev/(?:tcp|udp)/([^/]+)")
# The values of these options are text, and so are the arguments of these commands (but not their redirections).
_TEXT_OPTIONS = (
    "-H --header -d --data --data-raw --data-binary --data-urlencode -m --message -u --user -F --form -e --password "
    "--token"
).split()
_TEXT_COMMANDS = ("echo", "printf")
_PATTERN_COMMANDS = "sed awk gawk grep egrep fgrep rg ag perl jq yq tr".split()  # a quoted word is a pattern
_FORCE = re.compile(r"--force(-with-lease(=.*)?|-if-includes)?|-[A-Za-z]*f[A-Za-z]*")
_MAIN = re.compile(r"(^|:)\+?(refs/heads/)?(main|master)$")
_CODE_OPTION = re.compile(r"-[A-Za-z]*[cm]")  # -c 'code', -lc, -m module
_SUB = re.compile(r"\$\(([^()]+)\)|`([^`]+)`")


class _Word(str):
    """A word without its quotes. `kind`: "" bare, "q"/"d" single/double quoted, "m"/"M" mixed or escaped."""

    def __new__(cls, text: str, kind: str = ""):
        word = super().__new__(cls, text)
        word.kind = kind
        return word


@dataclass(frozen=True)
class ShellFacts:
    commands: tuple[str, ...]  # one name per pipeline or list segment, in order, with repeats
    paths: tuple[str, ...]  # absolute and ~/ paths named in the text
    hosts: tuple[str, ...]  # URL hosts of network commands, and channels such as "git remote"
    flags: tuple[str, ...]  # from model.FLAGS


def url_host(url: str) -> str | None:
    """The lower-cased host of a URL, or None when it has none that reads as a host name."""
    try:
        host = urlsplit(url if "://" in url else "//" + url).hostname or ""
    except ValueError:
        return None
    return host if _HOSTNAME.fullmatch(host) else None


def _strip_heredocs(text: str) -> str:
    """Drop heredoc bodies: they are data for a command, not commands."""
    lines, kept, i = text.split("\n"), [], 0
    while i < len(lines):
        kept.append(lines[i])
        i += 1
        for word in _HEREDOC.findall(kept[-1]):
            ends = [j for j in range(i, len(lines)) if lines[j].strip() == word]
            i = ends[0] + 1 if ends else i  # no end line: it was no heredoc
    return "\n".join(kept)


def _segments(text: str) -> list[tuple[str, list[_Word]]]:
    """Split into (operator before, words) per command, minding quotes, comments, $((..)) and case patterns."""
    segments: list[tuple[str, list[_Word]]] = []
    words: list[_Word] = []
    word: str | None = None  # None between words; "" is an empty quoted word
    before, quote, kind, depth, i = "", "", "", 0, 0
    while i < len(text):
        ch = text[i]
        i += 1
        if quote:
            if ch == quote:
                quote = ""
            elif ch == "\\" and quote == '"' and i < len(text):
                word, i = (word or "") + text[i], i + 1
            else:
                word = (word or "") + ch
        elif ch in "\"'":
            q = "d" if ch == '"' else "q"
            quote, word, kind = ch, word or "", q if word is None else ("M" if "d" in kind + q else "m")
        elif ch == "\\" and i < len(text):
            word, i, kind = (word if text[i] == "\n" else (word or "") + text[i]), i + 1, "M" if "d" in kind else "m"
        elif ch == "#" and word is None:
            i = (text + "\n").index("\n", i)
        elif text.startswith("((", i - 1):
            i = (text + "))").index("))", i) + 2  # arithmetic holds no command
        elif ch == "&" and ((word or " ")[-1] in "<>" or text[i : i + 1] == ">"):
            word = (word or "") + ch  # 2>&1 and &> are redirections
        elif ch in " \t|&;\n()`":
            lead = ""
            if ch == "(" and word and word[-1] in "<$":
                lead, word = word[-1], word[:-1] or None
            if word is not None:
                words.append(_Word(word, kind))
                word, kind = None, ""
            if ch in " \t":
                continue
            op = text[i - 1 : i + 1] if text[i - 1 : i + 1] in ("||", "&&", "|&", ";;") else ch
            i += len(op) - 1
            if ch == ")" and depth == 0:
                words = []  # `pattern)` in a case, not a command
            depth = max(depth + (ch == "(") - (ch == ")"), 0)
            if words:
                segments.append((before, words))
            if words or ch != "\n":  # a newline behind an operator continues the list
                before = lead + op
            words = []
        else:
            word, kind = (word or "") + ch, ("M" if "d" in kind else "m") if kind in ("q", "d") else kind
    if word is not None:
        words.append(_Word(word, kind))
    return segments + [(before, words)] if words else segments


def _command(words: list[str]) -> tuple[str | None, list[str], bool]:
    """A segment's command name behind assignments, keywords and wrappers; its arguments; whether sudo ran it."""
    wrapper, sudo, i = None, False, 0
    while i < len(words):
        name = words[i].rsplit("/", 1)[-1]
        i += 1
        if _ASSIGNMENT.match(words[i - 1]) or name in _LEAD:
            continue
        if name in _STOP:
            break
        if name not in _WRAPPERS:
            return (name if _NAME.fullmatch(name) else wrapper), words[i:], sudo
        wrapper, sudo = name, sudo or name in ("sudo", "doas", "pkexec")
        if name == "command" and words[i : i + 1] in (["-v"], ["-V"]):
            break  # a lookup, not a run
        while i < len(words) and words[i].startswith("-"):
            i += 2 if len(words[i]) == 2 and words[i][1] in _WRAPPERS[name] else 1
        i += name == "timeout"  # its duration
    return wrapper, [], sudo  # a wrapper on its own is the command


def _positional(args: list[str]) -> list[str]:
    """Arguments that are no options and no option values: the subcommand comes first."""
    found, skip = [], False
    for arg in args:
        if not skip and arg not in _VALUE_OPTIONS and not arg.startswith("-"):
            found.append(arg)
        skip = not skip and arg in _VALUE_OPTIONS
    return found


def _has(positional: list[str], subcommands: set[str] | None) -> bool:
    first = positional[0] if positional else ""
    return subcommands is None or not subcommands.isdisjoint((first, " ".join(positional[:2])))


def _paths(name: str | None, words: list[_Word]) -> list[str]:
    """The paths a segment names: whole words only, never an option value, a text argument or a pattern."""
    found, skip, target = [], False, False  # skip: the last word was an option with a text value
    for word in words:
        ok = word.kind == "" or (
            word.kind in ("q", "d") and name not in _PATTERN_COMMANDS and not any(map(str.isspace, word))
        )
        pieces = _REDIRECT.split(word) if not word.kind else [word]
        for n, piece in enumerate(pieces):
            text = skip or (name in _TEXT_COMMANDS and not (n or target))
            match = _PATH.match(_HOME.sub("~", piece)) if ok and not text else None
            if match:
                path = match.group()
                if (match.string[match.end() :][:1] or " ") in "*?[{$":
                    path = path[: path.rfind("/") + 1]  # the last part is a pattern or a variable: keep its folder
                if path.endswith(".") and not path.endswith(("/.", "..")):
                    path = path[:-1]  # the full stop of a sentence
                path = path.rstrip("/")
                if path == "~" or re.search(r"[A-Za-z0-9]", path):
                    found.append(path)
        is_test = name == "test" or "[" in words or "[[" in words
        skip, target = word in _TEXT_OPTIONS and not (word == "-e" and is_test), len(pieces) > 1 and pieces[-1] == ""
    return found


def _walk(text: str, outer: str | None, depth: int, out: dict[str, list[str]]) -> None:
    """Collect commands, paths, hosts and flags from `text`; `outer` is the shell that was handed it with -c."""
    previous, piped = outer, False  # piped: an earlier stage of this pipeline was curl or wget
    for before, words in _segments(text):
        name, args, sudo = _command(words)
        found, nets = ["sudo"] * (sudo or name == "su"), []
        subs = [m[0] or m[1] for w in words if w.kind in ("d", "M") for m in _SUB.findall(w)]
        piped = piped and before in ("|", "|&")
        out["paths"] += [p for p in dict.fromkeys(_paths(name, words)) if p not in out["paths"]]
        if name:
            out["commands"].append(name)
            pos = _positional(args)
            runs_input = not any(_CODE_OPTION.fullmatch(a) for a in args) and (
                name in _SHELLS or pos[:1] in ([], ["-"])
            )
            if (name in _INTERPRETERS and piped and runs_input) or (
                name in _FETCHERS and before in ("<(", "$(") and previous in (*_INTERPRETERS, "eval", "source", ".")
            ):
                found.append("pipe-to-shell")
            piped = piped or name in _FETCHERS
            if name == "git" and pos[:1] == ["push"]:
                found += ["force-push"] * (any(_FORCE.fullmatch(a) for a in args) or any(a[:1] == "+" for a in pos[1:]))
                found += ["push-main"] * any(_MAIN.search(a) for a in pos[2:])
            if _has(pos, _URL_COMMANDS.get(name, set())):
                nets += [url_host(url) for arg in args for url in _HTTP.findall(arg)]
            if (name == "ssh" and pos) or (name in ("scp", "rsync") and any(":" in a for a in pos)):
                nets.append("ssh")
            nets += [channel for names, subs_, channel in _CHANNELS if name in names.split() and _has(pos, subs_)]
            code = [j for j, arg in enumerate(args[:-1]) if re.fullmatch(r"-[a-z]*c", arg)]
            subs = [args[code[0] + 1]] if name in _SHELLS and code else [" ".join(args)] if name == "eval" else subs
        for sub in subs:
            if sub and depth < 3:
                _walk(sub, name, depth + 1, out)
        previous = name
        out["hosts"] += [net for net in dict.fromkeys(nets) if net and net not in out["hosts"]]
        out["flags"] += [flag for flag in dict.fromkeys(found) if flag not in out["flags"]]


def _facts(command: str) -> ShellFacts:
    out: dict[str, list[str]] = {key: [] for key in ShellFacts.__dataclass_fields__}
    _walk(_strip_heredocs(command), None, 0, out)
    for path in out["paths"]:  # /dev/tcp/<host>/<port> is a connection
        if (net := _DEVNET.match(path)) and (host := url_host(net[1])) and host not in out["hosts"]:
            out["hosts"].append(host)
    return ShellFacts(**{key: tuple(found) for key, found in out.items()})


def parse(command: str) -> ShellFacts:
    """The facts in a shell command's text. Never raises: one text it can't follow must not end a whole scan."""
    try:
        return _facts(command)
    except Exception:  # the tests fuzz _facts itself, so this guard hides no known fault
        return ShellFacts((), (), (), ())
