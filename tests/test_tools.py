import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GIT = shutil.which("git")


def run(*cmd, cwd=None):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")


@unittest.skipUnless(GIT, "git não instalado")
class SyncTo(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.src, self.dst = Path(self.tmp.name) / "src", Path(self.tmp.name) / "dst"
        for d in (self.src, self.dst):
            d.mkdir()
            run("git", "init", "-q", "-b", "main", cwd=d)

    def commit(self, repo, msg="c"):
        run("git", "add", "-A", cwd=repo)
        r = run("git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", msg, cwd=repo)
        self.assertEqual(r.returncode, 0, r.stderr)

    def sync(self, *extra):
        return run(sys.executable, str(ROOT / "tools" / "sync_to.py"), str(self.dst), "--source", str(self.src), *extra)

    def test_copies_committed_content_not_the_disk_and_propagates_removals(self):
        (self.src / "a.txt").write_text("commitado", encoding="utf-8")
        (self.src / "velho.txt").write_text("x", encoding="utf-8")
        self.commit(self.src)
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual((self.dst / "a.txt").read_text(encoding="utf-8"), "commitado")
        self.commit(self.dst, "importa")                     # no fluxo real o destino commita entre as sincronizações
        run("git", "rm", "-q", "velho.txt", cwd=self.src)
        r = run("git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "remove", cwd=self.src)
        self.assertEqual(r.returncode, 0, r.stderr)                       # commit SÓ do que já estava preparado
        (self.src / "a.txt").write_text("editado e NÃO commitado", encoding="utf-8")   # edição só no disco, depois do commit
        self.assertEqual(self.sync().returncode, 0)
        self.assertEqual((self.dst / "a.txt").read_text(encoding="utf-8"), "commitado")  # o commit, não o disco
        self.assertFalse((self.dst / "velho.txt").exists())

    def test_never_deletes_files_the_target_does_not_track(self):
        (self.src / "a.txt").write_text("x", encoding="utf-8")
        self.commit(self.src)
        (self.dst / "minhas-notas.txt").write_text("meu, não é do projeto", encoding="utf-8")   # não versionado no destino
        self.assertEqual(self.sync().returncode, 0)
        self.assertTrue((self.dst / "minhas-notas.txt").exists())

    def test_dry_run_writes_nothing(self):
        (self.src / "a.txt").write_text("x", encoding="utf-8")
        self.commit(self.src)
        r = self.sync("--dry-run")
        self.assertEqual(r.returncode, 0)
        self.assertIn("novos: 1", r.stdout)
        self.assertFalse((self.dst / "a.txt").exists())

    def test_refuses_personal_data_even_if_it_was_committed_by_mistake(self):
        (self.src / "ok.txt").write_text("ok", encoding="utf-8")
        for rel in ("data-antes/h50.db", "data/robots.json", ".env", "backup.h50bak", "dump.json", "prints_app/a.jpeg",
                    "x/edge-profile/Preferences"):
            f = self.src / rel
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"segredo")
        self.commit(self.src)
        r = self.sync()
        self.assertEqual(r.returncode, 2)
        self.assertIn("RECUSADO", r.stdout)
        for rel in ("data-antes/h50.db", ".env", "dump.json"):
            self.assertIn(rel, r.stdout)
        self.assertFalse((self.dst / "ok.txt").exists())                 # nada foi copiado

    def test_example_env_and_icons_are_allowed(self):
        (self.src / ".env.example").write_text("H50_PORT=8050", encoding="utf-8")
        (self.src / "icon.png").write_bytes(b"\x89PNG")
        self.commit(self.src)
        self.assertEqual(self.sync().returncode, 0)
        self.assertTrue((self.dst / ".env.example").exists())


class CheckSecretsDir(unittest.TestCase):
    def check(self, d):
        return run(sys.executable, str(ROOT / "tools" / "check_secrets.py"), "--dir", str(d))

    def test_ignores_python_cache_but_catches_real_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cache = root / "tests" / "__pycache__"
            cache.mkdir(parents=True)
            (cache / "t.cpython-314.pyc").write_bytes(b"\x00" + b"ab" * 16 + b"\x00")      # constante dobrada pelo compilador
            (root / "ok.py").write_text("x = 1", encoding="utf-8")
            self.assertEqual(self.check(root).returncode, 0)                                  # cache não conta
            (root / "ruim.txt").write_text("t = " + "cd" * 16, encoding="utf-8")
            r = self.check(root)
            self.assertEqual(r.returncode, 1)
            self.assertIn("ruim.txt", r.stdout)


@unittest.skipUnless(GIT, "git não instalado")
class Hook(unittest.TestCase):
    def test_hook_blocks_a_commit_with_a_secret(self):
        with tempfile.TemporaryDirectory() as d:
            repo = Path(d)
            run("git", "init", "-q", "-b", "main", cwd=repo)
            (repo / "tools").mkdir()
            shutil.copy(ROOT / "tools" / "check_secrets.py", repo / "tools" / "check_secrets.py")
            self.assertEqual(run(sys.executable, str(ROOT / "tools" / "install_hook.py"), str(repo)).returncode, 0)
            (repo / "limpo.txt").write_text("nada de segredo", encoding="utf-8")
            (repo / "ruim.txt").write_text("token = " + "ab" * 16, encoding="utf-8")        # 32 hex solto
            run("git", "add", "limpo.txt", cwd=repo)
            ok = run("git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "ok", cwd=repo)
            self.assertEqual(ok.returncode, 0, ok.stderr + ok.stdout)
            run("git", "add", "ruim.txt", cwd=repo)
            bad = run("git", "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "ruim", cwd=repo)
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("ruim.txt", bad.stdout + bad.stderr)


if __name__ == "__main__":
    unittest.main()
