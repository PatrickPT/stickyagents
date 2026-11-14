"""The Claude Code reader against synthetic session records (tests/fixtures/claude_code)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from stickyagents.model import CALL_KINDS
from stickyagents.readers import claude_code

HOME = Path("/home/dev")
FIXTURES = Path(__file__).parent / "fixtures" / "claude_code"
PROJECT = FIXTURES / "projects" / "-home-dev-project"
SESSION = PROJECT / "0a1b2c3d-1111-4222-8333-444455556666.jsonl"


class ReadSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        runs = claude_code.read(SESSION, HOME)
        assert len(runs) == 1
        cls.run_ = runs[0]
        cls.calls = runs[0].calls

    def by_command(self, command: str):
        return next(call for call in self.calls if call.command == command)

    def test_meta(self) -> None:
        meta = self.run_.meta
        self.assertEqual(meta.harness, "claude-code")
        self.assertEqual(meta.session, "0a1b2c3d-1111-4222-8333-444455556666")
        self.assertEqual(meta.start, "/home/dev/project")
        self.assertEqual(meta.started, "2026-01-05T10:00:00.000Z")
        self.assertEqual(meta.source, str(SESSION))
        self.assertEqual(meta.state_dirs, ("~/.claude",))
        self.assertEqual(meta.siblings, ())

    def test_modes_are_distinct_and_in_first_seen_order(self) -> None:
        self.assertEqual(self.run_.meta.modes, ("default", "acceptEdits", "plan"))

    def test_every_tool_maps_to_its_kind_in_order(self) -> None:
        expected = [
            ("Read", "read"),
            ("Grep", "read"),
            ("Glob", "read"),
            ("Bash", "shell"),  # the subagent's two calls fall here by time
            ("Read", "read"),
            ("NotebookRead", "read"),
            ("LS", "read"),
            ("Edit", "write"),
            ("Write", "write"),
            ("MultiEdit", "write"),
            ("NotebookEdit", "write"),
            ("Bash", "shell"),
            ("Bash", "shell"),
            ("PowerShell", "shell"),
            ("Monitor", "shell"),
            ("WebFetch", "fetch"),
            ("WebSearch", "search"),
            ("Agent", "other"),
            ("mcp__tracker__create_issue", "other"),
            ("Bash", "shell"),
            ("Write", "write"),
            ("Bash", "shell"),
            ("Read", "read"),
        ]
        self.assertEqual([(call.tool, call.kind) for call in self.calls], expected)
        self.assertEqual({call.kind for call in self.calls}, set(CALL_KINDS))
        self.assertEqual([call.time for call in self.calls], sorted(call.time for call in self.calls))

    def test_paths_come_from_file_tools_only(self) -> None:
        paths = [call.paths for call in self.calls if call.kind in ("read", "write")]
        self.assertEqual(
            paths,
            [
                ("/home/dev/project/README.md",),
                ("/home/dev/project/src",),
                (),  # Glob without a folder
                ("/home/dev/.netrc",),
                ("/home/dev/project/notes.ipynb",),
                ("/home/dev/project",),
                ("/home/dev/project/src/app.py",),
                ("/tmp/health-notes.txt",),
                ("src/routes.py",),
                ("/home/dev/project/notes.ipynb",),
                ("/home/dev/.bashrc",),
                ("/home/dev/project/src/routes.py",),
            ],
        )
        self.assertTrue(all(call.paths == () for call in self.calls if call.kind not in ("read", "write")))

    def test_shell_calls_keep_their_command(self) -> None:
        commands = [call.command for call in self.calls if call.kind == "shell"]
        self.assertEqual(
            commands,
            ["ls src", "pytest -q", "docker ps", "Get-ChildItem", "tail -f build.log", "git push --force origin main"]
            + ["rm -rf build"],
        )
        self.assertTrue(all(call.command is None for call in self.calls if call.kind != "shell"))

    def test_sandbox_flag(self) -> None:
        self.assertEqual([call.command for call in self.calls if call.unsandboxed], ["docker ps"])

    def test_fetch_keeps_the_url_and_search_nothing(self) -> None:
        self.assertEqual([call.url for call in self.calls if call.url], ["https://example.com/docs/health"])
        search = next(call for call in self.calls if call.kind == "search")
        self.assertEqual((search.paths, search.command, search.url), ((), None, None))

    def test_refused_by_denial_kind_by_decision_and_by_the_harness_sentence(self) -> None:
        refused = [(call.tool, call.command or call.paths[0]) for call in self.calls if call.refused]
        self.assertEqual(
            refused,
            [
                ("Read", "/home/dev/.netrc"),  # toolDenialKind, in the subagent's file
                ("Bash", "git push --force origin main"),  # toolDenialKind
                ("Write", "/home/dev/.bashrc"),  # permissionDecision says reject
                ("Bash", "rm -rf build"),  # only the sentence, as in older records
            ],
        )

    def test_a_failed_command_is_not_refused(self) -> None:
        self.assertFalse(self.by_command("pytest -q").refused)

    def test_subagent_calls_from_its_own_file_and_from_sidechain_lines(self) -> None:
        sub = [(call.tool, call.command or call.paths[0]) for call in self.calls if call.sub]
        self.assertEqual(
            sub,
            [("Bash", "ls src"), ("Read", "/home/dev/.netrc"), ("Read", "/home/dev/project/src/routes.py")],
        )

    def test_broken_lines_repeats_and_blobs_add_no_call(self) -> None:
        self.assertEqual(len(self.calls), 23)  # 21 in the session's file, 2 in the subagent's
        commands = {call.command for call in self.calls}
        self.assertNotIn("echo repeated-in-a-blob", commands)
        self.assertEqual(sum(call.paths == ("/home/dev/project/README.md",) for call in self.calls), 1)


class ReadOtherInput(unittest.TestCase):
    def test_empty_file(self) -> None:
        self.assertEqual(claude_code.read(PROJECT / "0c3d4e5f-3333-4444-8555-666677778888.jsonl", HOME), [])

    def test_session_without_a_conversation(self) -> None:
        self.assertEqual(claude_code.read(PROJECT / "0b2c3d4e-2222-4333-8444-555566667777.jsonl", HOME), [])

    def test_not_a_session(self) -> None:
        self.assertEqual(claude_code.read(FIXTURES / "not-a-session.jsonl", HOME), [])

    def test_missing_file_folder_and_binary_file(self) -> None:
        self.assertEqual(claude_code.read(PROJECT / "missing.jsonl", HOME), [])
        self.assertEqual(claude_code.read(PROJECT, HOME), [])
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "binary.jsonl"
            binary.write_bytes(bytes(range(256)) * 4)
            self.assertEqual(claude_code.read(binary, HOME), [])

    def test_fields_of_the_wrong_type_never_raise(self) -> None:
        (run,) = claude_code.read(FIXTURES / "wrong-types.jsonl", HOME)
        self.assertEqual(run.meta.start, "/home/dev/project")
        self.assertEqual(run.meta.started, "2026-01-07T08:00:00.000Z")
        self.assertEqual(run.meta.modes, ())
        kinds = [("", "other"), ("Read", "read"), ("Bash", "shell"), ("WebFetch", "fetch")]
        self.assertEqual([(call.tool, call.kind) for call in run.calls], kinds)
        for call in run.calls:
            self.assertEqual((call.paths, call.command, call.url), ((), None, None))
            self.assertFalse(call.unsandboxed or call.refused or call.sub)

    def test_session_id_is_safe_as_a_file_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            odd = Path(tmp) / "a b$c..d.jsonl"
            odd.write_text(SESSION.read_text(encoding="utf-8"), encoding="utf-8")
            (run,) = claude_code.read(odd, HOME)
        self.assertEqual(run.meta.session, "a_b_c__d")
        self.assertEqual(len(run.calls), 21)  # no subagent folder beside this copy


class Find(unittest.TestCase):
    def test_finds_sessions_and_not_subagent_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            projects = home / ".claude" / "projects"
            wanted = [projects / "-home-dev-a" / "s1.jsonl", projects / "-home-dev-a" / "s2.jsonl"]
            wanted.append(projects / "-home-dev-b" / "s0.jsonl")
            others = [
                projects / "-home-dev-a" / "agent-0001.jsonl",  # a subagent beside its session (older layout)
                projects / "-home-dev-a" / "s1" / "subagents" / "agent-0002.jsonl",
                projects / "-home-dev-a" / "s1" / "tool-results" / "out.txt",
                projects / "-home-dev-a" / "memory" / "notes.md",
                projects / "-home-dev-b" / "index.json",
                projects / "stray.jsonl",
                home / ".claude" / "history.jsonl",
            ]
            for path in reversed(wanted + others):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("", encoding="utf-8")
            (projects / "-home-dev-b" / "folder.jsonl").mkdir()
            self.assertEqual(claude_code.find(home), wanted)

    def test_home_without_the_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(claude_code.find(Path(tmp)), [])

    def test_fixture_tree_reads_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            (home / ".claude" / "projects").symlink_to(FIXTURES / "projects", target_is_directory=True)
            found = claude_code.find(home)
            runs = [run for path in found for run in claude_code.read(path, home)]
        self.assertEqual(len(found), 3)
        self.assertEqual([len(run.calls) for run in runs], [23])


if __name__ == "__main__":
    unittest.main()
