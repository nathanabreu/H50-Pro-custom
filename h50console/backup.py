"""Backup e restauração criptografados (só biblioteca padrão).

Um backup contém tokens e a sessão da nuvem, então é SEMPRE cifrado:
    arquivo = "H50BAK1\\n" | salt(16) | iterações(4) | iv(16) | AES-128-CBC(zip) | HMAC-SHA256(32)
    chaves  = PBKDF2-HMAC-SHA256(senha, salt, iterações, 48 bytes) → 16 de AES + 32 de HMAC (encrypt-then-MAC)
O HMAC é conferido ANTES de decifrar: senha errada e arquivo adulterado são rejeitados do mesmo jeito.

Conteúdo do zip: manifest.json, robots.json, settings.json, [app.json], [cloud-session.json] e, por robô, uma cópia
consistente do banco (API de backup do SQLite, com o app rodando) e o último mapa. A chave de assinatura das sessões
(secret.key) NÃO entra: depois de restaurar, todos precisam entrar de novo.
"""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import os
import re
import sqlite3
import struct
import time
import zipfile
from pathlib import Path

from . import aes

MAGIC = b"H50BAK1\n"
KDF_ITERS = 200_000
MAX_UNCOMPRESSED = 500 * 1024 * 1024
FIXED = {"manifest.json", "robots.json", "settings.json", "app.json", "cloud-session.json"}
ALLOWED = re.compile(r"(?:robots/[\w.-]+/)?(?:h50\.db|map/latest\.json)|map/latest\.json")


class BackupError(Exception):
    pass


# -- cifra ---------------------------------------------------------------------------------------------------
def _keys(passphrase: str, salt: bytes, iters: int) -> tuple[bytes, bytes]:
    dk = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iters, 48)
    return dk[:16], dk[16:]


def seal(plain: bytes, passphrase: str, iters: int = KDF_ITERS) -> bytes:
    if len(passphrase or "") < 8:
        raise BackupError("use uma senha de backup com pelo menos 8 caracteres")
    salt, iv = os.urandom(16), os.urandom(16)
    enc_key, mac_key = _keys(passphrase, salt, iters)
    head = MAGIC + salt + struct.pack(">I", iters) + iv
    ct = aes.cbc_encrypt(plain, enc_key, iv)
    return head + ct + hmac.new(mac_key, head + ct, hashlib.sha256).digest()


def unseal(blob: bytes, passphrase: str) -> bytes:
    fixed = len(MAGIC) + 16 + 4 + 16
    if len(blob) < fixed + 16 + 32 or not blob.startswith(MAGIC):
        raise BackupError("não é um backup do H50 Console")
    salt = blob[len(MAGIC):len(MAGIC) + 16]
    iters = struct.unpack(">I", blob[len(MAGIC) + 16:len(MAGIC) + 20])[0]
    if not 1000 <= iters <= 5_000_000:
        raise BackupError("arquivo corrompido")
    iv, ct, mac = blob[len(MAGIC) + 20:fixed], blob[fixed:-32], blob[-32:]
    enc_key, mac_key = _keys(passphrase or "", salt, iters)
    if not hmac.compare_digest(mac, hmac.new(mac_key, blob[:fixed] + ct, hashlib.sha256).digest()):
        raise BackupError("senha incorreta ou arquivo corrompido")
    try:
        return aes.cbc_decrypt(ct, enc_key, iv)
    except ValueError as ex:
        raise BackupError("arquivo corrompido") from ex


# -- coleta e restauração --------------------------------------------------------------------------------------
def snapshot_db(store) -> bytes:
    """Cópia consistente do banco com o app rodando (API de backup do SQLite)."""
    dst = sqlite3.connect(":memory:")
    try:
        with store.lock:
            store.db.backup(dst)
        return dst.serialize()
    finally:
        dst.close()


def collect(fleet, include_cloud: bool = True, include_auth: bool = True, app_version: str = "") -> dict[str, bytes]:
    data = fleet.data_dir
    files: dict[str, bytes] = {}

    def add(rel: str) -> None:
        p = data / rel
        if p.exists():
            files[rel] = p.read_bytes()

    add("robots.json")
    add("settings.json")
    if include_auth:
        add("app.json")
    if include_cloud:
        add("cloud-session.json")
    for robot in fleet.robots.values():
        files[robot.db_path.relative_to(data).as_posix()] = snapshot_db(robot.store)
        add((robot.map_dir / "latest.json").relative_to(data).as_posix())
    files["manifest.json"] = json.dumps({
        "format": 1, "created": int(time.time()), "app_version": app_version,
        "robots": [r.cfg.id for r in fleet.robots.values()], "files": sorted(files),
    }, indent=1).encode()
    return files


def create(fleet, passphrase: str, include_cloud: bool = True, include_auth: bool = True, app_version: str = "") -> bytes:
    files = collect(fleet, include_cloud, include_auth, app_version)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for name in ("manifest.json", *sorted(n for n in files if n != "manifest.json")):
            z.writestr(name, files[name])
    return seal(buf.getvalue(), passphrase)


def read(blob: bytes, passphrase: str) -> dict[str, bytes]:
    """Decifra e valida o conteúdo: só nomes esperados, sem caminhos fora da pasta de dados, tamanho limitado."""
    plain = unseal(blob, passphrase)
    try:
        z = zipfile.ZipFile(io.BytesIO(plain))
    except zipfile.BadZipFile as ex:
        raise BackupError("arquivo corrompido") from ex
    infos = z.infolist()
    if sum(i.file_size for i in infos) > MAX_UNCOMPRESSED:
        raise BackupError("backup grande demais")
    out: dict[str, bytes] = {}
    for info in infos:
        name = info.filename
        if name not in FIXED and not ALLOWED.fullmatch(name):
            raise BackupError(f"arquivo inesperado no backup: {name}")
        out[name] = z.read(info)
    if "manifest.json" not in out:
        raise BackupError("backup sem manifesto")
    return out


def apply(fleet, files: dict[str, bytes], include_auth: bool = True, start: bool = True) -> dict:
    """Troca os dados pelos do backup e recarrega a frota. Para os robôs enquanto grava."""
    data = fleet.data_dir
    fleet.stop_all()
    written = []
    for name, content in files.items():
        if name == "manifest.json" or (name == "app.json" and not include_auth):
            continue
        dst = data / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        if name.endswith(".db"):
            for ext in ("-wal", "-shm"):
                Path(str(dst) + ext).unlink(missing_ok=True)
        tmp = dst.with_name(dst.name + ".restore")
        tmp.write_bytes(content)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        tmp.replace(dst)
        written.append(name)
    fleet.reload(start=start)
    return {"written": written, "robots": [r.cfg.id for r in fleet.robots.values()]}
