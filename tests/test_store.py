import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stickyagents import store
from stickyagents.model import Event, Record, RunMeta


def record(session="s1", started="2026-01-01T10:00:00Z"):
    meta = RunMeta(
        harness="claude-code",
        session=session,
        start="~/project",
        started=started,
        source="~/.claude/projects/x/s1.jsonl",
        modes=("default",),
        state_dirs=("~/.claude",),
        siblings=("~/project-wt",),
    )
    events = [
        Event(kind="call", tool="Read", time=started, call_kind="read", unsandboxed=False, refused=False),
        Event(kind="touch", tool="Read", time=started, mode="read", zone="home", target="~/notes.md"),
        Event(kind="net", tool="Bash", exact=False, target="git remote"),
    ]
    return Record(meta, events)


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patch = mock.patch.dict(os.environ, {"STICKYAGENTS_HOME": self.temp.name})
        patch.start()
        self.addCleanup(patch.stop)

    def test_base_prefers_the_explicit_folder(self):
        self.assertEqual(store.base(), Path(self.temp.name))
        with mock.patch.dict(os.environ, {"XDG_STATE_HOME": "/state"}):
            del os.environ["STICKYAGENTS_HOME"]
            self.assertEqual(store.base(), Path("/state/stickyagents"))

    def test_round_trip(self):
        original = record()
        path = store.save(original)
        loaded = store.load(path)
        self.assertEqual(loaded.meta, original.meta)
        self.assertEqual(loaded.events, original.events)

    def test_file_is_private_and_first_line_is_the_meta(self):
        path = store.save(record())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertIn('"schema": 1', path.read_text().splitlines()[0])

    def test_saving_again_replaces(self):
        store.save(record())
        store.save(record())
        self.assertEqual(len(store.load_all()), 1)
        self.assertEqual([p.name for p in path_list(self.temp.name)], ["s1.jsonl"])

    def test_session_ids_cannot_leave_the_folder(self):
        path = store.save(record(session="../../etc/passwd"))
        self.assertEqual(path.parent, Path(self.temp.name) / "runs" / "claude-code")

    def test_load_all_is_oldest_first_and_skips_broken_files(self):
        store.save(record("b", "2026-01-02T00:00:00Z"))
        store.save(record("a", "2026-01-03T00:00:00Z"))
        broken = Path(self.temp.name) / "runs" / "claude-code" / "broken.jsonl"
        broken.write_text("not json\n")
        other = Path(self.temp.name) / "runs" / "claude-code" / "other-schema.jsonl"
        other.write_text('{"schema": 99, "harness": "x", "session": "y", "start": "~"}\n')
        self.assertEqual([r.meta.session for r in store.load_all()], ["b", "a"])

    def test_a_head_or_an_event_that_is_no_object_is_a_broken_file(self):
        good = json.dumps({"schema": 1, "harness": "claude-code", "session": "x", "start": "~"})
        folder = Path(self.temp.name) / "runs" / "claude-code"
        folder.mkdir(parents=True)
        for n, text in enumerate(
            ("null\n", "42\n", "[]\n", '"x"\n', f"{good}\nnull\n", f"{good}\n42\n", f"{good}\n[1]\n")
        ):
            path = folder / f"odd{n}.jsonl"
            path.write_text(text)
            with self.subTest(text=text):
                self.assertIsNone(store.load(path))
        (folder / "ok.jsonl").write_text(good + "\n")
        self.assertEqual([r.meta.session for r in store.load_all()], ["x"])

    def test_nothing_stored_yet(self):
        self.assertEqual(store.load_all(), [])


class PermissionsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name) / "state"
        patch = mock.patch.dict(os.environ, {"STICKYAGENTS_HOME": str(self.base)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(os.umask, os.umask(0o022))

    def mode(self, path):
        return stat.S_IMODE(path.stat().st_mode)

    def test_every_folder_is_private_also_when_it_was_made_before(self):
        (self.base / "runs" / "claude-code").mkdir(parents=True)
        for folder in (self.base, self.base / "runs", self.base / "runs" / "claude-code"):
            folder.chmod(0o755)
        path = store.save(record())
        for folder in (self.base, self.base / "runs", path.parent):
            self.assertEqual(self.mode(folder), 0o700, folder)

    def test_new_folders_are_private_under_a_lax_umask(self):
        path = store.save(record())
        for folder in (self.base, self.base / "runs", path.parent):
            self.assertEqual(self.mode(folder), 0o700, folder)

    def test_write_private_is_mode_600_and_leaves_no_temp_file(self):
        store.private_dir(self.base)
        target = self.base / "x.json"
        store.write_private(target, "{}")
        self.assertEqual((target.read_text(), self.mode(target)), ("{}", 0o600))
        self.assertEqual([p.name for p in self.base.iterdir()], ["x.json"])

    def test_a_failed_write_removes_its_temp_file_and_keeps_the_old_file(self):
        store.private_dir(self.base)
        target = self.base / "x.json"
        store.write_private(target, "old")
        with mock.patch("os.replace", side_effect=OSError("disk")), self.assertRaises(OSError):
            store.write_private(target, "new")
        self.assertEqual(target.read_text(), "old")
        self.assertEqual([p.name for p in self.base.iterdir()], ["x.json"])


def path_list(base):
    return sorted((Path(base) / "runs" / "claude-code").iterdir())


if __name__ == "__main__":
    unittest.main()
