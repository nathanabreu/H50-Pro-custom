"""Instala o hook de pre-commit que roda tools/check_secrets.py (impede commitar token, uid, did, IP ou sessão).

    py tools/install_hook.py                 # neste repositório
    py tools/install_hook.py "C:\\caminho\\do\\outro\\repositorio"

Hooks não são versionados pelo git: rode isto uma vez em cada clone. O CI do GitHub roda a mesma conferência.
"""

import stat
import sys
from pathlib import Path

repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
git_dir = repo / ".git"
if not git_dir.is_dir():
    sys.exit(f"{repo} não é um repositório git.")
checker = Path(__file__).resolve().parent / "check_secrets.py"
hook = git_dir / "hooks" / "pre-commit"
hook.parent.mkdir(exist_ok=True)
# usa o verificador do próprio repositório (tools/check_secrets.py) e devolve o código de saída DELE, sem mascarar
hook.write_text(
    "#!/bin/sh\n"
    "# bloqueia commits com segredos/dados pessoais (tools/check_secrets.py)\n"
    "CHECK=tools/check_secrets.py\n"
    f"[ -f \"$CHECK\" ] || CHECK=\"{checker.as_posix()}\"\n"
    "for PY in py python3 python; do\n"
    "  if command -v \"$PY\" >/dev/null 2>&1; then exec \"$PY\" \"$CHECK\" --staged; fi\n"
    "done\n"
    "echo 'Python não encontrado: não foi possível conferir segredos.' >&2\n"
    "exit 1\n",
    encoding="utf-8", newline="\n")
hook.chmod(hook.stat().st_mode | stat.S_IXUSR)
print(f"hook instalado em {hook}")
