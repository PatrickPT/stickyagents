"""One module per harness. Each has NAME, STATE_DIRS, find(home) and read(path, home).

    NAME: str                      "claude-code"
    STATE_DIRS: tuple[str, ...]    the harness's own folders, as "~/..."
    find(home: Path) -> list[Path]             every session source found under this home folder
    read(path: Path, home: Path) -> list[Run]  the sessions in that source; [] if none; never raises on bad input

A reader knows its harness's format and nothing else: no zones, no rules. Paths in a Run are as recorded.
To support another harness, add a module here, name it in MODULES and give it a fixture test.
"""

from __future__ import annotations

from importlib import import_module
from types import ModuleType

MODULES = ("claude_code", "pi", "opencode")


def load() -> list[ModuleType]:
    return [import_module(f"{__name__}.{name}") for name in MODULES]
