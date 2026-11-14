"""Zones: where a path lies, seen from the folder a run started in. Fixed rules, first match wins."""

from __future__ import annotations

import os
import re
from pathlib import Path

from .model import RunMeta

# Credential-like places under a home folder: the folder or file itself and everything below it.
_HOME_CREDENTIALS = (
    ".ssh .gnupg .aws .azure .kube .docker/config.json .git-credentials .cargo/credentials .cargo/credentials.toml "
    ".bash_history .zsh_history .config/gh .config/gcloud .config/sops .config/age "
    ".claude/.credentials.json .codex/auth.json .gemini/oauth_creds.json"
).split()
_HOMES = re.compile(r"/(?:root|home/[^/]+|Users/[^/]+)(?=/|$)")  # any user's home folder, not only this one
# Harness folders that keep logins in a file called auth.json somewhere below them.
_AUTH_JSON_DIRS = (".local/share/opencode", ".pi")
# Credential-like by file name, wherever the file lies. Public keys (.pub) are excluded before this is asked.
_CREDENTIAL_NAME = re.compile(
    r"\.(pem|key|p12|pfx|kdbx)$|^id_(rsa|ed25519|ecdsa)|^\.env(?!\.(example|sample|template|dist)$)(\..*)?$"
    r"|^\.(npmrc|pypirc|netrc)$",
    re.I,
)
_CREDENTIAL_SYSTEM = re.compile(r"/etc/(shadow-?$|sudoers|ssl/private/)|/proc/[^/]+/environ$")
_SCRATCH = ("/tmp", "/var/tmp", "/dev/shm", "/private/tmp", "/var/folders")  # noqa: S108 (named, never written)


def tilde(path: str, home: str) -> str:
    """`path` with the home folder shown as ~, so that no record carries a user's name."""
    home = home.rstrip("/")
    if home and (path == home or path.startswith(home + "/")):
        return "~" + path[len(home) :]
    return path


def _absolute(path: str, base: str, home: str) -> str:
    """`path` (absolute, ~/ or relative to `base`) made absolute and normalised, from the text alone."""
    if path == "~" or path.startswith("~/"):
        path = home.rstrip("/") + path[1:]
    path = os.path.normpath(os.path.join(base, path))
    return "/" + path.lstrip("/") if path.startswith("/") else path  # normpath keeps a leading "//"


def _under(path: str, folder: str) -> bool:
    return bool(folder) and (path == folder or path.startswith(folder.rstrip("/") + "/"))


def _in_scratch(full: str) -> bool:
    return any(_under(full, folder) for folder in _SCRATCH)


def _credential(full: str, home: str) -> bool:
    name = os.path.basename(full)
    if name.endswith(".pub"):
        return False
    if _CREDENTIAL_NAME.search(name) or _CREDENTIAL_SYSTEM.match(full):
        return True
    owner = home if _under(full, home) else m.group() if (m := _HOMES.match(full)) else None
    rel = full[len(owner) :] if owner else ""
    return any(_under(rel, f"/{part}") for part in _HOME_CREDENTIALS) or (
        name == "auth.json" and any(_under(rel, f"/{part}") for part in _AUTH_JSON_DIRS)
    )


def classify(path: str, meta: RunMeta, home: str) -> tuple[str, str] | None:
    """The zone of a recorded path and the path to show (home as ~). None when it is no touch.

    No touch: empty input, /dev/* (except /dev/shm), and a relative path without a start folder to
    resolve it against. The filesystem is never asked, so a link is judged by where it stands.
    """
    if not path or not path.strip():
        return None
    home = home.rstrip("/")
    start = _absolute(meta.start, "", home) if meta.start else ""
    full = _absolute(path, start, home)
    if not full.startswith("/") or (_under(full, "/dev") and not _in_scratch(full)):  # /dev/shm is scratch
        return None
    if _credential(full, home):
        zone = "credential"
    elif _under(full, start):
        zone = "repo"
    elif any(_under(full, _absolute(folder, "", home)) for folder in meta.siblings):
        zone = "sibling"
    elif _in_scratch(full):
        zone = "scratch"
    elif any(_under(full, _absolute(folder, "", home)) for folder in meta.state_dirs):
        zone = "agent-state"
    elif _under(full, home):
        zone = "home"
    else:
        zone = "system"
    return zone, tilde(full, home)


def find_siblings(start: str) -> tuple[str, ...]:
    """The main repository and the other worktrees of the repository `start` is a checkout of.

    Best effort, read from `.git` without running git: no repository or any error gives ().
    """
    if not start:
        return ()
    try:
        here = Path(os.path.abspath(start))
        dot = here / ".git"
        if dot.is_file():  # a worktree: "gitdir: <main>/.git/worktrees/<name>"
            gitdir = here / dot.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip()
            if gitdir.parent.name != "worktrees":  # a submodule, not a worktree
                return ()
            common = gitdir.parent.parent
        elif dot.is_dir():
            common = dot
        else:
            return ()
        found = {os.path.normpath(common.parent)} if common.name == ".git" else set()  # a bare repo has no folder
        for link in common.glob("worktrees/*/gitdir"):  # each holds "<worktree>/.git"
            found.add(os.path.normpath((link.parent / link.read_text(encoding="utf-8").strip()).parent))
        return tuple(sorted(found - {str(here)}))
    except (OSError, IndexError, ValueError):
        return ()
