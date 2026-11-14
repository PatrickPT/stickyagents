import unittest
from pathlib import Path

from stickyagents.model import SEVERITIES, Event, Record, RunMeta
from stickyagents.rules import NO_PROMPT_MODES, RULES, evaluate


def record(*events, modes=("default",), session="s1"):
    return Record(RunMeta("claude-code", session, "~/project", modes=modes), list(events))


def call(kind="shell", **fields):
    return Event("call", "Bash", call_kind=kind, **fields)


def touch(target, zone, mode="read"):
    return Event("touch", "Edit" if mode == "write" else "Read", mode=mode, zone=zone, target=target)


def mention(target, zone):
    return Event("touch", "Bash", exact=False, mode="mention", zone=zone, target=target)


def net(target, exact=False):
    return Event("net", "WebFetch" if exact else "Bash", exact=exact, target=target)


def flag(name):
    return Event("flag", "Bash", exact=False, target=name)


def ids(findings):
    return [f.rule for f in findings]


CLEAN = record(
    call("read"),
    touch("~/project/README.md", "repo"),
    call("write"),
    touch("~/project/src/main.py", "repo", "write"),
    call("shell", unsandboxed=False, refused=False),
    mention("~/project/Makefile", "repo"),
    Event("cmd", "Bash", exact=False, target="make"),
)
EARLIER = [record(touch("~/project/README.md", "repo"), session="s0")]

# One minimal record per rule: the rule's id, the record, and the examples the finding must show.
CASES = {
    "C001": (record(touch("~/.ssh/id_ed25519", "credential")), ("~/.ssh/id_ed25519",)),
    "C002": (record(mention("~/.aws/credentials", "credential")), ("~/.aws/credentials",)),
    "W001": (record(touch("~/notes/todo.md", "home", "write")), ("~/notes/todo.md",)),
    "W002": (record(touch("~/.bashrc", "home", "write")), ("~/.bashrc",)),
    "W003": (record(mention("/etc/cron.d/job", "system")), ("/etc/cron.d/job",)),
    "W004": (record(touch("~/.claude/settings.json", "agent-state", "write")), ("~/.claude/settings.json",)),
    "S001": (record(call("shell", unsandboxed=True, refused=False)), ("Bash",)),
    "S002": (record(modes=("default", "bypassPermissions")), ("bypassPermissions",)),
    "S003": (record(flag("sudo")), ("sudo",)),
    "S004": (record(flag("pipe-to-shell")), ("pipe-to-shell",)),
    "G001": (record(flag("force-push")), ("force-push",)),
    "G002": (record(flag("push-main")), ("push-main",)),
    "H001": (record(mention("/tmp/build.log", "scratch")), ("scratch",)),
    "H002": (record(net("example.org", exact=True)), ("example.org",)),
    "H003": (record(mention("~/.netrc", "credential")), ("~/.netrc",)),
}


class TableTest(unittest.TestCase):
    def test_every_rule_has_a_case(self):
        self.assertEqual(sorted(CASES), sorted(rule.id for rule in RULES))

    def test_docs_table_matches_rules(self):
        doc = (Path(__file__).parent.parent / "docs" / "rules.md").read_text(encoding="utf-8")
        rows = [
            tuple(part.strip() for part in line.strip("|").split("|"))
            for line in doc.splitlines()
            if line.startswith("| ") and not line.startswith("| Id |") and not line.startswith("|---")
        ]
        self.assertEqual(rows, [(r.id, r.severity, r.title, r.advice) for r in RULES])

    def test_rules_are_well_formed(self):
        self.assertEqual(len({rule.id for rule in RULES}), len(RULES))
        for rule in RULES:
            with self.subTest(rule.id):
                self.assertIn(rule.severity, SEVERITIES)
                self.assertTrue(rule.title and rule.advice.endswith("."))
                self.assertNotIn("!", rule.title + rule.advice)

    def test_each_rule_fires_on_its_minimal_record(self):
        for rule_id, (rec, examples) in CASES.items():
            with self.subTest(rule_id):
                found = {f.rule: f for f in evaluate(rec, EARLIER)}
                self.assertIn(rule_id, found)
                self.assertEqual(found[rule_id].examples, examples)
                self.assertEqual(found[rule_id].count, 1)

    def test_a_clean_run_has_no_findings(self):
        self.assertEqual(evaluate(CLEAN, []), [])
        self.assertEqual(evaluate(CLEAN, EARLIER), [])


