import json
import unittest

from stickyagents.model import Event, Finding, Record, RunMeta
from stickyagents.report import NOTE, WIDTH, build, build_summary, render, render_summary

SESSION = "0123abcd-4567-89ab-cdef-000000000001"
LONG = "~/Code/" + "a-very-long-folder-name-" * 6 + "end/file.txt"


def record(*events, harness="claude-code", session=SESSION, modes=("default",)):
    meta = RunMeta(harness, session, "~/project", started="2026-01-02T03:04:05Z", modes=modes)
    return Record(meta, list(events))


def call(kind="shell", **fields):
    return Event("call", "Bash", call_kind=kind, **fields)


def touch(target, zone, mode="read"):
    return Event("touch", "Edit" if mode == "write" else "Read", mode=mode, zone=zone, target=target)


def mention(target, zone):
    return Event("touch", "Bash", exact=False, mode="mention", zone=zone, target=target)


def net(target, exact=False):
    return Event("net", "WebFetch" if exact else "Bash", exact=exact, target=target)


def finding(rule, severity, count=1, examples=()):
    return Finding(rule, severity, f"Title of {rule}", f"Advice of {rule}.", count, tuple(examples))


RUN = record(
    call("read"),
    touch("~/Code/other/src/a.py", "home"),
    call("read", sub=True),
    touch("~/Code/other/src/b.py", "home"),
    call("write"),
    touch("~/notes/todo.md", "home", "write"),
    call("write"),
    touch("/tmp/out.txt", "scratch", "write"),
    call("fetch"),
    net("example.org", exact=True),
    call("search"),
    net("web search", exact=True),
    call("shell", unsandboxed=True, refused=False),
    mention("~/.ssh/id_ed25519", "credential"),
    mention("~/Code/other/Makefile", "home"),
    mention(LONG, "home"),
    net("github.com (gh)"),
    net("github.com (gh)"),
    net("git remote"),
    Event("cmd", "Bash", exact=False, target="gh"),
    Event("flag", "Bash", exact=False, target="sudo"),
    call("shell", refused=True),
    call("shell"),
    call("shell"),
    touch("~/project/README.md", "repo"),
    modes=("default", "bypassPermissions"),
)
FINDINGS = [
    finding("C002", "high", 1, ["~/.ssh/id_ed25519"]),
    finding("W001", "high", 4, ["~/notes/todo.md", LONG, "~/a", "~/b"]),
    finding("S002", "medium", 1, ["bypassPermissions"]),
]
INSIDE = record(
    call("read"), touch("~/project/README.md", "repo"), call("shell"), mention("~/project/Makefile", "repo")
)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.data = build(RUN, FINDINGS, [INSIDE, INSIDE])

    def test_same_input_same_dict(self):
        self.assertEqual(self.data, build(RUN, FINDINGS, [INSIDE, INSIDE]))
        self.assertEqual(json.dumps(self.data), json.dumps(build(RUN, FINDINGS, [INSIDE, INSIDE])))

    def test_shape(self):
        keys = ["schema", "run", "limits", "calls", "outside_repo", "network", "findings", "history"]
        self.assertEqual(list(self.data), keys)
        self.assertEqual(self.data["schema"], 1)
        run = {"harness": "claude-code", "session": SESSION, "start": "~/project", "started": "2026-01-02T03:04:05Z"}
        self.assertEqual(self.data["run"], run | {"modes": ["default", "bypassPermissions"]})
        self.assertEqual(self.data["history"], {"runs": 2})

    def test_limits_and_calls(self):
        self.assertEqual(self.data["limits"], {"calls": 10, "shell_calls": 4, "shell_share": 0.4, "note": NOTE})
        kinds = {"read": 2, "write": 2, "shell": 4, "fetch": 1, "search": 1, "other": 0}
        self.assertEqual(self.data["calls"], kinds | {"sub": 1, "refused": 1, "unsandboxed": 1})

    def test_a_refused_call_is_not_counted_as_unsandboxed(self):
        both = record(call("shell", unsandboxed=True, refused=True), call("shell", unsandboxed=True, refused=False))
        data = build(both, [], [])
        self.assertEqual((data["calls"]["unsandboxed"], data["calls"]["refused"]), (1, 1))
        self.assertIn("outside the sandbox 1.", render(data))

    def test_outside_repo_counts_exact_and_mentions_apart(self):
        outside = self.data["outside_repo"]
        self.assertEqual(list(outside), ["credential", "scratch", "home"])
        self.assertEqual(outside["home"]["exact"], {"read": 2, "write": 1})
        self.assertEqual(outside["home"]["mentions"], 2)
        top = [["~/Code/other", 3], ["~/Code/" + "a-very-long-folder-name-" * 6 + "end", 1], ["~/notes/todo.md", 1]]
        self.assertEqual(outside["home"]["top"], top)
        self.assertEqual(
            outside["scratch"], {"exact": {"read": 0, "write": 1}, "mentions": 0, "top": [["/tmp/out.txt", 1]]}
        )
        self.assertEqual(outside["credential"]["top"], [["~/.ssh/id_ed25519", 1]])

    def test_top_folders_are_three_components_and_at_most_five(self):
        events = [touch(f"/usr/lib/python3/{n}.py", "system") for n in range(3)]
        events += [touch(f"/opt/tool{n}/bin/run", "system") for n in range(6)]
        top = build(record(*events), [], [])["outside_repo"]["system"]["top"]
        self.assertEqual(top[0], ["/usr/lib", 3])
        self.assertEqual([name for name, _ in top[1:]], [f"/opt/tool{n}" for n in range(4)])

    def test_network_is_sorted_by_count_then_name(self):
        network = {
            "exact": [["example.org", 1], ["web search", 1]],
            "mentions": [["github.com (gh)", 2], ["git remote", 1]],
        }
        self.assertEqual(self.data["network"], network)

    def test_findings_as_data(self):
        first = self.data["findings"][0]
        self.assertEqual(list(first), ["rule", "severity", "title", "advice", "count", "examples"])
        self.assertEqual(first["examples"], ["~/.ssh/id_ed25519"])
        self.assertEqual(json.loads(json.dumps(self.data)), self.data)


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.text = render(build(RUN, FINDINGS, [INSIDE, INSIDE]))
        self.lines = self.text.splitlines()

    def test_plain_text_within_the_width(self):
        self.assertLessEqual(max(len(line) for line in self.lines), WIDTH)
        self.assertTrue(self.text.isascii())
        self.assertNotIn("\x1b", self.text)

    def test_title_then_limits_first(self):
        self.assertEqual(
            self.lines[0], "stickyagents: claude-code run 0123abcd in ~/project, started 2026-01-02T03:04:05Z"
        )
        self.assertNotIn(SESSION, self.text)
        self.assertTrue(self.lines[1].startswith("10 tool calls, 4 (40%) were shell commands. Targets of shell"))
        self.assertIn("mentions, not proven touches.", " ".join(self.lines[1:3]))

    def test_sections_in_order(self):
        heads = ["Outside the repo", "Network", "Findings", "Compared with 2 earlier runs in this repo."]
        places = [self.lines.index(head) for head in heads]
        self.assertEqual(places, sorted(places))
        self.assertLess(2, places[0])

    def test_table_network_and_findings(self):
        self.assertIn("  zone         exact reads exact writes shell mentions  top folders", self.lines)
        self.assertIn("  scratch                0            1              0  /tmp/out.txt (1)", self.lines)
        self.assertIn("  Fetches and searches: example.org (1), web search (1)", self.lines)
        self.assertIn("  Mentioned in shell: github.com (gh) (2), git remote (1)", self.lines)
        at = self.lines.index("  high      C002  Title of C002 (1x)")
        self.assertEqual(
            self.lines[at + 1 : at + 3], [" " * 18 + "e.g. ~/.ssh/id_ed25519", " " * 18 + "Advice of C002."]
        )
        self.assertIn("Permission modes recorded: default, bypassPermissions.", self.lines)

    def test_at_most_three_examples(self):
        self.assertIn("~/a", self.text)
        self.assertNotIn("~/b", self.text)

    def test_a_run_that_never_left_the_repo(self):
        text = render(build(INSIDE, [], []))
        self.assertIn("\nOutside the repo: no touch recorded.", text)
        self.assertNotIn("top folders", text)
        self.assertIn("\nNetwork: no host or channel recorded.\n", text)
        self.assertIn("\nNo findings.\n", text)
        self.assertTrue(text.endswith("\nNo earlier runs in this repo: nothing is marked as first seen.\n"))
        self.assertTrue(text.splitlines()[1].startswith("2 tool calls, 1 (50%) were shell commands."))

    def test_one_earlier_run_and_an_empty_run(self):
        self.assertIn("Compared with 1 earlier run in this repo.", render(build(INSIDE, [], [INSIDE])))
        self.assertIn("0 tool calls, 0 (0%) were shell commands.", render(build(record(), [], [])))


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.records = [
            RUN,
            record(
                call("shell"), mention("~/.netrc", "credential"), net("github.com (gh)"), harness="pi", session="p1"
            ),
            record(call("read"), touch("~/project/a.py", "repo"), session="c2"),
        ]
        self.findings = {
            f"claude-code/{SESSION}": FINDINGS,
            "pi/p1": [finding("C002", "high", 2), finding("S002", "medium", 5), finding("C001", "critical")],
            "claude-code/c2": [finding("S002", "medium", 1)],
        }
        self.data = build_summary(self.records, self.findings)

    def test_totals(self):
        self.assertEqual(self.data["schema"], 1)
        self.assertEqual(self.data["runs"], 3)
        self.assertEqual(self.data["harnesses"], {"claude-code": 2, "pi": 1})
        self.assertEqual((self.data["calls"], self.data["shell_calls"], self.data["shell_share"]), (12, 5, 0.42))

    def test_zones_count_runs_with_exact_and_mentions_apart(self):
        zones = self.data["zones"]
        self.assertEqual(list(zones), ["credential", "sibling", "scratch", "agent-state", "home", "system"])
        none = {"runs": 0, "share": 0.0}
        self.assertEqual(zones["credential"], {"exact": none, "mentions": {"runs": 2, "share": 0.67}})
        self.assertEqual(zones["home"], {"exact": {"runs": 1, "share": 0.33}, "mentions": {"runs": 1, "share": 0.33}})
        self.assertEqual(zones["system"], {"exact": none, "mentions": none})

    def test_network_by_number_of_runs(self):
        hosts = [["github.com (gh)", 2], ["example.org", 1], ["git remote", 1], ["web search", 1]]
        self.assertEqual(self.data["network"], hosts)
        many = [record(*(net(f"host{n}.example") for n in range(12)), session="m1")]
        self.assertEqual(len(build_summary(many, {})["network"]), 10)

    def test_findings_by_severity_then_runs_and_the_top_three(self):
        rows = [(f["rule"], f["severity"], f["runs"], f["count"]) for f in self.data["findings"]]
        expected = [
            ("C001", "critical", 1, 1),
            ("C002", "high", 2, 3),
            ("W001", "high", 1, 4),
            ("S002", "medium", 3, 7),
        ]
        self.assertEqual(rows, expected)
        self.assertEqual(self.data["top"], ["S002", "C002", "W001"])
        self.assertEqual(self.data["findings"][0]["advice"], "Advice of C001.")
        self.assertNotIn("examples", self.data["findings"][0])

    def test_same_input_same_dict_and_json(self):
        again = build_summary(list(self.records), dict(self.findings))
        self.assertEqual(json.dumps(self.data), json.dumps(again))
        self.assertEqual(json.loads(json.dumps(self.data)), self.data)

    def test_render_summary(self):
        text = render_summary(self.data)
        lines = text.splitlines()
        self.assertLessEqual(max(len(line) for line in lines), WIDTH)
        self.assertTrue(text.isascii())
        self.assertEqual(lines[0], "stickyagents: 3 runs (claude-code 2, pi 1)")
        self.assertTrue(lines[1].startswith("12 tool calls, 5 (42%) were shell commands. Targets of shell"))
        heads = ["Outside the repo: runs with at least one touch", "Findings, the most frequent first", "All findings"]
        places = [lines.index(head) for head in heads]
        self.assertEqual(places, sorted(places))
        self.assertIn("  credential               0 (0%)          2 (67%)", lines)
        self.assertIn(
            "Network, by number of runs: github.com (gh) (2), example.org (1), git remote (1), web search (1)", lines
        )
        first = lines[places[1] + 1 : places[1] + 4]
        self.assertEqual(first[0], "  1. S002  Title of S002 (3 of 3 runs)")
        self.assertEqual([line.split()[1] for line in first], ["S002", "C002", "W001"])
        at = lines.index("  critical  C001  Title of C001 (1 run, 1x)")
        self.assertEqual(lines[at + 1], " " * 18 + "Advice of C001.")

    def test_no_runs_and_no_findings(self):
        data = build_summary([], {})
        self.assertEqual(
            (data["runs"], data["calls"], data["shell_share"], data["findings"], data["top"]), (0, 0, 0.0, [], [])
        )
        text = render_summary(data)
        self.assertTrue(text.startswith("stickyagents: 0 runs\n0 tool calls, 0 (0%) were shell commands."))
        self.assertTrue(text.endswith("\nNo findings.\n"))


if __name__ == "__main__":
    unittest.main()
