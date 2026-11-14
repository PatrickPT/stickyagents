"""The scan must survive anything one session record holds, and must notice every change of a source."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stickyagents import cli
from stickyagents.model import Run, RunMeta, ToolCall
from stickyagents.normalise import normalise

FIXTURES = Path(__file__).parent / "fixtures" / "claude_code" / "projects"


class TimeTest(unittest.TestCase):
    def test_a_time_at_the_edge_of_the_calendar_becomes_none(self):
        meta = RunMeta(harness="pi", session="s", start="/home/dev/project", started="0001-01-01T00:00:00+02:00")
        call = ToolCall(tool="bash", kind="shell", command="ls", time="9999-12-31T23:59:59-02:00")
        record = normalise(Run(meta, [call]), "/home/dev")
        self.assertIsNone(record.meta.started)
        self.assertEqual({event.time for event in record.events}, {None})


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        shutil.copytree(FIXTURES, self.home / ".claude" / "projects")
        patch = mock.patch.dict(os.environ, {"STICKYAGENTS_HOME": str(Path(self.temp.name) / "state")})
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_run_that_cannot_be_normalised_or_saved_is_counted_not_fatal(self):
        for target in ("stickyagents.normalise.normalise", "stickyagents.store.save"):
            with self.subTest(target=target), mock.patch(target, side_effect=OverflowError("boom")):
                counts = cli.scan(self.home)
                self.assertEqual((counts["unreadable"], counts["runs"]), (1, 0))
        self.assertEqual(cli.scan(self.home)["runs"], 1)  # not marked as seen: it is read again


class StampTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "sessions.db"
        self.source.write_bytes(b"data")
        self.log = self.source.with_name("sessions.db-wal")
        self.log.write_bytes(b"log")

    def later(self, path):
        stat = path.stat()
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    def test_a_change_of_the_log_alone_is_a_change(self):
        before = cli._stamp(self.source)
        self.later(self.log)  # same size, as after a checkpoint and a new row
        self.assertNotEqual(cli._stamp(self.source), before)

    def test_the_shared_memory_file_does_not_count(self):
        before = cli._stamp(self.source)
        self.source.with_name("sessions.db-shm").write_bytes(b"x")
        self.assertEqual(cli._stamp(self.source), before)

    def test_a_source_without_a_log(self):
        self.log.unlink()
        self.assertEqual(len(cli._stamp(self.source)), 2)


if __name__ == "__main__":
    unittest.main()
