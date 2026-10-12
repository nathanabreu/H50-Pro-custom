"""Copia o projeto para OUTRO repositório git, para você revisar, commitar e publicar de lá.

    py tools/sync_to.py "C:\\Programas\\GIT\\H50 Pro custom" --dry-run     # mostra o que mudaria
    py tools/sync_to.py "C:\\Programas\\GIT\\H50 Pro custom"               # copia

- Copia o que está no ÚLTIMO COMMIT daqui (HEAD), não o que está no disco: o que você publica é o que foi commitado.
- RECUSA copiar qualquer coisa com cara de dado pessoal (data*/, .env, bancos, backups, dump.json, prints, perfis do navegador…),
  mesmo que, por engano, tenha sido commitada.
- Apaga no destino o que é VERSIONADO lá (já commitado) e deixou de existir aqui. Arquivos seus não versionados nunca são apagados.
- NÃO faz commit nem push: o destino fica com as mudanças para você conferir (`git status`, `git diff`) e commitar.
- Confere o resultado com tools/check_secrets.py (token, uid, did, IP, sessão).
Sem dependências.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# nada disso pode chegar a um repositório público, nem por engano
FORBIDDEN = re.compile(
    r"(^|/)(data[^/]*|prints_app|win-mirobo[^/]*|edge-profile|shots)(/|$)"
    r"|\.(db|db-wal|db-shm|h50bak|pcapng|etl|bin)$"
    r"|(^|/)(\.env|dump\.json|robots\.json|secret\.key|app\.json|notify\.json|settings\.json|cloud-session\.json)$"
)
ALLOWED_BIN = re.compile(r"\.png$|\.ico$")          # (ícones) png/ico não estão na lista acima; .bin sim


def git(*args: str, binary: bool = False, cwd: Path | None = None):
    res = subprocess.run(["git", *args], cwd=cwd or ROOT, capture_output=True, check=True)
    return res.stdout if binary else res.stdout.decode("utf-8", "replace")


def target_git(target: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=target, capture_output=True, text=True, check=True).stdout


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("target", type=Path)
    ap.add_argument("--source", type=Path, help="repositório de origem (padrão: este)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    target = args.target.resolve()
    source = args.source.resolve() if args.source else ROOT
    if target == source:
        sys.exit("O destino é este mesmo repositório.")
    if not (target / ".git").exists():
        sys.exit(f"{target} não é um repositório git.")
    if git("status", "--porcelain", "--untracked-files=no", cwd=source).strip():
        print("Aviso: há mudanças aqui ainda não commitadas; só o ÚLTIMO COMMIT é copiado.")

    src_files = [f for f in git("ls-tree", "-r", "--name-only", "HEAD", cwd=source).splitlines() if f]
    blocked = [f for f in src_files if FORBIDDEN.search(f) and not ALLOWED_BIN.search(f)]
    if blocked:
        print("RECUSADO: o último commit contém arquivos que parecem dados pessoais:")
        for f in blocked[:30]:
            print(f"  {f}")
        print("Remova-os do git (git rm --cached) e corrija o .gitignore antes de publicar.")
        return 2

    dst_tracked = {f for f in target_git(target, "ls-files").splitlines() if f}
    added, changed, removed = [], [], []
    for rel in src_files:
        data = git("show", f"HEAD:{rel}", binary=True, cwd=source)
        d = target / rel
        if not d.exists():
            added.append(rel)
        elif d.read_bytes() != data:
            changed.append(rel)
        else:
            continue
        if not args.dry_run:
            d.parent.mkdir(parents=True, exist_ok=True)
            d.write_bytes(data)
    for rel in sorted(dst_tracked - set(src_files)):
        removed.append(rel)
        if not args.dry_run:
            (target / rel).unlink(missing_ok=True)

    print(f"{'(simulação) ' if args.dry_run else ''}novos: {len(added)} | alterados: {len(changed)} | removidos: {len(removed)}")
    for label, names in (("novo", added), ("alterado", changed), ("removido", removed)):
        for n in names[:60]:
            print(f"  {label}: {n}")
        if len(names) > 60:
            print(f"  … e mais {len(names) - 60} {label}(s)")
    if args.dry_run:
        return 0
    check = subprocess.run([sys.executable, str(ROOT / "tools" / "check_secrets.py"), "--dir", str(target)])
    if check.returncode:
        print("ATENÇÃO: o verificador achou algo no destino. NÃO publique antes de resolver.")
        return 1
    print(f"\nPronto. Agora, em {target}:\n  git status\n  git add -A && git commit -m \"...\" && git push")
    return 0


if __name__ == "__main__":
    sys.exit(main())
