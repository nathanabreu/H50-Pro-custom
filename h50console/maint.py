"""Manutenção: espaço e linhas por robô, otimização do banco, retenção, logs e pacote de diagnóstico."""

from __future__ import annotations

import collections
import json
import logging
import platform
import re
import sys
import time
from pathlib import Path

TABLES = ("prop_change", "cleaning_record", "consumable_snapshot", "command_log", "fault_event", "room")


class RingLog(logging.Handler):
    """Guarda as últimas mensagens de log em memória (aba Manutenção e pacote de diagnóstico)."""

    def __init__(self, capacity: int = 500):
        super().__init__(logging.INFO)
        self.records: collections.deque = collections.deque(maxlen=capacity)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.records.append({"ts": time.strftime("%H:%M:%S", time.localtime(record.created)),
                                 "level": record.levelname, "name": record.name, "msg": record.getMessage()})
        except Exception:  # noqa: BLE001 - log nunca pode derrubar o app
            pass

    def tail(self, n: int = 200) -> list[dict]:
        return list(self.records)[-n:]


def file_size(path: Path) -> int:
    return sum(p.stat().st_size for p in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")) if p.exists())


def dir_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def db_stats(robot) -> dict:
    st = robot.store
    rows = {t: st._query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"] for t in TABLES}
    oldest = st._query("SELECT MIN(ts) AS ts FROM prop_change")[0]["ts"]
    return {"id": robot.cfg.id, "name": robot.cfg.name, "db_bytes": file_size(robot.db_path),
            "map_bytes": dir_size(robot.map_dir), "rows": rows, "oldest_change": oldest}


def optimize(robot) -> dict:
    """Checkpoint do WAL + VACUUM (devolve espaço) + estatísticas do otimizador."""
    st = robot.store
    before = file_size(robot.db_path)
    with st.lock:
        st.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        st.db.execute("VACUUM")
        st.db.execute("PRAGMA optimize")
    return {"id": robot.cfg.id, "before": before, "after": file_size(robot.db_path)}


def purge(robot, days: int) -> dict:
    """Apaga mudanças de propriedades antigas (todas). O histórico de limpezas e consumíveis nunca é apagado."""
    n = robot.store.purge_changes(None, days=days)
    n += robot.store.purge_commands(days=max(days, 365))
    return {"id": robot.cfg.id, "deleted": n}


def mask_ip(ip: str) -> str:
    return re.sub(r"(\d+\.\d+\.\d+\.)\d+", r"\1x", ip or "")


def support_bundle(hub, ring: RingLog | None, version: str) -> dict:
    """Informações úteis para um relatório de problema, SEM segredos (token, sessão, DID, IP completo)."""
    robots = []
    for r in hub.fleet.robots.values():
        c = r.cfg
        robots.append({"model": c.model, "transport": c.transport, "ip": mask_ip(c.ip), "has_did": bool(c.did),
                       "online": r.gw.online, "via": r.gw.via, "fails": r.gw.fails, "latency_ms": r.gw.last_latency_ms,
                       "status": r.gw.cache.get("2/2"), "props_in_cache": len(r.gw.cache.values),
                       "db_bytes": file_size(r.db_path)})
    return {
        "app_version": version, "python": sys.version.split()[0], "platform": platform.platform(),
        "generated": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cloud_state": hub.cloud.state if hub.cloud else "none",
        "robots": robots,
        "log": [{k: (mask_ip(v) if k == "msg" else v) for k, v in rec.items()} for rec in (ring.tail(200) if ring else [])],
    }


def bundle_json(hub, ring, version) -> bytes:
    return json.dumps(support_bundle(hub, ring, version), ensure_ascii=False, indent=1).encode()
