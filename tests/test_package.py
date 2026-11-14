import unittest
from pathlib import Path

import stickyagents


class PackageTest(unittest.TestCase):
    def test_version(self):
        self.assertRegex(stickyagents.__version__, r"^\d+\.\d+\.\d+$")
        pyproject = (Path(__file__).parent.parent / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn(f'version = "{stickyagents.__version__}"', pyproject)


if __name__ == "__main__":
    unittest.main()
