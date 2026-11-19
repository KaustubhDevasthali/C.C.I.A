import contextlib
import io
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from ccia.analyzer import GitError, analyze
from ccia.cli import main


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


class AnalyzerTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.repo = Path(temporary.name)
        self.git("init", "--quiet", "--template=")

    def git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.repo), "-c", "user.name=Fixture",
             "-c", "user.email=fixture@example.invalid", "-c", "core.hooksPath=/dev/null", *args],
            check=True, capture_output=True,
        ).stdout

    def write(self, path, source):
        file = self.repo / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(source, encoding="utf-8")

    def commit(self):
        self.git("add", "-A")
        self.git("commit", "--quiet", "--no-gpg-sign", "-m", "Fixture snapshot")
        return self.git("rev-parse", "HEAD").decode().strip()

    def test_sample_transitive_impact_is_stable_and_ignores_worktree(self):
        shutil.copytree(EXAMPLES / "base", self.repo, dirs_exist_ok=True)
        base = self.commit()
        shutil.copytree(EXAMPLES / "head", self.repo, dirs_exist_ok=True)
        head = self.commit()
        self.write("shop/checkout.py", "value = 0\n")
        self.git("add", "shop/checkout.py")
        self.write("untracked.py", "from shop import prices\n")
        status = self.git("status", "--porcelain")
        index = (self.repo / ".git" / "index").read_bytes()
        report = analyze(self.repo / "shop", "HEAD^", "HEAD")
        self.assertEqual(report, analyze(self.repo, base, head))
        self.assertEqual(report["changes"], [{"path": "shop/prices.py", "status": "M"}])
        self.assertEqual(report["impacted_python_files"], ["main.py", "shop/checkout.py"])
        self.assertEqual((self.repo / ".git" / "index").read_bytes(), index)
        self.assertEqual(self.git("status", "--porcelain"), status)

    def test_two_snapshots_handle_added_and_deleted_import_targets(self):
        self.write("src/demo/__init__.py", "")
        self.write("src/demo/old.py", "type Count = int\n")
        self.write("src/demo/old_consumer.py", "from . import old\n")
        self.write("src/demo/new_consumer.py", "from . import new\n")
        self.write("src/demo/outer.py", "import demo.old_consumer\n")
        self.write("misc.py", "import demo.old\n")
        base = self.commit()
        (self.repo / "src/demo/old.py").unlink()
        self.write("src/demo/new.py", "value = 2\n")
        self.write("note\twith\nwhitespace.txt", "hello\n")
        head = self.commit()
        report = analyze(self.repo, base, head, "src")
        self.assertEqual(report["changes"], [
            {"path": "note\twith\nwhitespace.txt", "status": "A"},
            {"path": "src/demo/new.py", "status": "A"},
            {"path": "src/demo/old.py", "status": "D"},
        ])
        self.assertEqual(report["impacted_python_files"],
                         ["src/demo/new_consumer.py", "src/demo/old_consumer.py", "src/demo/outer.py"])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(analyze(self.repo, head, head, "src")["impacted_python_files"], [])

    def test_cycles_and_unparseable_files(self):
        self.write("first.py", "import second\n")
        self.write("second.py", "import first\n")
        self.write("invalid.py", "import\n")
        base = self.commit()
        self.write("first.py", "import second\nvalue = 2\n")
        report = analyze(self.repo, base, self.commit())
        self.assertEqual(report["impacted_python_files"], ["second.py"])
        self.assertEqual(
            [(warning["snapshot"], warning["path"]) for warning in report["warnings"]],
            [("base", "invalid.py"), ("head", "invalid.py")],
        )

    def test_invalid_revisions_and_source_root(self):
        self.write("sample.py", "")
        self.commit()
        with self.assertRaises(GitError):
            analyze(self.repo, "--version", "HEAD")
        with self.assertRaises(ValueError):
            analyze(self.repo, "HEAD", "HEAD", "../")
        errors = io.StringIO()
        with contextlib.redirect_stderr(errors):
            self.assertEqual(main(["missing", "HEAD", "--repo", str(self.repo)]), 2)
        self.assertIn("ccia:", errors.getvalue())


if __name__ == "__main__":
    unittest.main()
