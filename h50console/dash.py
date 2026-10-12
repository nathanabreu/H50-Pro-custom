"""Agregações para os dashboards (só leitura do banco). Datas agrupadas no fuso local."""

from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from . import catalog
from .store import Store

WEEKDAYS = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"]


def _local(dt: datetime) -> datetime:
    return dt.astimezone()


def consumable_forecast(history: list[dict], today=None) -> dict | None:
    """Estima em quantos dias um consumível acaba, pelo ritmo de desgaste desde a última troca.

    `history`: fotos diárias [{day, pct, hours}] em ordem. Uma troca aparece como a vida subindo: só vale o trecho depois dela.
    Usa as horas restantes (mais finas que a % inteira). Precisa de pelo menos 2 dias de dados e de algum desgaste."""
    if len(history) < 2:
        return None
    seg = [history[-1]]
    for row in reversed(history[:-1]):
        key = "hours" if row.get("hours") is not None and seg[-1].get("hours") is not None else "pct"
        if row.get(key) is None or seg[-1].get(key) is None or row[key] < seg[-1][key]:
            break                                             # a vida subiu: foi trocado ali; o trecho começa depois
        seg.append(row)
    seg.reverse()
    first, last = seg[0], seg[-1]
    span = (datetime.fromisoformat(last["day"]).date() - datetime.fromisoformat(first["day"]).date()).days
    if span < 2:
        return None
    key = "hours" if first.get("hours") is not None and last.get("hours") is not None else "pct"
    burn = (first[key] - last[key]) / span                  # unidades por dia
    if burn <= 0 or last[key] is None:
        return None
    days_left = last[key] / burn
    today = today or datetime.now().date()
    return {"per_day": round(burn, 2), "unit": "h" if key == "hours" else "%", "days_left": round(days_left),
            "date": (today + timedelta(days=days_left)).isoformat(), "based_on_days": span}


