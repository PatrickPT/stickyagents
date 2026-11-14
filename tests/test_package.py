import unittest

import stickyagents


class PackageTest(unittest.TestCase):
    def test_version(self):
        self.assertRegex(stickyagents.__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
