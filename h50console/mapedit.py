"""Edição do mapa em RASCUNHO: operações puras sobre o JSON decifrado do mapa (mapdecode.decrypt).

NADA aqui escreve no robô. O app monta o rascunho, mostra o resultado e a lista de mudanças; gravar de volta no robô
depende de descobrir o formato de escrita (ver docs/BACKLOG.md, "Edição do mapa pelo app"). Por isso toda função devolve
uma CÓPIA e valida o que recebe (limites, tamanhos, o que existe), para o dia em que a gravação for ligada.

Operações (dicts, como chegam da API):
    {"op": "add_wall",   "x1":, "y1":, "x2":, "y2":}                       parede virtual (mm)
    {"op": "remove_wall", "id":}
    {"op": "add_furniture", "type":, "cx":, "cy":, "w":, "h":, "angle": 0}  móvel centrado em (cx, cy), tamanho w×h (mm)
    {"op": "move_furniture", "id":, "dx":, "dy":}
    {"op": "remove_furniture", "id":}
    {"op": "rename_room", "id":, "name":}
Coordenadas em mm, x para a direita e y para cima (as mesmas de mapdecode).
"""

from __future__ import annotations

import copy
import math

MAX_WALLS = 20
MAX_FURNITURE = 40
MIN_WALL_MM = 200
MAX_WALL_MM = 20_000
MIN_SIDE_MM, MAX_SIDE_MM = 100, 5_000
MAX_ROOM_NAME = 20

# tamanhos padrão (largura × profundidade, mm) por tipo conhecido
DEFAULT_SIZE = {1220: (1800, 800), 1400: (1200, 800), 1740: (500, 400)}


class EditError(ValueError):
    """Operação inválida (mensagem pensada para aparecer na tela)."""


def _num(op: dict, key: str) -> float:
    try:
        v = float(op[key])
    except (KeyError, TypeError, ValueError):
        raise EditError(f"campo '{key}' ausente ou inválido") from None
    if not math.isfinite(v):
        raise EditError(f"campo '{key}' inválido")
    return v


def bounds(m: dict) -> tuple[float, float, float, float]:
    """Caixa do mapa em mm: (xmin, ymin, xmax, ymax)."""
    res = m["resolution"]
    x0, y0 = m["origin_x"], m["origin_y"]
    return x0, y0, x0 + m["width"] * res, y0 + m["height"] * res


def _inside(m: dict, x: float, y: float) -> bool:
    xmin, ymin, xmax, ymax = bounds(m)
    return xmin <= x <= xmax and ymin <= y <= ymax


def _next_id(items: list[dict], floor: int = 1) -> int:
    return max([floor - 1] + [int(i.get("id", 0)) for i in items]) + 1


def corners(cx: float, cy: float, w: float, h: float, angle_deg: float = 0.0) -> list[int]:
    """Quatro cantos (x1,y1,…,x4,y4), na ordem que o robô usa (sentido horário a partir do canto -w/-h)."""
    a = math.radians(angle_deg)
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for dx, dy in ((-w / 2, -h / 2), (-w / 2, h / 2), (w / 2, h / 2), (w / 2, -h / 2)):
        pts += [round(cx + dx * ca - dy * sa), round(cy + dx * sa + dy * ca)]
    return pts


def _find(items: list[dict], ident, what: str) -> dict:
    for i in items:
        if i.get("id") == ident:
            return i
    raise EditError(f"{what} {ident} não existe no mapa")