def coverage(store: Store, days: int, cell: int = 250, now: datetime | None = None) -> dict:
    """Em quantas limpezas o robô passou por cada quadrado de `cell` mm (mapa de calor de cobertura).

    Cada limpeza conta uma vez por quadrado; os saltos entre pontos (<= 1 m) são preenchidos para não deixar falhas."""
    now = _local(now or datetime.now(timezone.utc))
    start = int((now - timedelta(days=days)).timestamp())
    counts: Counter = Counter()
    paths = store.paths_since(start)
    for rec in paths:
        seen = set()
        prev = None
        for x, y, *_ in rec["points"]:
            if prev and math.hypot(x - prev[0], y - prev[1]) <= 1000:
                steps = max(1, int(math.hypot(x - prev[0], y - prev[1]) // (cell / 2)))
                for i in range(1, steps + 1):
                    seen.add((int((prev[0] + (x - prev[0]) * i / steps) // cell), int((prev[1] + (y - prev[1]) * i / steps) // cell)))
            else:
                seen.add((int(x // cell), int(y // cell)))
            prev = (x, y)
        counts.update(seen)
    return {"days": days, "cell": cell, "cleanings": len(paths), "max": max(counts.values(), default=0),
            "cells": [[cx * cell, cy * cell, n] for (cx, cy), n in counts.items()]}


def cleanings(store: Store, days: int, now: datetime | None = None) -> dict:
    now = _local(now or datetime.now(timezone.utc))
    first_day = (now - timedelta(days=days - 1)).date()
    start = datetime.combine(first_day, datetime.min.time()).astimezone()
    rows = store.cleanings(int(start.timestamp()), None)
    names = {r["id"]: r["name"] for r in store.rooms()}

    by_day = {(first_day + timedelta(days=i)).isoformat(): {"count": 0, "area_m2": 0.0, "duration_min": 0.0}
              for i in range(days)}
    by_room: Counter = Counter()
    by_type: Counter = Counter()
    heat = [[0] * 24 for _ in range(7)]           # [dia da semana][hora]
    for r in rows:
        t = datetime.fromtimestamp(r["stime"], timezone.utc).astimezone()
        d = by_day.get(t.date().isoformat())
        if d is not None:
            d["count"] += 1
            d["area_m2"] += r["area_m2"] or 0
            d["duration_min"] += (r["duration_s"] or 0) / 60
        label = (r["raw_label"] or "")
        if label.startswith("custom:"):
            by_room[f'Rotina "{label[7:]}"'] += 1
        elif label.startswith("zones:"):
            by_room["Zonas"] += 1
        for rid in r["rooms"]:
            by_room[names.get(rid, f"cômodo {rid}")] += 1
        if not r["rooms"] and not label.startswith(("custom:", "zones:")):
            by_room["Casa toda / sem cômodo"] += 1
        by_type[catalog.label("2/5", r["sweep_type"]) if r["sweep_type"] else "Desconhecido"] += 1
        heat[(t.weekday() + 1) % 7][t.hour] += 1   # weekday(): seg=0 -> dom=0

    total_area = sum(r["area_m2"] or 0 for r in rows)
    total_s = sum(r["duration_s"] or 0 for r in rows)
    return {
        "days": days,
        "totals": {"count": len(rows), "area_m2": round(total_area, 2), "duration_min": round(total_s / 60),
                   "avg_area_m2": round(total_area / len(rows), 2) if rows else None},
        "by_day": [{"day": k, **{kk: round(vv, 2) for kk, vv in v.items()}} for k, v in by_day.items()],
        "by_room": [{"label": k, "count": v} for k, v in by_room.most_common()],
        "by_type": [{"label": k, "count": v} for k, v in by_type.most_common()],
        "heat": {"weekdays": WEEKDAYS, "matrix": heat},
    }


def _changes(store: Store, prop: str, start: str) -> tuple[object, list[tuple[str, object]]]:
    """(valor vigente no início da janela, [(ts, novo valor), …] dentro da janela)."""
    before = store._query("SELECT new_value FROM prop_change WHERE prop=? AND ts < ? ORDER BY ts DESC, id DESC LIMIT 1",
                          (prop, start))
    rows = store._query("SELECT ts, new_value FROM prop_change WHERE prop=? AND ts >= ? ORDER BY ts, id", (prop, start))

    def val(v):
        try:
            return json.loads(v)
        except (TypeError, ValueError):
            return v
    return (val(before[0]["new_value"]) if before else None), [(r["ts"], val(r["new_value"])) for r in rows]


def timeline(store: Store, hours: int, now: datetime | None = None, current: dict | None = None) -> dict:
    """Bateria (pontos) e status (segmentos) nas últimas `hours` horas."""
    now = now or datetime.now(timezone.utc)
    start_dt = now - timedelta(hours=hours)
    start, end = start_dt.isoformat(timespec="seconds"), now.isoformat(timespec="seconds")
    current = current or {}

    b0, bch = _changes(store, "3/1", start)
    battery = ([{"t": start, "v": b0}] if b0 is not None else []) + [{"t": t, "v": v} for t, v in bch]
    if battery and current.get("3/1") is not None:
        battery.append({"t": end, "v": current["3/1"]})

    s0, sch = _changes(store, "2/2", start)
    points = ([(start, s0)] if s0 is not None else []) + sch
    segments = []
    for i, (t, st) in enumerate(points):
        t_end = points[i + 1][0] if i + 1 < len(points) else end
        if t_end <= t:
            continue
        segments.append({"start": t, "end": t_end, "status": st, "label": catalog.label("2/2", st),
                         "group": catalog.status_group(st)})
    per_group: dict[str, float] = defaultdict(float)
    for s in segments:
        per_group[s["group"]] += (datetime.fromisoformat(s["end"]) - datetime.fromisoformat(s["start"])).total_seconds()
    data_from = segments[0]["start"] if segments else (battery[0]["t"] if battery else None)
    return {
        "hours": hours, "start": start, "end": end, "data_from": data_from,
        "battery": battery, "segments": segments,
        "groups": [g for g, _ in catalog.STATUS_GROUPS],
        "time_by_group": {g: round(per_group.get(g, 0)) for g, _ in catalog.STATUS_GROUPS},
    }
