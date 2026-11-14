import tempfile
import unittest
from pathlib import Path

from stickyagents.model import RunMeta
from stickyagents.zones import classify, find_siblings, tilde

HOME = "/home/dev"
META = RunMeta(
    harness="h",
    session="s",
    start="/home/dev/project",
    siblings=("/home/dev/project-wt", "~/other-wt"),
    state_dirs=("~/.claude", "~/.cache/tool"),
)


def zone(path, meta=META):
    found = classify(path, meta, HOME)
    return found[0] if found else None


class ClassifyTest(unittest.TestCase):
    def test_credentials(self):
        for path in (
            "~/.ssh/id_rsa",
            "~/.ssh/config",
            "~/.gnupg/pubring.kbx",
            "~/.aws/credentials",
            "~/.azure/x",
            "~/.kube/config",
            "~/.docker/config.json",
            "~/.netrc",
            "~/.npmrc",
            "~/.pypirc",
            "~/.git-credentials",
            "~/.config/gh/hosts.yml",
            "~/.config/gcloud/x",
            "~/.config/sops/age/keys.txt",
            "~/.config/age/key",
            "/srv/app/server.pem",
            "/srv/app/tls.key",
            "/srv/a.p12",
            "/srv/a.pfx",
            "/srv/vault.kdbx",
            "/srv/id_ed25519",
            "/srv/id_ecdsa_old",
            "/srv/id_rsa.bak",
            "/home/dev/project/.env",
            "/home/dev/project/.env.local",
            "/etc/shadow",
            "/etc/sudoers",
            "/etc/sudoers.d/90-x",
            "/proc/1234/environ",
            "~/.claude/.credentials.json",
            "~/.codex/auth.json",
            "~/.gemini/oauth_creds.json",
            "~/.local/share/opencode/auth.json",
            "~/.pi/agent/auth.json",
        ):
            with self.subTest(path=path):
                self.assertEqual(zone(path), "credential")

    def test_credentials_of_any_home_and_by_name(self):
        for path in (
            "/root/.aws/credentials",
            "/home/other/.ssh/authorized_keys",
            "/home/other/.config/gh/hosts.yml",
            "/Users/bob/.kube/config",
            "/Users/bob/.codex/auth.json",
            "/root/.pi/agent/auth.json",
            "~/.cargo/credentials",
            "~/.cargo/credentials.toml",
            "/root/.cargo/credentials.toml",
            "~/.bash_history",
            "~/.zsh_history",
            "/home/other/.bash_history",
            "/etc/ssl/private/site",
            "/etc/ssl/private/nested/site.crt",
            "/srv/app/.npmrc",
            "/srv/app/.pypirc",
            "/srv/app/.netrc",
            "/home/dev/project/.npmrc",
            "/home/dev/project/.env.production",
            "/home/dev/project/.ENV",
        ):
            with self.subTest(path=path):
                self.assertEqual(zone(path), "credential")

    def test_env_templates_and_other_look_alikes_are_no_credentials(self):
        for path in ("/home/dev/project/.env.example", ".env.sample", "sub/.env.template", "a/.env.dist"):
            with self.subTest(path=path):
                self.assertEqual(zone(path), "repo")
        for path in (
            "/home/dev/project/.npmrc.bak",
            "/home/dev/project/.cargo/credentials",  # a home-relative place, but not in the home
            "/home/other/project/.ssh/x",
            "/home/other/.sshx/x",
            "/etc/ssl/certs/ca.crt",
            "/etc/ssl/privateer",
            "/rootless/.aws/credentials",
        ):
            with self.subTest(path=path):
                self.assertNotEqual(zone(path), "credential")

    def test_not_credentials(self):
        self.assertEqual(zone("~/.ssh/id_rsa.pub"), "home")
        self.assertEqual(zone("/home/dev/project/key.pub"), "repo")
        self.assertEqual(zone("/home/dev/project/.envrc"), "repo")
        self.assertEqual(zone("/home/dev/project/environment.md"), "repo")
        self.assertEqual(zone("/home/dev/project/auth.json"), "repo")  # only harness folders keep logins there
        self.assertEqual(zone("/etc/shadowy"), "system")
        self.assertEqual(zone("/proc/1234/status"), "system")
        self.assertEqual(zone("~/.local/share/opencode/log.txt"), "home")

    def test_other_zones(self):
        cases = {
            "/home/dev/project": "repo",
            "/home/dev/project/src/a.py": "repo",
            "/home/dev/project-wt/a.py": "sibling",
            "/home/dev/other-wt": "sibling",
            "~/other-wt/x": "sibling",
            "/tmp/x": "scratch",
            "/var/tmp/x": "scratch",
            "/dev/shm/x": "scratch",
            "/private/tmp/x": "scratch",
            "/var/folders/ab/cd": "scratch",
            "~/.claude/projects/x.jsonl": "agent-state",
            "~/.cache/tool/y": "agent-state",
            "~/notes.md": "home",
            "/home/dev": "home",
            "/usr/bin/env": "system",
            "/etc/hosts": "system",
            "/home/other/x": "system",
        }
        for path, expected in cases.items():
            with self.subTest(path=path):
                self.assertEqual(zone(path), expected)

    def test_prefix_trap(self):
        self.assertEqual(zone("/home/dev/project-other/a.py"), "home")
        self.assertEqual(zone("/home/dev/projects"), "home")
        self.assertEqual(zone("/tmpfoo/x"), "system")
        self.assertEqual(zone("/home/devious/x"), "system")

    def test_first_match_wins(self):
        self.assertEqual(zone("/home/dev/project/.ssh/id_rsa"), "credential")
        meta = RunMeta(harness="h", session="s", start="/home/dev/project", siblings=("/tmp/wt",))
        self.assertEqual(zone("/tmp/wt/a", meta), "sibling")  # sibling before scratch
        meta = RunMeta(harness="h", session="s", start="/home/dev/.claude/x", state_dirs=("~/.claude",))
        self.assertEqual(zone("/home/dev/.claude/x/a", meta), "repo")  # repo before agent-state

    def test_shown_path(self):
        self.assertEqual(classify("/home/dev/project/a.py", META, HOME), ("repo", "~/project/a.py"))
        self.assertEqual(classify("~/notes.md", META, HOME), ("home", "~/notes.md"))
        self.assertEqual(classify("/etc/hosts", META, HOME), ("system", "/etc/hosts"))
        self.assertEqual(classify("/home/dev", META, HOME), ("home", "~"))
        self.assertEqual(classify("/home/dev/project/a.py", META, "/home/dev/"), ("repo", "~/project/a.py"))

    def test_relative_paths(self):
        self.assertEqual(classify("src/a.py", META, HOME), ("repo", "~/project/src/a.py"))
        self.assertEqual(classify("./a.py", META, HOME), ("repo", "~/project/a.py"))
        self.assertEqual(classify("../project-wt/a.py", META, HOME), ("sibling", "~/project-wt/a.py"))
        self.assertEqual(classify("../.ssh/config", META, HOME), ("credential", "~/.ssh/config"))
        self.assertEqual(classify("a/../../x", META, HOME), ("home", "~/x"))

    def test_start_in_tilde_form(self):
        meta = RunMeta(harness="h", session="s", start="~/project", siblings=("~/wt",))
        self.assertEqual(classify("a.py", meta, HOME), ("repo", "~/project/a.py"))
        self.assertEqual(zone("/home/dev/project/b", meta), "repo")
        self.assertEqual(zone("/home/dev/wt/b", meta), "sibling")

    def test_normalises_without_touching_the_disk(self):
        self.assertEqual(classify("/home/dev//project/./x/../a.py", META, HOME), ("repo", "~/project/a.py"))
        self.assertEqual(classify("//etc/hosts", META, HOME), ("system", "/etc/hosts"))
        self.assertEqual(classify("/home/dev/project/../../../../etc/hosts", META, HOME), ("system", "/etc/hosts"))

    def test_no_touch(self):
        for path in ("/dev/null", "/dev/tty", "/dev/stdout", "", "   "):
            with self.subTest(path=path):
                self.assertIsNone(classify(path, META, HOME))

    def test_relative_without_start_is_no_touch(self):
        self.assertIsNone(classify("a.py", RunMeta(harness="h", session="s", start=""), HOME))


