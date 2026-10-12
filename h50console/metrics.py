"""Métricas no formato texto do Prometheus (GET /metrics). Sem biblioteca, só leitura do que o app já tem em memória/banco.

Um rótulo `robot` (id) em todas as séries. Nada sensível sai aqui: sem token, IP, DID nem nomes de cômodo.
"""

from __future__ import annotations

from datetime import datetime

from . import catalog


def _esc(v) -> str:
    return str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _epoch(v):
    """last_ok vem como texto ISO-8601 (ou número); devolve segundos desde 1970, ou None."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        return datetime.fromisoformat(str(v)).timestamp()
    except ValueError:
        return None


def render(robots, version: str, started: float, now: float) -> str:
    """`robots`: iterável de fleet.Robot."""
    lines: list[str] = []
    seen: set[str] = set()

    def metric(name: str, help_: str, kind: str, labels: dict, value) -> None:
        if value is None:
            return
        if name not in seen:
            seen.add(name)
            lines.append(f"# HELP {name} {help_}")
            lines.append(f"# TYPE {name} {kind}")
        lab = ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items())
        lines.append(f"{name}{{{lab}}} {float(value):g}")

    for r in robots:
        c = r.gw.cache
        rid = {"robot": r.cfg.id}
        status = c.get("2/2")
        metric("h50_robot_online", "1 se o robô respondeu no último ciclo.", "gauge", rid, int(bool(r.gw.online)))
        metric("h50_robot_last_ok_timestamp_seconds", "Quando o robô respondeu pela última vez (epoch).", "gauge", rid, _epoch(r.gw.last_ok))
        metric("h50_battery_percent", "Bateria do robô.", "gauge", rid, c.get("3/1"))
        metric("h50_status_code", "Código de estado (2/2) do robô.", "gauge", rid, status)
        metric("h50_cleaning_active", "1 enquanto o robô limpa, volta ou trabalha na base.", "gauge", rid,
               None if status is None else int(status in catalog.ACTIVE_STATUS))
        metric("h50_fault_code", "Código de falha atual (0 = nenhuma).", "gauge", rid, c.get("2/3"))
        for item, (pct, hours) in catalog.CONSUMABLE_PROPS.items():
            lab = {**rid, "item": item}
            metric("h50_consumable_percent", "Vida útil restante do consumível.", "gauge", lab, c.get(pct))
            metric("h50_consumable_hours", "Horas restantes do consumível.", "gauge", lab, c.get(hours))
        rows = r.store.cleanings()
        metric("h50_cleanings_total", "Limpezas registradas no histórico.", "counter", rid, len(rows))
        metric("h50_cleaned_area_square_meters_total", "Área limpa registrada no histórico.", "counter", rid,
               round(sum(x["area_m2"] or 0 for x in rows), 2))
        metric("h50_cleaning_seconds_total", "Tempo de limpeza registrado no histórico.", "counter", rid,
               sum(x["duration_s"] or 0 for x in rows))
    metric("h50_build_info", "Versão do H50 Console.", "gauge", {"version": version}, 1)
    metric("h50_uptime_seconds", "Tempo desde que o app iniciou.", "gauge", {}, max(0.0, now - started))
    return "\n".join(lines) + "\n"
