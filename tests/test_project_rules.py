"""The project's own rules, as checks: no network, no dependency, small enough to read."""

import ast
import sys
import unittest
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "stickyagents"
FORBIDDEN = {"socket", "ssl", "http", "ftplib", "smtplib", "telnetlib", "asyncio", "subprocess", "urllib.request"}
MAX_LINES = 1600  # SC-006
MAX_READER_LINES = 150


def imports(path):
    """Every module a file imports, as dotted names."""
    names = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


class ProjectRulesTest(unittest.TestCase):
    def test_no_network_and_no_subprocess(self):
        for path in sorted(SRC.rglob("*.py")):
            used = {name for name in imports(path) if name in FORBIDDEN or name.split(".")[0] in FORBIDDEN}
            self.assertEqual(used, set(), f"{path.name} imports {sorted(used)}")

    def test_standard_library_only(self):
        for path in sorted(SRC.rglob("*.py")):
            roots = {name.split(".")[0] for name in imports(path)} - {"stickyagents", "__future__"}
            outside = {root for root in roots if root not in sys.stdlib_module_names}
            self.assertEqual(outside, set(), f"{path.name} imports {sorted(outside)}")

    def test_small_enough_to_read(self):
        counts = {path: len(path.read_text().splitlines()) for path in SRC.rglob("*.py")}
        self.assertLess(sum(counts.values()), MAX_LINES)
        for path, lines in counts.items():
            if path.parent.name == "readers" and path.name != "__init__.py":
                self.assertLess(lines, MAX_READER_LINES, path.name)


if __name__ == "__main__":
    unittest.main()