class TildeTest(unittest.TestCase):
    def test_tilde(self):
        self.assertEqual(tilde("/home/dev/a", HOME), "~/a")
        self.assertEqual(tilde("/home/dev", HOME), "~")
        self.assertEqual(tilde("/home/devious/a", HOME), "/home/devious/a")
        self.assertEqual(tilde("/etc/a", HOME), "/etc/a")
        self.assertEqual(tilde("/a", ""), "/a")


class FindSiblingsTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()

    def build(self):
        """A main repo with two worktrees; returns (main, wt_a, wt_b)."""
        main, a, b = self.root / "main", self.root / "wt-a", self.root / "wt-b"
        for name, folder in (("a", a), ("b", b)):
            admin = main / ".git" / "worktrees" / name
            admin.mkdir(parents=True)
            (admin / "gitdir").write_text(f"{folder}/.git\n")
            folder.mkdir()
            (folder / ".git").write_text(f"gitdir: {admin}\n")
        return main, a, b

    def test_from_a_worktree(self):
        main, a, b = self.build()
        self.assertEqual(find_siblings(str(a)), tuple(sorted((str(main), str(b)))))

    def test_from_the_main_folder(self):
        main, a, b = self.build()
        self.assertEqual(find_siblings(str(main)), (str(a), str(b)))

    def test_repo_without_worktrees(self):
        (self.root / "solo" / ".git").mkdir(parents=True)
        self.assertEqual(find_siblings(str(self.root / "solo")), ())

    def test_no_git(self):
        (self.root / "plain").mkdir()
        self.assertEqual(find_siblings(str(self.root / "plain")), ())

    def test_errors_give_nothing(self):
        broken = self.root / "broken"
        broken.mkdir()
        (broken / ".git").write_text("not a pointer")
        self.assertEqual(find_siblings(str(broken)), ())
        self.assertEqual(find_siblings(str(self.root / "missing")), ())
        self.assertEqual(find_siblings(""), ())

    def test_submodule_is_no_worktree(self):
        sub = self.root / "sub"
        sub.mkdir()
        (sub / ".git").write_text(f"gitdir: {self.root}/super/.git/modules/sub\n")
        self.assertEqual(find_siblings(str(sub)), ())


if __name__ == "__main__":
    unittest.main()
