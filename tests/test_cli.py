import contextlib
import io
import json
import os
import shutil
import sqlite3
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stickyagents import cli, store
from stickyagents.model import Record, RunMeta

FIXTURES = Path(__file__).parent / "fixtures" / "claude_code" / "projects"
SESSION = "0a1b2c3d-1111-4222-8333-444455556666"
MARKER = "sk-marker-4f9a1c"


def run(argv, home, folder=None):
    """main() with its output captured: (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(argv, home=home, folder=folder)
    return code, out.getvalue(), err.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        shutil.copytree(FIXTURES, self.home / ".claude" / "projects")
        patch = mock.patch.dict(os.environ, {"STICKYAGENTS_HOME": str(Path(self.temp.name) / "state")})
        patch.start()
        self.addCleanup(patch.stop)

    def test_first_run_scans_stores_and_summarises(self):
        code, out, err = run([], self.home)
        self.assertEqual(code, 0)
        self.assertIn("claude-code", out)
        self.assertRegex(err, r"Scanned \d+ session sources .* 1 runs recorded")
        self.assertEqual([r.meta.session for r in store.load_all()], [SESSION])

    def test_second_scan_reads_nothing_again(self):
        first = cli.scan(self.home)
        second = cli.scan(self.home)
        self.assertEqual(first["runs"], 1)
        self.assertEqual(second["runs"], 0)
        self.assertEqual(second["unchanged"], second["sources"])

    def test_report_for_the_folder_a_run_started_in(self):
        code, out, _ = run(["report"], self.home, folder=Path("/home/dev/project/src"))
        self.assertEqual(code, 0)
        self.assertIn("shell commands", out.splitlines()[1])

    def test_report_as_data_and_by_session(self):
        code, out, _ = run(["report", "--session", SESSION[:8], "--json"], self.home, folder=Path("/"))
        self.assertEqual(code, 0)
        data = json.loads(out)
        self.assertEqual(data["schema"], 1)
        self.assertEqual(data["run"]["session"], SESSION)

    def test_report_is_the_same_twice(self):
        first = run(["report", "--session", SESSION], self.home)[1]
        self.assertEqual(first, run(["report", "--session", SESSION], self.home)[1])

    def test_report_without_a_matching_run(self):
        code, out, err = run(["report"], self.home, folder=Path("/somewhere/else"))
        self.assertEqual((code, out), (1, ""))
        self.assertIn("No record of a run", err)

    def test_summary_as_data(self):
        code, out, _ = run(["summary", "--json"], self.home)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["runs"], 1)

    def test_nothing_on_this_machine(self):
        code, _, err = run([], Path(self.temp.name) / "empty-home")
        self.assertEqual(code, 1)
        self.assertIn("No sessions found", err)

    def test_harnesses(self):
        code, out, _ = run(["harnesses"], self.home)
        self.assertEqual(code, 0)
        self.assertEqual([line.split(":")[0] for line in out.splitlines()], ["claude-code", "pi", "opencode"])

    def test_an_unreadable_source_is_counted_not_fatal(self):
        with mock.patch("stickyagents.readers.claude_code.read", side_effect=RuntimeError("boom")):
            code, _, err = run([], self.home)
        self.assertEqual(code, 1)
        self.assertIn("could not be read", err)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.state = Path(self.temp.name) / "state"
        patch = mock.patch.dict(os.environ, {"STICKYAGENTS_HOME": str(self.state)})
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(os.umask, os.umask(0o022))

    def project(self) -> Path:
        folder = self.home / ".claude" / "projects" / "-home-dev-project"
        folder.mkdir(parents=True, exist_ok=True)
        return folder

    def test_a_source_without_a_readable_session_is_reported(self):
        shutil.copy(FIXTURES / "-home-dev-project" / f"{SESSION}.jsonl", self.project())
        (self.project() / "broken.jsonl").write_text("{{{ not json\n")
        code, _, err = run([], self.home)
        self.assertEqual(code, 0)
        self.assertIn("Scanned 2 session sources (0 unchanged, 1 without a readable session); 1 runs recorded.", err)
        err = run([], self.home)[2]  # nothing changed since: the zero parts are left out
        self.assertIn("Scanned 2 session sources (2 unchanged); 0 runs recorded.", err)

    def test_the_counts(self):
        shutil.copy(FIXTURES / "-home-dev-project" / f"{SESSION}.jsonl", self.project())
        (self.project() / "broken.jsonl").write_text("{{{ not json\n")
        counts = cli.scan(self.home)
        self.assertEqual((counts["sources"], counts["runs"], counts["no_session"], counts["unreadable"]), (2, 1, 1, 0))

    def test_what_a_scan_creates_is_private_also_when_it_existed(self):
        shutil.copy(FIXTURES / "-home-dev-project" / f"{SESSION}.jsonl", self.project())
        (self.state / "runs" / "claude-code").mkdir(parents=True)
        for folder in (self.state, self.state / "runs", self.state / "runs" / "claude-code"):
            folder.chmod(0o755)
        cli.scan(self.home)
        for folder in (self.state, self.state / "runs", self.state / "runs" / "claude-code"):
            self.assertEqual(stat.S_IMODE(folder.stat().st_mode), 0o700, folder)
        self.assertEqual(stat.S_IMODE((self.state / "sources.json").stat().st_mode), 0o600)
        self.assertEqual([p.name for p in self.state.iterdir() if p.name.startswith(".tmp-")], [])
        self.assertIsInstance(json.loads((self.state / "sources.json").read_text()), dict)

    def test_sources_json_is_written_private_even_without_any_source(self):
        cli.scan(self.home)
        self.assertEqual(stat.S_IMODE(self.state.stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE((self.state / "sources.json").stat().st_mode), 0o600)

    def test_a_database_in_wal_mode_is_unchanged_on_the_second_scan(self):
        """Reading it read-only creates and touches -shm; that is no change of the source."""
        folder = self.home / ".local" / "share" / "opencode"
        folder.mkdir(parents=True)
        message = {
            "agent": "build",
            "content": [
                {"type": "tool", "name": "read", "state": {"status": "completed", "input": {"path": "/etc/hosts"}}}
            ],
        }
        db = sqlite3.connect(folder / "opencode.db")
        self.assertEqual(db.execute("PRAGMA journal_mode = WAL").fetchone()[0], "wal")
        db.executescript(
            "CREATE TABLE session_v2 "
            "(id TEXT PRIMARY KEY, parent_id TEXT, directory TEXT, agent TEXT, time_created INTEGER);"
            "CREATE TABLE session_message (id TEXT, session_id TEXT, type TEXT, seq INTEGER, time_created INTEGER, "
            "time_updated INTEGER, data TEXT);"
        )
        db.execute("INSERT INTO session_v2 VALUES ('s1', NULL, '/home/dev/project', 'build', 1770000000000)")
        db.execute(
            "INSERT INTO session_message VALUES ('m1', 's1', 'assistant', 1, 1770000001000, 1770000001000, ?)",
            (json.dumps(message),),
        )
        db.commit()
        db.close()  # the last connection leaves no -wal and no -shm; a read-only open makes them again
        first, second = cli.scan(self.home), cli.scan(self.home)
        self.assertEqual((first["runs"], first["unchanged"]), (1, 0))
        self.assertEqual((second["runs"], second["unchanged"]), (0, 1))

    def test_the_stamp_follows_the_source_and_its_log_but_not_shm(self):
        source = self.home / "x.db"
        self.home.mkdir(parents=True)
        source.write_text("a")
        first = cli._stamp(source)
        self.assertIsInstance(first, list)
        (self.home / "x.db-shm").write_text("shm")
        self.assertEqual(cli._stamp(source), first)
        (self.home / "x.db-wal").write_text("wal")
        self.assertNotEqual(cli._stamp(source), first)
        self.assertEqual(json.loads(json.dumps(cli._stamp(source))), cli._stamp(source))


class EmptyStartTest(unittest.TestCase):
    def record(self, start, started="2026-01-01T00:00:00.000Z", siblings=()):
        return Record(RunMeta("h", "s", start, started, siblings=tuple(siblings)))

    def test_a_record_without_a_start_matches_no_folder(self):
        self.assertIsNone(cli.pick([self.record("")], None, "/home/dev/project"))
        self.assertIsNone(cli.pick([self.record("")], None, "~/project"))
        found = self.record("~/project")
        self.assertIs(cli.pick([self.record(""), found, self.record("")], None, "~/project/src"), found)

    def test_a_record_without_a_start_is_the_same_repo_as_nothing(self):
        empty, other = self.record(""), self.record("~/project", siblings=("",))
        self.assertFalse(cli.same_repo(empty, empty))
        self.assertFalse(cli.same_repo(empty, other))
        self.assertFalse(cli.same_repo(other, empty))
        self.assertTrue(cli.same_repo(other, self.record("~/project")))
        self.assertTrue(cli.same_repo(other, self.record("~/wt", siblings=("~/project",))))
        self.assertEqual(cli.history(self.record("~/p", "2026-01-02T00:00:00.000Z"), [empty]), [])


class NoValuesTest(unittest.TestCase):
    """SC-004: a value planted in a command, a file, a result and a URL reaches no record and no report."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name) / "home"
        self.state = Path(self.temp.name) / "state"
        project = self.home / ".claude" / "projects" / "-home-dev-project"
        project.mkdir(parents=True)
        home = str(self.home)
        common = {"cwd": f"{home}/project", "sessionId": "s-marker", "isSidechain": False}

        def said(kind, stamp, content):
            return {"type": kind, "timestamp": stamp, "message": {"role": kind, "content": content}, **common}

        def use(ident, name, **given):
            return {"type": "tool_use", "id": ident, "name": name, "input": given}

        lines = [
            said("user", "2026-02-01T09:00:00.000Z", f"use the key {MARKER}"),
            said(
                "assistant",
                "2026-02-01T09:00:01.000Z",
                [
                    use(
                        "t1",
                        "Bash",
                        command=f"TOKEN={MARKER} curl -H 'Authorization: Bearer {MARKER}' https://example.com/x",
                    ),
                    use("t2", "Write", file_path=f"{home}/.bashrc", content=f"export KEY={MARKER}\n"),
                    use("t3", "WebFetch", url=f"https://example.org/search?token={MARKER}", prompt=MARKER),
                    use("t4", "Read", file_path=f"{home}/.ssh/id_ed25519"),
                ],
            ),
            said(
                "user",
                "2026-02-01T09:00:02.000Z",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": "t4",
                        "content": f"-----BEGIN KEY----- {MARKER}",
                        "is_error": False,
                    }
                ],
            ),
        ]
        (project / "s-marker.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n")
        patch = mock.patch.dict(os.environ, {"STICKYAGENTS_HOME": str(self.state)})
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_marker_is_nowhere(self):
        shown = ""
        for argv in (
            [],
            ["summary", "--json"],
            ["report", "--session", "s-marker"],
            ["report", "--session", "s-marker", "--json"],
        ):
            code, out, err = run(argv, self.home)
            self.assertEqual(code, 0)
            shown += out + err
        stored = "".join(p.read_text() for p in self.state.rglob("*") if p.is_file())
        self.assertNotIn(MARKER, shown)
        self.assertNotIn(MARKER, stored)
        self.assertIn("~/.ssh/id_ed25519", shown)  # the path is reported, its content is not
        self.assertIn("example.org", shown)
        self.assertNotIn(str(self.home), shown + stored)  # the home folder is shown as ~


if __name__ == "__main__":
    unittest.main()