class RuleTest(unittest.TestCase):
    def test_credential_exact_and_mention_are_apart(self):
        self.assertEqual(ids(evaluate(record(touch("~/.ssh/id_ed25519", "credential")), [])), ["C001"])
        self.assertEqual(ids(evaluate(record(mention("~/.ssh/id_ed25519", "credential")), [])), ["C002"])

    def test_writes_to_scratch_agent_state_and_siblings_are_no_finding(self):
        rec = record(
            touch("/tmp/out.txt", "scratch", "write"),
            touch("~/.agent/state.json", "agent-state", "write"),
            touch("~/project-wt/a.py", "sibling", "write"),
            touch("~/notes/todo.md", "home", "read"),
        )
        self.assertEqual(evaluate(rec, []), [])

    def test_startup_files(self):
        named = ("~/.zshrc", "~/.ssh/authorized_keys", "~/.config/systemd/user/a.service", "/etc/crontab")
        other = ("~/.bashrc.bak", "~/.config/systemd-notes/a", "~/.config/fish/functions/a.fish", "/etc/hosts")
        for target in named:
            with self.subTest(target):
                self.assertIn("W002", ids(evaluate(record(touch(target, "home", "write")), [])))
                self.assertIn("W003", ids(evaluate(record(mention(target, "home")), [])))
        for target in other:
            with self.subTest(target):
                found = ids(evaluate(record(touch(target, "home", "write"), mention(target, "home")), []))
                self.assertEqual(found, ["W001"])

    def test_more_startup_files(self):
        named = ("~/.zshenv", "~/.bash_login", "~/.ssh/config", "/etc/profile", "/etc/profile.d/x.sh", "/etc/profile.d")
        other = ("/etc/profiled", "/etc/profile.bak", "~/.zshenv.d/a", "/etc/profiles")
        for target in named:
            with self.subTest(target):
                self.assertIn("W002", ids(evaluate(record(touch(target, "home", "write")), [])))
                self.assertIn("W003", ids(evaluate(record(mention(target, "home")), [])))
        for target in other:
            with self.subTest(target):
                found = ids(evaluate(record(touch(target, "system", "write"), mention(target, "system")), []))
                self.assertEqual(found, ["W001"])

    def test_the_harness_s_own_settings(self):
        for target in (
            "~/.claude/settings.json",
            "~/.claude/settings.local.json",
            "~/.codex/config.toml",
            "~/.pi/agent/config.json",
            "~/.config/opencode/config.yaml",
            "~/.gemini/hooks.json",
            "~/.claude/hooks/pre-tool.sh",
            "~/.codex/hooks/a/b.py",
            "~/.claude/CLAUDE.md",
            "~/.pi/agent/AGENTS.md",
            "~/.claude/skills/x/SKILL.md",
            "~/.claude/agents/x.md",
            "~/.claude/commands/x.md",
        ):
            with self.subTest(target):
                self.assertEqual(ids(evaluate(record(touch(target, "agent-state", "write")), [])), ["W004"])
        for event in (
            touch("~/.claude/settings.json", "agent-state", "read"),  # a read
            mention("~/.claude/settings.json", "agent-state"),  # shell text
            touch("~/project/settings.json", "repo", "write"),  # not the harness's
            touch("~/project/CLAUDE.md", "repo", "write"),  # in the repo, not agent-state
            touch("~/.claude/notes.md", "agent-state", "write"),
            touch("~/.claude/hooks", "agent-state", "write"),  # a file called hooks, not a folder
            touch("~/.claude/settings.json.bak", "agent-state", "write"),
        ):
            with self.subTest(event.target):
                self.assertEqual(evaluate(record(event), []), [])

    def test_dontask_is_not_a_missing_brake(self):
        self.assertNotIn("dontAsk", NO_PROMPT_MODES)
        self.assertEqual(evaluate(record(modes=("dontAsk",)), []), [])

    def test_reading_a_startup_file_with_a_file_tool_is_no_finding(self):
        self.assertEqual(evaluate(record(touch("~/.bashrc", "home", "read")), []), [])

    def test_a_refused_unsandboxed_call_did_not_run(self):
        self.assertEqual(evaluate(record(call("shell", unsandboxed=True, refused=True)), []), [])

    def test_every_no_prompt_mode_counts(self):
        for mode in NO_PROMPT_MODES:
            with self.subTest(mode):
                self.assertEqual(ids(evaluate(record(modes=(mode,)), [])), ["S002"])
        self.assertEqual(evaluate(record(modes=("default", "acceptEdits", "plan")), []), [])

    def test_count_is_per_occurrence_and_examples_are_five_distinct_in_order(self):
        paths = [f"~/notes/{n}.md" for n in (3, 1, 3, 2, 6, 5, 4)]
        (finding,) = evaluate(record(*(touch(p, "home", "write") for p in paths)), [])
        self.assertEqual(finding.count, 7)
        self.assertEqual(finding.examples, tuple(f"~/notes/{n}.md" for n in (3, 1, 2, 6, 5)))


class HistoryTest(unittest.TestCase):
    new = record(mention("~/.netrc", "credential"), mention("/tmp/a", "scratch"), net("example.org"))

    def test_nothing_is_first_seen_without_history(self):
        self.assertEqual(ids(evaluate(self.new, [])), ["C002"])

    def test_first_seen_against_earlier_runs(self):
        found = {f.rule: f for f in evaluate(self.new, EARLIER)}
        self.assertEqual(sorted(found), ["C002", "H001", "H002", "H003"])
        self.assertEqual(found["H001"].examples, ("credential", "scratch"))
        self.assertEqual(found["H002"].examples, ("example.org",))
        self.assertEqual(found["H003"].examples, ("~/.netrc",))

    def test_seen_before_is_not_marked(self):
        earlier = [*EARLIER, record(*self.new.events, session="s0b")]
        self.assertEqual(ids(evaluate(self.new, earlier)), ["C002"])

    def test_a_known_zone_with_a_new_credential_path(self):
        earlier = [record(mention("~/.aws/credentials", "credential"), session="s0")]
        rec = record(mention("~/.netrc", "credential"), mention("~/.aws/credentials", "credential"))
        found = {f.rule: f for f in evaluate(rec, earlier)}
        self.assertEqual(sorted(found), ["C002", "H003"])
        self.assertEqual(found["H003"].examples, ("~/.netrc",))


class OrderTest(unittest.TestCase):
    def test_most_severe_first_then_rule_id(self):
        rec = record(
            flag("push-main"),
            flag("force-push"),
            flag("sudo"),
            mention("~/.netrc", "credential"),
            touch("~/.bashrc", "home", "write"),
            touch("~/.ssh/id_ed25519", "credential"),
            net("example.org"),
            modes=("yolo",),
        )
        findings = evaluate(rec, EARLIER)
        expected = ["C001", "W002", "C002", "H003", "S003", "W001", "G001", "G002", "H001", "H002", "S002"]
        self.assertEqual(ids(findings), expected)
        self.assertEqual(ids(evaluate(rec, EARLIER)), expected)


if __name__ == "__main__":
    unittest.main()
