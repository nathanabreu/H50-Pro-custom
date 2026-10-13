"""Decodifica o mapa da nuvem do H50 Pro (só biblioteca padrão: aes.py + zlib).

Arquivo baixado: {"version": 2, "data": "<base64>"} = AES-128-CBC + zlib de um JSON.
Derivação da chave (engenharia reversa do plugin RN do Xiaomi Home feita pelo projeto
devbis/xiaomi-vac, `xiaomi_json_decrypt.py`; confirmada aqui com o mapa real de 11/10/2026):
    mk  = model[-16:]                              # "mi.vacuum.ov42gl"
    key = MD5(AES-CBC(mk, IV).encrypt(PKCS7(mk + did)))
    json = zlib(AES-CBC(key, IV).decrypt(data))    # IV fixo "ABCDEF1234123412"

JSON do mapa (observado):
    width/height/resolution(mm por pixel)/origin_x/origin_y (mm): pixel (col, row) -> mundo
        x = origin_x + col*resolution, y = origin_y + row*resolution  (x para a direita, y para cima)
    map_data: base64(zlib(grade)), 1 byte por pixel: 0 fora, 1 parede, 3..N id do cômodo
    pile_x/pile_y/pile_yaw: base; position {x, y, yaw}: robô
    room_attrs[]: id, room_name, name_pos_x/y, ajustes por cômodo (fan/water/clean_times…)
    fb_walls[]: paredes virtuais {id, wall_points: [x1, y1, x2, y2]}
    furniture[]: {id, type, pos: [x1,y1,…,x4,y4]} (1220 sofá, 1400 mesa, 1740 liteira)
    paths.points: JSON string com a trajetória [{x, y, type, sweep_mop_mode, yaw}]
    map_3d_info[]: contornos por cômodo {room_id, lines: [{type, segment: [x1,y1,x2,y2]}]}
"""

from __future__ import annotations

import base64
import hashlib
import json
import zlib

from . import aes

IV = b"ABCDEF1234123412"


def map_key(model: str, did: str) -> bytes:
    mk = model[-16:].encode("latin-1")
    return hashlib.md5(aes.cbc_encrypt(mk + str(did).encode("latin-1"), mk, IV)).digest()  # noqa: S324


def decrypt(raw: bytes, model: str, did: str) -> dict:
    """Bytes baixados da nuvem -> dict do mapa. ValueError se o formato/chave não conferirem."""
    env = json.loads(raw)
    if env.get("version") != 2:
        raise ValueError(f"versão de mapa não suportada: {env.get('version')!r}")
    plain = aes.cbc_decrypt(base64.b64decode(env["data"]), map_key(model, did), IV)
    return json.loads(zlib.decompress(plain).decode("utf-8"))


def encrypt(m: dict, model: str, did: str) -> bytes:
    """Inverso de decrypt(): dict do mapa -> bytes do arquivo da nuvem. Usado só para gerar mapas SINTÉTICOS de teste."""
    plain = zlib.compress(json.dumps(m, ensure_ascii=False).encode("utf-8"))
    ct = aes.cbc_encrypt(plain, map_key(model, did), IV)
    return json.dumps({"version": 2, "data": base64.b64encode(ct).decode()}).encode()


def grid(m: dict) -> bytes:
    """Grade crua (width*height bytes, linha 0 = menor y)."""
    g = zlib.decompress(base64.b64decode(m["map_data"]))
    if len(g) != m["width"] * m["height"]:
        raise ValueError(f"grade com {len(g)} bytes, esperado {m['width'] * m['height']}")
    return g


def for_ui(m: dict) -> dict:
    """Versão enxuta para o navegador: a grade segue como base64(zlib) e a UI descompacta."""
    pts = m.get("paths", {}).get("points") or "[]"
    path = [[p["x"], p["y"], p.get("type", 0)] for p in json.loads(pts) if p.get("x") or p.get("y")]
    rooms = {r["id"]: r for r in m.get("room_attrs", [])}
    return {
        "map_id": m.get("map_id"), "width": m["width"], "height": m["height"], "resolution": m["resolution"],
        "origin": [m["origin_x"], m["origin_y"]], "grid_zlib_b64": m["map_data"],
        "pile": [m.get("pile_x"), m.get("pile_y"), m.get("pile_yaw")] if m.get("have_pile") else None,
        "robot": [m["position"]["x"], m["position"]["y"], m["position"].get("yaw")] if m.get("position") else None,
        "rooms": [{"id": r["id"], "name": r.get("room_name", ""), "pos": [r.get("name_pos_x"), r.get("name_pos_y")],
                   "fan": r.get("fan_level"), "water": r.get("water_level"), "times": r.get("clean_times"),
                   "mode": r.get("clean_mode")} for r in rooms.values()],
        "walls": [w["wall_points"] for w in m.get("fb_walls", [])],
        "wall_ids": [w.get("id") for w in m.get("fb_walls", [])],
        "furniture": [{"id": f["id"], "type": f["type"], "pos": f["pos"]} for f in m.get("furniture", [])],
        "path": path,
        "config": m.get("current_cleaning_config"),
    }
