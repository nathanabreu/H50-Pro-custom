"""Dados de teste SINTÉTICOS: reproduzem a estrutura do que o robô devolve, sem nada de uma casa real.

Servem ao CI público e a quem clona o projeto: com eles a suíte inteira roda, sem os arquivos privados de
tests/fixtures (que ficam fora do git). Tudo é inventado: uid 1000000000, did 1000000001, cômodos, rotinas, agenda,
mapa (desenhado por código e cifrado com o mesmo método do app oficial).

Os valores seguem o que os testes esperam: 12 limpezas somando 188 min e 151,78 m², agenda 06:30 seg–sex e 08:30 fim de
semana, 6 cômodos (ids 3–8), rotina "Sala intenso" nos cômodos 3 e 8, mapa 252×274 a 50 mm/pixel com 2 paredes
virtuais e 2 móveis, histórico da nuvem com 40 itens (21 limpezas únicas, total_count 22).
"""

from __future__ import annotations

import base64
import json
import zlib
from pathlib import Path

from h50console import catalog, mapdecode

UID, DID = "1000000000", "1000000001"
MODEL = "xiaomi.vacuum.ov42gl"

ROOMS = [(3, "Sala de estar"), (4, "Quarto de criança"), (5, "Quarto"), (6, "Cozinha"), (7, "Banheiro"), (8, "Corredor")]
ROOMS_JSON = json.dumps({"rooms": [{"id": i, "name": n} for i, n in ROOMS], "map_uid": 1}, ensure_ascii=False)
SURFACES_JSON = json.dumps([{"id": str(i), "name": n, "surface": 0} for i, n in ROOMS], ensure_ascii=False)

SCHEDULES = {"id": [1791675536, 1791691479], "on": [1, 1], "week": [190, 193], "time": [1566, 2078],
             "clean_conf": [{"mode": 7, "cid": 1791675441}, {"mode": 7, "cid": 1791675441}]}
CUSTOM = {"user_labels": [
    {"id": 1791675441, "name": "Sala intenso", "v": 1, "source": 0, "en": 1, "mop": [3], "room_ids": [3, 8], "user_cfg": []},
    {"id": 1791744466, "name": "Pelos gatos", "v": 1, "source": 0, "en": 1, "mop": [1], "room_ids": [], "user_cfg": []}]}
FURNITURE = {"furnitures": [{"id": 6135, "type": 1220, "rid": 248}, {"id": 15964, "type": 1400, "rid": 3}], "map_uid": 1}


