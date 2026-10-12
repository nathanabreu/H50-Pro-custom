"""Verifica se algum arquivo versionado (ou a ser commitado) carrega segredos ou dados pessoais.

    py tools/check_secrets.py            # arquivos já versionados (git ls-files)
    py tools/check_secrets.py --staged   # só o que está no índice (usado pelo hook de pre-commit)

Procura:
  * os VALORES reais do seu ambiente: H50_TOKEN, o user_id da sessão da nuvem e o did/IP do robô
    (lidos de data/cloud-session.json e data/h50.db, que ficam fora do git);
  * sequências hexadecimais de 32 caracteres (formato do token miIO), exceto vetores de teste conhecidos;
  * ssecurity/serviceToken/senhas literais e e-mails (exceto noreply).
Sai com código 1 se achar algo. Sem dependências.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOW_HEX32 = {   # vetores públicos de teste (FIPS-197) e afins
    "69c4e0d86a7b0430d8cdb78070b4c55a", "00112233445566778899aabbccddeeff", "000102030405060708090a0b0c0d0e0f",
    "2b7e151628aed2a6abf7158809cf4f3c", "3243f6a8885a308d313198a2e0370734", "3925841d02dc09fbdc118597196a0b32",
}
ALLOW_EMAIL = re.compile(r"noreply@|@example\.|@users\.noreply\.github\.com")
SKIP_SUFFIX = (".png", ".bin", ".jpg", ".jpeg", ".gif", ".ico", ".wav", ".pkg", ".exe", ".dll", ".pyc")
PATTERNS = [
    (re.compile(r"\b[0-9a-fA-F]{32}\b"), "32 hex (parece token miIO)"),
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "e-mail"),
    (re.compile(r"(?i)\b(ssecurity|servicetoken|password|senha)\s*[:=]\s*['\"][^'\"\s]{8,}"), "credencial literal"),
]


def personal_values() -> dict[str, str]:
    """Valores reais que nunca podem aparecer em arquivos versionados."""
    vals: dict[str, str] = {}
    if os.environ.get("H50_TOKEN"):
        vals[os.environ["H50_TOKEN"]] = "H50_TOKEN"
    try:
        s = json.loads((ROOT / "data" / "cloud-session.json").read_text(encoding="utf-8"))
        for k in ("user_id", "ssecurity", "service_token", "device_id"):
            if s.get(k):
                vals[str(s[k])] = f"sessão da nuvem ({k})"
    except (OSError, ValueError):
        pass
    try:
        db = sqlite3.connect(str(ROOT / "data" / "h50.db"))
        for k, label in (("robot_did", "did do robô"), ("robot_ip", "IP do robô")):
            row = db.execute("SELECT value FROM app_setting WHERE key=?", (k,)).fetchone()
            if row:
                vals[str(json.loads(row[0]))] = label
        db.close()
    except (sqlite3.Error, ValueError):
        pass
    return {v: k for v, k in vals.items() if len(v) >= 6}


def files(staged: bool) -> list[str]:
    cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"] if staged else ["git", "ls-files"]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [f for f in out.splitlines() if f and not f.lower().endswith(SKIP_SUFFIX)]


def content(path: str, staged: bool) -> str:
    if staged:   # o que vai ser commitado, não o arquivo no disco
        res = subprocess.run(["git", "show", f":{path}"], cwd=ROOT, capture_output=True)
        return res.stdout.decode("utf-8", "replace")
    return (ROOT / path).read_text(encoding="utf-8", errors="replace")


def dir_files(root: Path) -> list[str]:
    """Todos os arquivos de texto de uma pasta (fora o .git), para conferir uma cópia publicada."""
    return [p.relative_to(root).as_posix() for p in root.rglob("*")
            if p.is_file() and not ({".git", "__pycache__"} & set(p.relative_to(root).parts))
            and not p.name.lower().endswith(SKIP_SUFFIX)]


def main() -> int:
    staged = "--staged" in sys.argv
    if "--dir" in sys.argv:                  # py tools/check_secrets.py --dir "C:\caminho\do\outro\repositorio"
        root = Path(sys.argv[sys.argv.index("--dir") + 1])
        names, read = dir_files(root), (lambda f: (root / f).read_text(encoding="utf-8", errors="replace"))
    else:
        names, read = files(staged), (lambda f: content(f, staged))
    mine = personal_values()
    bad = []
    for f in names:
        try:
            text = read(f)
        except OSError:
            continue
        for value, label in mine.items():
            if value in text:
                bad.append((f, f"valor real: {label}"))
        for rx, what in PATTERNS:
            for m in rx.finditer(text):
                hit = m.group(0)
                if what.startswith("32 hex"):
                    if hit.lower() in ALLOW_HEX32:
                        continue
                    ctx = text[max(0, m.start() - 8): m.start()]
                    if "/" in ctx or "=" in ctx[-1:]:     # parte de uma URL (gist, hash de arquivo…)
                        continue
                if what == "e-mail" and ALLOW_EMAIL.search(hit):
                    continue
                bad.append((f, f"{what}: {hit[:12]}…"))
    for f, why in sorted(set(bad)):
        print(f"  {f}: {why}")
    if bad:
        print(f"\n{len(set(bad))} problema(s). Remova/substitua por placeholders antes de commitar.")
        return 1
    print(f"ok: {len(names)} arquivo(s) verificados, sem segredos ({len(mine)} valor(es) pessoais checados).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