def apply_op(m: dict, op: dict) -> None:
    """Aplica UMA operação em `m` (modifica o dict recebido: use apply_ops para trabalhar numa cópia)."""
    kind = op.get("op")
    if kind == "add_wall":
        pts = [_num(op, k) for k in ("x1", "y1", "x2", "y2")]
        if not (_inside(m, pts[0], pts[1]) and _inside(m, pts[2], pts[3])):
            raise EditError("a parede precisa ficar dentro do mapa")
        length = math.hypot(pts[2] - pts[0], pts[3] - pts[1])
        if not MIN_WALL_MM <= length <= MAX_WALL_MM:
            raise EditError(f"parede com {length / 1000:.1f} m: use entre {MIN_WALL_MM / 1000:.1f} e {MAX_WALL_MM / 1000:.0f} m")
        walls = m.setdefault("fb_walls", [])
        if len(walls) >= MAX_WALLS:
            raise EditError(f"limite de {MAX_WALLS} paredes virtuais")
        walls.append({"id": _next_id(walls, 0), "wall_points": [round(p) for p in pts]})
    elif kind == "remove_wall":
        walls = m.get("fb_walls", [])
        walls.remove(_find(walls, op.get("id"), "parede"))
    elif kind == "add_furniture":
        t = int(_num(op, "type"))
        w0, h0 = DEFAULT_SIZE.get(t, (800, 800))
        w = float(op["w"]) if op.get("w") is not None else w0
        h = float(op["h"]) if op.get("h") is not None else h0
        cx, cy = _num(op, "cx"), _num(op, "cy")
        if not (MIN_SIDE_MM <= w <= MAX_SIDE_MM and MIN_SIDE_MM <= h <= MAX_SIDE_MM):
            raise EditError(f"tamanho do móvel entre {MIN_SIDE_MM} e {MAX_SIDE_MM} mm")
        pos = corners(cx, cy, w, h, float(op.get("angle") or 0))
        if not all(_inside(m, pos[i], pos[i + 1]) for i in range(0, 8, 2)):
            raise EditError("o móvel precisa ficar dentro do mapa")
        items = m.setdefault("furniture", [])
        if len(items) >= MAX_FURNITURE:
            raise EditError(f"limite de {MAX_FURNITURE} móveis")
        items.append({"update": 1, "id": _next_id(items, 1000), "type": t, "pos": pos})
    elif kind == "move_furniture":
        f = _find(m.get("furniture", []), op.get("id"), "móvel")
        dx, dy = round(_num(op, "dx")), round(_num(op, "dy"))
        pos = [v + (dx if i % 2 == 0 else dy) for i, v in enumerate(f["pos"])]
        if not all(_inside(m, pos[i], pos[i + 1]) for i in range(0, len(pos), 2)):
            raise EditError("o móvel sairia do mapa")
        f["pos"], f["update"] = pos, 1
    elif kind == "remove_furniture":
        items = m.get("furniture", [])
        items.remove(_find(items, op.get("id"), "móvel"))
    elif kind == "rename_room":
        name = str(op.get("name", "")).strip()
        if not name or len(name) > MAX_ROOM_NAME:
            raise EditError(f"nome do cômodo: 1 a {MAX_ROOM_NAME} caracteres")
        room = _find(m.get("room_attrs", []), op.get("id"), "cômodo")
        room["room_name"] = name
    else:
        raise EditError(f"operação desconhecida: {kind!r}")


def apply_ops(m: dict, ops: list[dict]) -> dict:
    """Devolve uma CÓPIA de `m` com as operações aplicadas, na ordem. Para na primeira inválida."""
    if not isinstance(ops, list) or len(ops) > 200:
        raise EditError("lista de operações inválida (máximo 200)")
    out = copy.deepcopy(m)
    for n, op in enumerate(ops, 1):
        try:
            apply_op(out, op if isinstance(op, dict) else {})
        except EditError as ex:
            raise EditError(f"operação {n}: {ex}") from None
    return out


def diff(old: dict, new: dict) -> list[str]:
    """Resumo legível do que mudou entre dois mapas (paredes, móveis, nomes de cômodos)."""
    out: list[str] = []
    ow = {w["id"]: w["wall_points"] for w in old.get("fb_walls", [])}
    nw = {w["id"]: w["wall_points"] for w in new.get("fb_walls", [])}
    out += [f"+ parede virtual {i}" for i in nw if i not in ow]
    out += [f"- parede virtual {i}" for i in ow if i not in nw]
    of = {f["id"]: f for f in old.get("furniture", [])}
    nf = {f["id"]: f for f in new.get("furniture", [])}
    out += [f"+ móvel {i} (tipo {nf[i]['type']})" for i in nf if i not in of]
    out += [f"- móvel {i} (tipo {of[i]['type']})" for i in of if i not in nf]
    out += [f"~ móvel {i} movido" for i in nf if i in of and nf[i]["pos"] != of[i]["pos"]]
    orn = {r["id"]: r.get("room_name") for r in old.get("room_attrs", [])}
    out += [f"~ cômodo {r['id']}: \"{orn.get(r['id'])}\" → \"{r.get('room_name')}\""
            for r in new.get("room_attrs", []) if r["id"] in orn and orn[r["id"]] != r.get("room_name")]
    return out