def clean_record_old() -> str:
    """10/3 como o robô enviava com 12 limpezas (cabia no UDP): 188 min e 151,78 m² no total."""
    durations = [660, 240, 3060, 1140, 480, 780, 1260, 600, 900, 1320, 420, 420]
    areas = [0, 2870, 37130, 12700, 7800, 9100, 25150, 8200, 14300, 19800, 6730, 8000]
    types = [10, 1, 1, 3, 3, 3, 1, 3, 3, 1, 3, 3]
    hist = [{"label": f"{d:05d}_{a:04d}_{t}_14649_0", "stime": 1791663407 + i * 9000}
            for i, (d, a, t) in enumerate(zip(durations, areas, types))]
    return json.dumps({"total_time": sum(durations) // 60, "total_area": sum(areas), "total_count": 12, "history_list": hist})


def clean_record_cloud() -> str:
    """10/3 como a nuvem devolve: 21 limpezas únicas, cada uma repetida (menos a mais antiga e a mais nova): 40 itens."""
    fixed = {  # as que os testes conhecem por início/duração/área/tipo
        1791744511: (420, 3520, 3), 1791745283: (1200, 13060, 3), 1791747463: (60, 1670, 7),
        1791748043: (240, 4230, 2), 1791797400: (4680, 61730, 7)}
    unique = {1791500000 + i * 12000: (300 + 60 * i, 5000 + 500 * i, 3) for i in range(16)}
    unique.update(fixed)
    entries = [(s, *v) for s, v in sorted(unique.items())]
    assert len(entries) == 21
    items = []
    for i, (stime, dur, area, typ) in enumerate(entries):
        it = {"label": f"{dur:05d}_{area:04d}_{typ}_0_0", "stime": stime}
        items += [it] if i in (0, len(entries) - 1) else [it, dict(it)]
    return json.dumps({"total_time": 317, "total_area": 259050, "total_count": 22, "history_list": items})


def synthetic_map() -> dict:
    """Mapa 252x274 (50 mm/pixel): seis cômodos retangulares com parede, duas paredes virtuais e dois móveis."""
    w, h, res, ox, oy = 252, 274, 50, -1850, -7850
    grid = bytearray(w * h)
    layout = {3: (10, 120, 110, 250), 4: (118, 10, 200, 100), 5: (118, 150, 200, 260),
              6: (60, 30, 112, 118), 7: (205, 120, 245, 170), 8: (118, 100, 200, 120)}
    boxes = {}
    for rid, (c0, r0, c1, r1) in layout.items():
        for r in range(r0, r1):
            for c in range(c0, c1):
                edge = r in (r0, r1 - 1) or c in (c0, c1 - 1)
                grid[r * w + c] = 1 if edge else rid
        boxes[rid] = (ox + (c0 + c1) // 2 * res, oy + (r0 + r1) // 2 * res)
    world = lambda c, r: (ox + c * res, oy + r * res)                               # noqa: E731
    px, py = world(20, 130)
    pts = [{"x": 0, "y": 0, "type": 0, "sweep_mop_mode": 0, "yaw": 0}]             # o robô preenche com zeros no começo
    pts += [{"x": px + 100 * i, "y": py + 40 * (i % 5), "type": 1 if i % 7 else 0, "sweep_mop_mode": 1, "yaw": 0} for i in range(60)]
    return {
        "map_id": 1, "map_type": 1, "temp": 0, "height": h, "width": w, "have_pile": True,
        "pile_x": px, "pile_y": py, "pile_yaw": 1, "origin_x": ox, "origin_y": oy, "resolution": res, "rotate": 0,
        "map_data": base64.b64encode(zlib.compress(bytes(grid))).decode(), "task_id": 0, "map_name": "",
        "map_room_info": [{"grid_id": i, "room_id": i, "color": i % 5} for i, _ in ROOMS],
        "fb_walls": [{"id": 0, "wall_points": [*world(210, 125), *world(244, 128)]},
                     {"id": 1, "wall_points": [*world(212, 124), *world(211, 168)]}],
        "room_attrs": [{"id": i, "room_name": n, "fan_level": 0, "water_level": 0, "clean_mode": 0, "clean_times": 0,
                        "mop_mode": 0, "floor": 0, "name_pos_x": boxes[i][0], "name_pos_y": boxes[i][1], "on": False}
                       for i, n in ROOMS],
        "furniture": [{"update": 1, "id": 6135, "type": 1220, "pos": [*world(30, 200), *world(30, 230), *world(60, 230), *world(60, 200)]},
                      {"update": 1, "id": 15964, "type": 1400, "pos": [*world(70, 150), *world(70, 170), *world(95, 170), *world(95, 150)]}],
        "map_3d_info": [], "position": {"x": px + 150, "y": py, "yaw": 1},
        "paths": {"pose_id": 1, "points": json.dumps(pts)},
        "current_cleaning_config": {"clean_mode": 1, "is_ai_cleaning": False, "dirty_cleaning": False},
    }


def _default(prop) -> object:
    if prop.format == "bool":
        return False
    if prop.format == "string":
        return ""
    if prop.values:
        return prop.values[0][0]
    return prop.range[0] if prop.range else 0


def dump_values() -> dict[str, object]:
    """Valor de TODA propriedade legível: padrão pelo tipo, e os realistas por cima."""
    vals = {k: _default(catalog.PROPS[k]) for k in catalog.READABLE if k in catalog.PROPS}
    vals.update({
        "1/1": "xiaomi", "1/2": MODEL, "1/3": "SYNTH-0001", "1/4": "4.5.8_0087", "1/5": "SYNTH-SERIAL",
        "2/1": '{"base_version":"1.0-0.0.44"}', "2/2": 2, "2/3": 0, "2/4": 3, "2/5": 1, "2/6": 87, "2/7": 0, "2/8": 1,
        "2/9": 4, "2/10": 3, "2/16": ROOMS_JSON, "2/17": 1791748043, "2/18": '{"mode":0,"progress":0}',
        "2/19": json.dumps(SCHEDULES), "2/40": '{"clean_mode":1,"is_ai_cleaning":false,"dirty_cleaning":false}',
        "2/42": json.dumps(CUSTOM, ensure_ascii=False), "2/61": 2, "2/62": False, "2/66": "",
        "2/67": '{"type":3,"code":0,"index":1791724654}', "2/80": 2, "2/89": -1, "2/102": json.dumps(FURNITURE),
        "3/1": 95, "3/2": 1, "4/2": 70, "5/1": False, "9/1": 98, "9/2": 178, "11/1": False, "11/2": 385878016, "11/3": False,
        "12/1": 99, "12/2": 357, "13/1": 98, "13/2": 177, "14/1": 98, "14/2": 177, "15/1": "pt", "15/2": "pt",
        "18/1": 100, "18/4": 180, "19/1": 93, "19/2": 56,
        "10/1": json.dumps({"index": 1791744654, "obj_name": f"{UID}/{DID}/0"}),
        "10/2": json.dumps({"index": 1791742963, "obj_name": f"{UID}/{DID}/1"}),
        "10/5": json.dumps({"index": 1791743566, "map_array": [{"map_name": "", "obj_name": f"{UID}/{DID}/2", "map_id": 1, "temp": 0, "is_current": True}]}),
        "10/6": 1,
        "10/13": json.dumps({"index": 1791743568, "backup_map_arr": [{"map_name": "1791724654", "obj_name": f"{UID}/{DID}/8", "map_id": -2, "backup_id": 1}]}),
        "20/3": '{"differ":[{"type":2,"status":0},{"type":1,"status":0}]}',
        "23/1": SURFACES_JSON, "23/2": "[]", "23/3": "[]", "2/104": 1, "2/105": 1,
    })
    vals.pop("10/3", None)                         # o 10/3 não cabe no UDP: "timeout" no dump da LAN
    return vals


def build(dest: Path) -> Path:
    """Escreve em `dest` os 5 arquivos que os testes esperam (mesmos nomes e formatos de tests/fixtures)."""
    dest.mkdir(parents=True, exist_ok=True)
    vals = dump_values()
    props = {k: {"code": 0, "ms": 10, "value": v, "bytes": len(json.dumps(v))} for k, v in vals.items()}
    props["10/3"] = {"code": "timeout", "err": "timeout", "ms": 6000}
    (dest / "dump-full.json").write_text(json.dumps({"ts": "synthetic", "props": props}, ensure_ascii=False), encoding="utf-8")
    (dest / "dump.json").write_text(json.dumps({"2/2": 2, "10/3": clean_record_old()}), encoding="utf-8")
    extras = {k: vals[k] for k in ("23/1", "23/2", "23/3", "2/104", "2/105") if k in vals}
    scan = {k: {"code": 0, "ms": 20, **({"value": v} if v not in ("",) else {})} for k, v in extras.items()}
    (dest / "scan.json").write_text(json.dumps({"ts": "synthetic", "found": scan}, ensure_ascii=False), encoding="utf-8")
    (dest / "clean-record-cloud.json").write_text(clean_record_cloud(), encoding="utf-8")
    (dest / "map-v2.bin").write_bytes(mapdecode.encrypt(synthetic_map(), MODEL, DID))
    return dest
