"""The Pi reader against synthetic session records (tests/fixtures/pi)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stickyagents.readers import pi

HOME = Path("/home/dev")
FIXTURES = Path(__file__).parent / "fixtures" / "pi"
FOLDER = FIXTURES / "sessions" / "--home-dev-project--"
SESSION = FOLDER / "2026-02-03T09-00-00-000Z_5f0c1a2b-3c4d-4e5f-8a6b-7c8d9e0f1a2b.jsonl"


class ReadSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        runs = pi.read(SESSION, HOME)
        assert len(runs) == 1
        cls.run_ = runs[0]
        cls.calls = runs[0].calls

    def test_meta(self) -> None:
        meta = self.run_.meta
        self.assertEqual(meta.harness, "pi")
        self.assertEqual(meta.session, "5f0c1a2b-3c4d-4e5f-8a6b-7c8d9e0f1a2b")
        self.assertEqual(meta.start, "/home/dev/project")
        self.assertEqual(meta.started, "2026-02-03T09:00:00.000Z")
        self.assertEqual(meta.source, str(SESSION))
        self.assertEqual(meta.modes, ())
        self.assertEqual(meta.state_dirs, ("~/.pi",))
        self.assertEqual(meta.siblings, ())

    def test_every_tool_maps_to_its_kind_in_order(self) -> None:
        expected = [
            ("read", "read"),
            ("grep", "read"),
            ("find", "read"),
            ("ls", "read"),
            ("edit", "write"),
            ("write", "write"),
            ("bash", "shell"),
            ("todo", "other"),  # an unknown tool, though its arguments hold a path and a command
            ("read", "read"),
        ]
        self.assertEqual([(call.tool, call.kind) for call in self.calls], expected)

    def test_paths_come_from_file_tools_only(self) -> None:
        paths = [call.paths for call in self.calls if call.kind in ("read", "write")]
        self.assertEqual(
            paths,
            [
                ("/home/dev/project/README.md",),
                ("/home/dev/project/src",),
                ("/home/dev/project",),
                (),  # ls without a folder
                ("src/app.py",),
                ("/tmp/notes.txt",),
                ("/home/dev/project/LICENSE",),
            ],
        )
        self.assertTrue(all(call.paths == () for call in self.calls if call.kind not in ("read", "write")))

    def test_shell_calls_keep_their_command(self) -> None:
        commands = [call.command for call in self.calls if call.kind == "shell"]
        self.assertEqual(commands, ["pytest -q"])
        self.assertTrue(all(call.command is None for call in self.calls if call.kind != "shell"))

    def test_unknown_tool_is_other_without_paths_or_command(self) -> None:
        (call,) = [call for call in self.calls if call.tool == "todo"]
        self.assertEqual((call.kind, call.paths, call.command), ("other", (), None))

    def test_no_url_sub_refusal_or_sandbox_flag(self) -> None:
        for call in self.calls:
            self.assertIsNone(call.url)
            self.assertFalse(call.sub or call.refused or call.unsandboxed)

    def test_time_is_the_entry_timestamp_or_the_messages_epoch(self) -> None:
        self.assertEqual(self.calls[0].time, "2026-02-03T09:00:03.000Z")
        self.assertEqual(self.calls[7].time, "2026-02-03T09:00:07.000Z")
        self.assertEqual(self.calls[-1].time, "2026-02-03T09:00:12.000Z")  # converted from epoch milliseconds

    def test_user_lines_results_broken_lines_and_typed_commands_add_no_call(self) -> None:
        self.assertEqual(len(self.calls), 9)
        self.assertNotIn("/home/dev/.ssh/config", [path for call in self.calls for path in call.paths])
        self.assertNotIn("rm -rf build", [call.command for call in self.calls])


class ReadOtherInput(unittest.TestCase):
    def test_empty_file(self) -> None:
        self.assertEqual(pi.read(FIXTURES / "empty.jsonl", HOME), [])

    def test_not_a_session(self) -> None:
        # Its first line is not a header; a header-like line further down does not make it one.
        self.assertEqual(pi.read(FIXTURES / "not-a-session.jsonl", HOME), [])

    def test_missing_file_folder_and_binary_file(self) -> None:
        self.assertEqual(pi.read(FOLDER / "missing.jsonl", HOME), [])
        self.assertEqual(pi.read(FOLDER, HOME), [])
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "binary.jsonl"
            binary.write_bytes(bytes(range(256)) * 4)
            self.assertEqual(pi.read(binary, HOME), [])

    def test_header_without_time_or_folder_is_a_run_with_an_empty_start(self) -> None:
        (run,) = pi.read(FOLDER / "2026-02-04T09-00-00-000Z_header-only.jsonl", HOME)
        self.assertEqual((run.meta.start, run.meta.started, run.calls), ("", None, []))

    def test_fields_of_the_wrong_type_never_raise(self) -> None:
        (run,) = pi.read(FIXTURES / "wrong-types.jsonl", HOME)
        self.assertEqual(run.meta.start, "")  # cwd was a number
        self.assertEqual(run.meta.started, "2026-02-03T09:00:00.000Z")  # epoch milliseconds
        kinds = [("", "other"), ("read", "read"), ("read", "read"), ("bash", "shell")]
        self.assertEqual([(call.tool, call.kind) for call in run.calls], kinds)
        for call in run.calls:
            self.assertEqual((call.paths, call.command, call.url, call.time), ((), None, None, None))

    def test_session_id_is_safe_as_a_file_name(self) -> None:
        (run,) = pi.read(FOLDER / "2026-02-04T09-00-00-000Z_header-only.jsonl", HOME)
        self.assertEqual(run.meta.session, "a_b____c")


class Find(unittest.TestCase):
    def test_finds_session_files_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            sessions = home / ".pi" / "agent" / "sessions"
            wanted = [sessions / "--home-dev-a--" / "t1_s1.jsonl", sessions / "--home-dev-a--" / "t2_s2.jsonl"]
            wanted.append(sessions / "--home-dev-b--" / "t0_s0.jsonl")
            others = [
                sessions / "--home-dev-a--" / "notes.md",
                home / ".pi" / "agent" / "settings.json",
                home / ".pi" / "agent" / "history.jsonl",  # beside the sessions folder, not in it
                home / ".pi" / "stray.jsonl",
            ]
            for path in reversed(wanted + others):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            (sessions / "--home-dev-b--" / "folder.jsonl").mkdir()
            self.assertEqual(pi.find(home), wanted)

    def test_home_without_the_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(pi.find(Path(tmp)), [])
            (Path(tmp) / ".pi").mkdir()
            self.assertEqual(pi.find(Path(tmp)), [])

    def test_fixture_tree_reads_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".pi" / "agent").mkdir(parents=True)
            (home / ".pi" / "agent" / "sessions").symlink_to(FIXTURES / "sessions", target_is_directory=True)
            found = pi.find(home)
            runs = [run for path in found for run in pi.read(path, home)]
        self.assertEqual(len(found), 2)
        self.assertEqual([len(run.calls) for run in runs], [9, 0])


class Constants(unittest.TestCase):
    def test_contract(self) -> None:
        self.assertEqual((pi.NAME, pi.STATE_DIRS), ("pi", ("~/.pi",)))


if __name__ == "__main__":
    unittest.main()
