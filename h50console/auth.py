"""Autenticação do painel (só biblioteca padrão).

- Senha com PBKDF2-HMAC-SHA256 (600 mil iterações) em <data>/app.json; `H50_PASSWORD` (Docker) tem prioridade.
- Primeiro acesso: sem senha configurada, o app gera um CÓDIGO que aparece só no console; criar a senha exige esse
  código (ninguém que alcance a porta antes de você consegue tomar posse).
- Sessão: cookie assinado (HMAC-SHA256) com validade de 30 dias; trocar a senha ou "sair de todos" invalida todas.
- Limite de tentativas por IP (5 erros → espera que dobra até 15 min). Comparações em tempo constante.
- CSRF: cookie SameSite=Strict + cabeçalho X-H50 e checagem de Origin nas requisições que alteram algo (no web.py).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

PBKDF2_ITERS = 600_000
SESSION_DAYS = 30
MIN_PASSWORD = 8
COOKIE = "h50s"
MAX_FAILS = 5
MAX_LOCK = 15 * 60


class AuthError(Exception):
    def __init__(self, status: int, message: str, retry_after: int = 0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def hash_password(password: str, salt: bytes | None = None, iters: int = PBKDF2_ITERS) -> dict:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iters)
    return {"salt": salt.hex(), "hash": dk.hex(), "iters": iters}


def verify_password(password: str, rec: dict) -> bool:
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(rec["salt"]), int(rec["iters"]))
    return hmac.compare_digest(dk.hex(), rec["hash"])


def is_loopback(host: str) -> bool:
    return host in ("127.0.0.1", "::1", "localhost")


class Auth:
    def __init__(self, data_dir, *, enabled: bool = True, env_password: str = "", iters: int = PBKDF2_ITERS,
                 clock=time.time):
        self.dir = Path(data_dir)
        self.enabled = enabled
        self.env_password = env_password
        self.iters = iters
        self.clock = clock
        self._lock = threading.Lock()
        self._fails: dict[str, tuple[int, float]] = {}            # ip -> (erros, bloqueado até)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.path = self.dir / "app.json"
        self.cfg: dict = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.secret = self._load_secret()
        self.setup_code: str | None = None if self.configured else self._new_code()

    def reload(self) -> None:
        """Relê senha e chave do disco (depois de restaurar um backup)."""
        self.cfg = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        self.secret = self._load_secret()
        self.setup_code = None if self.configured else (self.setup_code or self._new_code())

    # -- armazenamento -------------------------------------------------------------------------------
    def _load_secret(self) -> bytes:
        p = self.dir / "secret.key"
        if not p.exists():
            p.write_text(secrets.token_hex(32), encoding="utf-8")
            self._private(p)
        return bytes.fromhex(p.read_text(encoding="utf-8").strip())

    @staticmethod
    def _private(path: Path) -> None:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.cfg, indent=1), encoding="utf-8")
        self._private(tmp)
        tmp.replace(self.path)

    @staticmethod
    def _new_code() -> str:
        a = secrets.token_hex(2).upper()
        return f"{a}-{secrets.token_hex(2).upper()}"

    @property
    def configured(self) -> bool:
        return bool(self.env_password or self.cfg.get("password"))

    @property
    def pwv(self) -> int:
        return int(self.cfg.get("pwv", 1))

    def status(self, authenticated: bool) -> dict:
        return {"enabled": self.enabled, "configured": self.configured,
                "setup_required": self.enabled and not self.configured, "authenticated": authenticated}

    # -- limite de tentativas ----------------------------------------------------------------------------
    def _check_rate(self, ip: str) -> None:
        with self._lock:
            _n, until = self._fails.get(ip, (0, 0.0))
        left = int(until - self.clock())
        if left > 0:
            raise AuthError(429, f"muitas tentativas; tente de novo em {left} s", retry_after=left)

    def _fail(self, ip: str) -> None:
        with self._lock:
            n, _ = self._fails.get(ip, (0, 0.0))
            n += 1
            lock = 0.0 if n < MAX_FAILS else min(MAX_LOCK, 30 * 2 ** (n - MAX_FAILS))
            self._fails[ip] = (n, self.clock() + lock)

    def _ok(self, ip: str) -> None:
        with self._lock:
            self._fails.pop(ip, None)

    # -- senha ---------------------------------------------------------------------------------------------
    def _check_password(self, password: str) -> bool:
        if self.env_password:
            return hmac.compare_digest(password.encode(), self.env_password.encode())
        rec = self.cfg.get("password")
        return bool(rec) and verify_password(password, rec)

    def setup(self, code: str, password: str, ip: str = "") -> str:
        """Primeiro acesso: cria a senha. Devolve um token de sessão."""
        if self.configured:
            raise AuthError(409, "a senha já foi criada")
        self._check_rate(ip)
        if not self.setup_code or not hmac.compare_digest((code or "").strip().upper().encode(), self.setup_code.encode()):
            self._fail(ip)
            raise AuthError(403, "código de primeiro acesso incorreto (ele aparece no console onde o app foi iniciado)")
        if len(password or "") < MIN_PASSWORD:
            raise AuthError(400, f"use uma senha com pelo menos {MIN_PASSWORD} caracteres")
        self.cfg["password"] = hash_password(password, iters=self.iters)
        self.cfg["pwv"] = self.pwv
        self._save()
        self.setup_code = None
        self._ok(ip)
        return self.make_token()

    def login(self, password: str, ip: str = "") -> str:
        if not self.configured:
            raise AuthError(409, "primeiro acesso: crie a senha")
        self._check_rate(ip)
        if not self._check_password(password or ""):
            self._fail(ip)
            raise AuthError(401, "senha incorreta")
        self._ok(ip)
        return self.make_token()

    def change_password(self, current: str, new: str) -> str:
        if self.env_password:
            raise AuthError(409, "a senha vem de H50_PASSWORD; altere a variável de ambiente")
        if not self._check_password(current or ""):
            raise AuthError(401, "senha atual incorreta")
        if len(new or "") < MIN_PASSWORD:
            raise AuthError(400, f"use uma senha com pelo menos {MIN_PASSWORD} caracteres")
        self.cfg["password"] = hash_password(new, iters=self.iters)
        self.cfg["pwv"] = self.pwv + 1                 # invalida as outras sessões
        self._save()
        return self.make_token()

    def reset_password(self) -> None:
        """Esqueci a senha: apaga a senha guardada e invalida todas as sessões. Na próxima partida o app gera um
        código de primeiro acesso novo. Só é alcançável por quem tem acesso aos arquivos do servidor."""
        self.cfg.pop("password", None)
        self.cfg["pwv"] = self.pwv + 1
        self._save()
        self.setup_code = None if self.configured else self._new_code()

    def revoke_all(self) -> str:
        """Sai de todos os aparelhos (menos o atual, que recebe um token novo)."""
        self.cfg["pwv"] = self.pwv + 1
        self._save()
        return self.make_token()

    # -- sessão -----------------------------------------------------------------------------------------------
    def _sig(self, body: str) -> str:
        key = self.secret + f":{self.pwv}".encode()
        return hmac.new(key, body.encode(), hashlib.sha256).hexdigest()

    def make_token(self) -> str:
        body = f"v1.{int(self.clock()) + SESSION_DAYS * 86400}.{secrets.token_hex(8)}"
        return f"{body}.{self._sig(body)}"

    def valid_token(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            version, exp, nonce, sig = token.split(".")
        except ValueError:
            return False
        body = f"{version}.{exp}.{nonce}"
        if version != "v1" or not hmac.compare_digest(sig, self._sig(body)):
            return False
        return int(exp) > self.clock()

    @staticmethod
    def cookie(token: str, secure: bool = False, clear: bool = False) -> str:
        parts = [f"{COOKIE}={'' if clear else token}", "Path=/", "HttpOnly", "SameSite=Strict",
                 "Max-Age=0" if clear else f"Max-Age={SESSION_DAYS * 86400}"]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)

    @staticmethod
    def token_from_cookie_header(header: str | None) -> str | None:
        for part in (header or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == COOKIE:
                return v
        return None
