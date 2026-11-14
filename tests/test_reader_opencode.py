"""The opencode reader against a synthetic database, built in a temporary folder (no binary file is committed)."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from stickyagents.readers import opencode

HOME = Path("/home/dev")
BASE = int(datetime(2026, 2, 5, 10, 0, tzinfo=timezone.utc).timestamp() * 1000)
SCHEMA = """
CREATE TABLE session_v2 (id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT, agent TEXT, time_created INTEGER);
CREATE TABLE session_message (
  id TEXT PRIMARY KEY, session_id TEXT, type TEXT, seq INTEGER, time_created INTEGER, time_updated INTEGER, data TEXT
);
"""
ODD_ID = "ses plan/../1"


def iso(seconds: float) -> str:
    stamp = datetime.fromtimestamp((BASE + seconds * 1000) / 1000, tz=timezone.utc)
    return stamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def tool(name: str, input_: object, status: str = "completed", error: object = None, time: float | None = None):
    state: dict = {"status": status, "input": input_}
    if error is not None:
        state["error"] = error
    item: dict = {"type": "tool", "id": f"call_{name}", "name": name, "state": state, "executed": False}
    if time is not None:
        item["time"] = {"created": BASE + int(time * 1000)}
    return item


def message(agent: str, *items: object) -> str:
    content = [{"type": "text", "text": "words"}, {"type": "reasoning", "text": "..."}, *items]
    return json.dumps({"agent": agent, "content": content, "time": {"created": BASE}})


PATCH = (
    "*** Begin Patch\n*** Add File: /home/dev/project/new.py\n+x\n*** Update File: src/app.py\n@@\n-a\n+b\n"
    "*** Move to: src/app2.py\n*** Delete File: old.txt\n*** End Patch"
)
# (session, type, seq, seconds after BASE, data): order in the table is not the order of the run.
MESSAGES = [
    (
        "ses_main",
        "assistant",
        7,
        3,
        message("plan", tool("edit", {"filePath": "src/app.py"}), tool("write", {"path": "/tmp/x"})),
    ),
    (
        "ses_main",
        "assistant",
        5,
        1,
        message("build", tool("read", {"path": "/home/dev/project/README.md", "limit": 5}, time=1.5)),
    ),
    ("ses_main", "user", 6, 2, json.dumps({"text": "hi", "content": [tool("read", {"path": "/home/dev/.ssh/id"})]})),
    ("ses_sub", "assistant", 3, 5, message("explore", tool("read", {"path": "/home/dev/.netrc"}))),
    (
        "ses_main",
        "assistant",
        9,
        6,
        message("build", tool("webfetch", {"url": "https://example.com/a"}), tool("websearch", {"query": "q"})),
    ),
    (
        "ses_main",
        "assistant",
        8,
        4,
        message("build", tool("shell", {"command": "pytest -q"}), tool("bash", {"command": "ls"})),
    ),
    ("ses_main", "assistant", 10, 7, message("build", tool("task", {"prompt": "p"}), tool("todowrite", {"todos": []}))),
    (
        "ses_main",
        "assistant",
        11,
        8,
        message(
            "build",
            tool("shell", {"command": "rm -rf build"}, "error", {"type": "permission.rejected", "message": "m"}),
            tool(
                "shell", {"command": "git push"}, "error", {"message": "The user rejected permission to use this tool"}
            ),
            tool("shell", {"command": "make"}, "error", {"type": "tool.failed", "message": "exit 2"}),
            tool("shell", {"command": "false"}, "error"),
            tool("shell", '{"command": "par'),  # input still being written: never ran
            {"type": "tool", "state": {"input": {"command": "no name"}}},
            {"type": "text", "state": {"input": {"command": "not a tool"}}},
            "not an item",
        ),
    ),
    ("ses_main", "assistant", 12, 9, "{not json"),
    ("ses_main", "assistant", 13, 9, None),
    ("ses_main", "assistant", 14, 9, "[1]"),
    ("ses_main", "idle", 15, 9, json.dumps({"outcome": "done"})),
    ("ses_unknown", "assistant", 1, 9, message("build", tool("read", {"path": "/home/dev/x"}))),
    (
        "ses_main",
        "assistant",
        4,
        0.5,
        message(
            "build",
            tool("glob", {"pattern": "*.py", "path": "/home/dev/project"}),
            tool("grep", {"pattern": "a"}),
            tool("list", {"path": "/home/dev/project"}),
            tool("apply_patch", {"patchText": PATCH}),
            tool("multiedit", {"filePath": "src/b.py"}),
        ),
    ),
    (ODD_ID, "assistant", 2, 11, message("plan", tool("shell", {"command": "echo hi"}))),
    ("ses_orphan", "assistant", 2, 31, message("build", tool("read", {"path": "/home/dev/orphan.txt"}))),
]
# id, parent, directory, agent, seconds after BASE
SESSIONS = [
    ("ses_main", None, "/home/dev/project", "build", 0),
    ("ses_sub", "ses_main", "/home/dev/project", "explore", 0.5),
    (ODD_ID, None, "/home/dev/other", "plan", 10),
    ("ses_empty", None, "/home/dev/empty", None, 20),
    ("ses_orphan", "ses_gone", "/home/dev/orphan", "build", 30),
]


def at(seconds: object) -> object:
    """Seconds after BASE as the milliseconds the database holds; anything else (a wrong type) is kept as it is."""
    return BASE + int(seconds * 1000) if isinstance(seconds, (int, float)) else seconds


def build(path: Path, sessions: list = SESSIONS, messages: list = MESSAGES) -> None:
    db = sqlite3.connect(path)
    db.executescript(SCHEMA)
    for sid, parent, directory, agent, seconds in sessions:
        db.execute("INSERT INTO session_v2 VALUES (?, ?, ?, ?, ?)", (sid, parent, directory, agent, at(seconds)))
    for n, (sid, kind, seq, seconds, data) in enumerate(messages):
        db.execute(
            "INSERT INTO session_message VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"msg_{n}", sid, kind, seq, at(seconds), 0, data),
        )
    db.commit()
    db.close()


class ReadDatabase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db = Path(self._tmp.name) / "opencode.db"
        build(self.db)
        self.runs = opencode.read(self.db, HOME)
        self.main = self.runs[0]

    def test_one_run_per_session_but_not_for_subagents(self) -> None:
        self.assertEqual(
            [run.meta.session for run in self.runs], ["ses_main", "ses_plan____1", "ses_empty", "ses_orphan"]
        )
        self.assertEqual([len(run.calls) for run in self.runs], [19, 1, 0, 1])  # a parentless child is its own run

    def test_meta(self) -> None:
        meta = self.main.meta
        self.assertEqual(meta.harness, "opencode")
        self.assertEqual((meta.start, meta.started), ("/home/dev/project", "2026-02-05T10:00:00.000Z"))
        self.assertEqual(meta.source, str(self.db))
        self.assertEqual(meta.state_dirs, opencode.STATE_DIRS)
        self.assertEqual(meta.siblings, ())
        self.assertEqual(self.runs[1].meta.start, "/home/dev/other")

    def test_modes_are_the_agents_of_the_session_without_the_subagents(self) -> None:
        self.assertEqual(self.main.meta.modes, ("build", "plan"))
        self.assertEqual([run.meta.modes for run in self.runs[1:3]], [("plan",), ()])

    def test_every_tool_maps_to_its_kind_in_order(self) -> None:
        expected = [
            ("glob", "read"),
            ("grep", "read"),
            ("list", "read"),
            ("apply_patch", "write"),
            ("multiedit", "write"),
            ("read", "read"),
            ("edit", "write"),
            ("write", "write"),
            ("shell", "shell"),
            ("bash", "shell"),
            ("read", "read"),  # the subagent's call, by time
            ("webfetch", "fetch"),
            ("websearch", "search"),
            ("task", "other"),
            ("todowrite", "other"),
            ("shell", "shell"),
            ("shell", "shell"),
            ("shell", "shell"),
            ("shell", "shell"),
        ]
        self.assertEqual([(call.tool, call.kind) for call in self.main.calls], expected)
        times = [call.time for call in self.main.calls]
        self.assertEqual(times, sorted(times))

    def test_paths_come_from_file_tools_and_patch_text(self) -> None:
        paths = [call.paths for call in self.main.calls if call.kind in ("read", "write")]
        self.assertEqual(
            paths,
            [
                ("/home/dev/project",),  # glob
                (),  # grep without a folder
                ("/home/dev/project",),
                ("/home/dev/project/new.py", "src/app.py", "src/app2.py", "old.txt"),
                ("src/b.py",),
                ("/home/dev/project/README.md",),
                ("src/app.py",),
                ("/tmp/x",),
                ("/home/dev/.netrc",),
            ],
        )
        self.assertTrue(all(call.paths == () for call in self.main.calls if call.kind not in ("read", "write")))

    def test_shell_command_and_fetch_url(self) -> None:
        commands = [call.command for call in self.main.calls if call.kind == "shell"]
        self.assertEqual(commands, ["pytest -q", "ls", "rm -rf build", "git push", "make", "false"])
        self.assertEqual([call.url for call in self.main.calls if call.url], ["https://example.com/a"])
        search = next(call for call in self.main.calls if call.kind == "search")
        self.assertEqual((search.paths, search.command, search.url), ((), None, None))

    def test_refused_by_error_type_and_by_the_harness_sentence_only(self) -> None:
        refused = [call.command for call in self.main.calls if call.refused]
        self.assertEqual(refused, ["rm -rf build", "git push"])  # a failed command, and an error without type, are not

    def test_subagent_calls_are_marked_and_belong_to_the_parent(self) -> None:
        self.assertEqual([call.paths for call in self.main.calls if call.sub], [("/home/dev/.netrc",)])
        self.assertFalse(any(call.sub for call in self.runs[3].calls))

    def test_time_is_the_items_own_or_the_messages(self) -> None:
        read = next(call for call in self.main.calls if call.paths == ("/home/dev/project/README.md",))
        self.assertEqual(read.time, iso(1.5))
        self.assertEqual(self.main.calls[0].time, iso(0.5))

    def test_user_rows_broken_rows_unknown_sessions_and_unfinished_tools_add_no_call(self) -> None:
        paths = [path for call in self.main.calls for path in call.paths]
        self.assertNotIn("/home/dev/.ssh/id", paths)
        self.assertNotIn("/home/dev/x", [path for run in self.runs for call in run.calls for path in call.paths])
        commands = {call.command for call in self.main.calls}
        self.assertFalse(commands & {"no name", "not a tool"})
        self.assertEqual(len(self.main.calls), 19)

    def test_the_database_is_not_changed_and_no_file_appears(self) -> None:
        folder = Path(self._tmp.name)
        before = (hashlib.sha256(self.db.read_bytes()).hexdigest(), sorted(p.name for p in folder.iterdir()))
        opencode.read(self.db, HOME)
        after = (hashlib.sha256(self.db.read_bytes()).hexdigest(), sorted(p.name for p in folder.iterdir()))
        self.assertEqual(before, after)

    def test_text_that_is_not_utf8_costs_only_its_row(self) -> None:
        db = sqlite3.connect(self.db)
        db.execute(
            "INSERT INTO session_message VALUES ('bad', 'ses_main', 'assistant', 99, ?, 0, CAST(x'7b22ff' AS TEXT))",
            (BASE + 20000,),
        )
        db.commit()
        db.close()
        self.assertEqual([len(run.calls) for run in opencode.read(self.db, HOME)], [19, 1, 0, 1])


class ReadOtherInput(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.folder = Path(self._tmp.name)

    def test_empty_file(self) -> None:
        empty = self.folder / "empty.db"
        empty.write_bytes(b"")
        self.assertEqual(opencode.read(empty, HOME), [])

    def test_not_a_database(self) -> None:
        text, binary = self.folder / "a.db", self.folder / "b.db"
        text.write_text("plain text, not a database\n" * 200, encoding="utf-8")
        binary.write_bytes(bytes(range(256)) * 40)
        self.assertEqual([opencode.read(text, HOME), opencode.read(binary, HOME)], [[], []])

    def test_a_database_that_is_not_opencodes(self) -> None:
        other = self.folder / "other.db"
        db = sqlite3.connect(other)
        db.execute("CREATE TABLE notes (id INTEGER, body TEXT)")
        db.commit()
        db.close()
        self.assertEqual(opencode.read(other, HOME), [])

    def test_missing_file_and_folder(self) -> None:
        self.assertEqual(opencode.read(self.folder / "missing.db", HOME), [])
        self.assertEqual(opencode.read(self.folder, HOME), [])
        self.assertEqual([p.name for p in self.folder.iterdir()], [])  # reading a missing file creates nothing

    def test_database_without_sessions(self) -> None:
        path = self.folder / "none.db"
        build(path, [], [])
        self.assertEqual(opencode.read(path, HOME), [])

    def test_path_with_odd_characters(self) -> None:
        path = self.folder / "my data #1 ?.db"
        build(path)
        self.assertEqual(len(opencode.read(path, HOME)), 4)

    def test_fields_of_the_wrong_type_never_raise(self) -> None:
        path = self.folder / "wrong.db"
        sessions = [
            ("s1", None, None, None, "soon"),
            ("", None, "/x", "build", 0),
            ("s3", "s3", "/home/dev/p", "build", 1),
        ]
        items = [
            tool(5, {"path": "/a"}),
            tool("read", {"path": 5}),
            tool("read", {"path": ["/a"]}),
            tool("shell", {"command": 5}),
            tool("webfetch", {"url": 5}),
            {"type": "tool", "name": "read", "state": "done"},
        ]
        data = [
            json.dumps({"agent": 4, "content": items}),
            json.dumps({"content": "words"}),
            json.dumps({"content": [{"type": "tool", "name": "read", "state": {"input": {"path": "/a"}}, "time": 3}]}),
        ]
        messages = [("s1", "assistant", n, n, d) for n, d in enumerate(data)]
        build(path, sessions, messages)
        (run,) = opencode.read(path, HOME)
        self.assertEqual((run.meta.start, run.meta.started, run.meta.modes), ("", None, ()))
        self.assertEqual(
            [(call.tool, call.kind) for call in run.calls],
            [("read", "read"), ("read", "read"), ("shell", "shell"), ("webfetch", "fetch"), ("read", "read")],
        )
        self.assertEqual([(c.paths, c.command, c.url) for c in run.calls[:4]], [((), None, None)] * 4)
        self.assertEqual(run.calls[4].paths, ("/a",))
        self.assertFalse(any(c.sub or c.refused or c.unsandboxed for c in run.calls))

    def test_session_id_is_safe_as_a_file_name(self) -> None:
        path = self.folder / "ids.db"
        build(path, [("../../etc/x y", None, "/home/dev/p", "build", 0)], [])
        (run,) = opencode.read(path, HOME)
        self.assertEqual(run.meta.session, "______etc_x_y")


class Find(unittest.TestCase):
    def test_finds_the_database(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            data = home / ".local" / "share" / "opencode"
            for name in ("opencode.db-wal", "opencode.db-shm", "opencode.db", "auth-notes.txt"):
                data.mkdir(parents=True, exist_ok=True)
                (data / name).write_text("", encoding="utf-8")
            (home / ".config" / "opencode").mkdir(parents=True)
            (home / ".config" / "opencode" / "opencode.db").write_text("", encoding="utf-8")
            self.assertEqual(opencode.find(home), [data / "opencode.db"])

    def test_home_without_the_harness(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            self.assertEqual(opencode.find(home), [])
            (home / ".local" / "share" / "opencode" / "opencode.db").mkdir(parents=True)  # a folder, not a file
            self.assertEqual(opencode.find(home), [])

    def test_found_database_reads_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".local" / "share" / "opencode").mkdir(parents=True)
            build(home / ".local" / "share" / "opencode" / "opencode.db")
            (found,) = opencode.find(home)
            runs = opencode.read(found, home)
        self.assertEqual([len(run.calls) for run in runs], [19, 1, 0, 1])


class Constants(unittest.TestCase):
    def test_contract(self) -> None:
        self.assertEqual(opencode.NAME, "opencode")
        self.assertIn("~/.local/share/opencode", opencode.STATE_DIRS)
        self.assertIn("~/.config/opencode", opencode.STATE_DIRS)


if __name__ == "__main__":
    unittest.main()
