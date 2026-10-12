"""Configuração: variáveis de ambiente, com .env opcional na pasta atual (sem python-dotenv).

Os robôs ficam em `<H50_DATA_DIR>/robots.json` (gerenciados pela interface). `H50_IP`/`H50_TOKEN`/`H50_NAME`
só são usados UMA vez, para migrar uma instalação de um robô só para esse arquivo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    """Carrega KEY=VALUE de um .env sem sobrescrever o que já está no ambiente."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _bool(value: str | None, default: bool = False) -> bool:
    return default if value is None else value.strip().lower() in ("1", "true", "yes", "sim", "on")


@dataclass
class Config:
    data_dir: Path = Path("data")
    host: str = "127.0.0.1"
    port: int = 8050
    timeout: float = 4.0
    raw_enabled: bool = False
    # segurança do painel
    auth_enabled: bool = True          # H50_AUTH=off só vale em localhost
    password: str = ""                 # H50_PASSWORD (Docker); senão a senha é criada no primeiro acesso
    trust_proxy: bool = False          # H50_TRUST_PROXY: só atrás de um proxy/túnel confiável
    cookie_secure: bool = False        # H50_COOKIE_SECURE: marca o cookie como Secure (HTTPS)
    # migração de instalações de um robô só (usados apenas se não houver robots.json)
    ip: str = ""
    token: str = ""
    device_name: str = ""

    @classmethod
    def from_env(cls, env_file: str | Path = ".env") -> "Config":
        load_env(env_file)
        e = os.environ
        token = e.get("H50_TOKEN", "")
        if token and len(token) != 32:
            raise SystemExit("H50_TOKEN deve ter 32 caracteres hexadecimais")
        return cls(
            data_dir=Path(e.get("H50_DATA_DIR", "data")),
            host=e.get("H50_HOST", cls.host),
            port=int(e.get("H50_PORT", cls.port)),
            timeout=float(e.get("H50_TIMEOUT", cls.timeout)),
            raw_enabled=_bool(e.get("RAW_ENABLED")),
            auth_enabled=e.get("H50_AUTH", "on").strip().lower() not in ("off", "false", "0", "no", "nao"),
            password=e.get("H50_PASSWORD", ""), trust_proxy=_bool(e.get("H50_TRUST_PROXY")),
            cookie_secure=_bool(e.get("H50_COOKIE_SECURE")),
            ip=e.get("H50_IP", ""), token=token, device_name=e.get("H50_NAME", ""),
        )

    def seed(self) -> dict:
        return {"ip": self.ip, "token": self.token, "name": self.device_name}
