#!/usr/bin/env python3
"""
h50pro.py - controle local (LAN) do Xiaomi Robot Vacuum H50 Pro (xiaomi.vacuum.ov42gl)
via protocolo MIoT sobre miIO (UDP 54321), usando a biblioteca python-miio.

Nao precisa de root: usa o token que o proprio robo recebeu no pareamento com o app.
O robo continua ligado a nuvem Xiaomi; isto e apenas um segundo "cliente" na LAN.

Requisitos
    Python 3.11+
    py -m pip install https://github.com/rytilahti/python-miio/archive/refs/heads/master.zip

Credenciais (uma das duas formas)
    --ip 192.168.x.y --token <32 hex>
    variaveis de ambiente H50_IP e H50_TOKEN

Exemplos
    python h50pro.py status
    python h50pro.py clean-rooms 3,4
    python h50pro.py suction max
    python h50pro.py get 2 89                 # progresso da limpeza
    python h50pro.py action 2 16 '["3,4"]'    # mesma coisa que clean-rooms
    python h50pro.py scan 21 1 30             # procura piids nao documentados no siid 21

Mapa siid/piid/aiid: https://home.miot-spec.com/spec/xiaomi.vacuum.ov42gl
(urn:miot-spec-v2:device:vacuum:0000A006:xiaomi-ov42gl:2)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

MODEL = "xiaomi.vacuum.ov42gl"

# ---------------------------------------------------------------------------
# Enums da spec (siid 2 = vacuum, 3 = battery)
# ---------------------------------------------------------------------------
STATUS = {
    1: "Standby", 2: "Carregando", 3: "Carga p/ retomar", 4: "Limpando", 5: "Pausado",
    6: "Voltando p/ base", 7: "Lavando mop", 8: "Controle remoto", 9: "Carga completa",
    10: "Mapeando", 11: "Atualizando firmware", 12: "Base trabalhando (limpeza)",
    13: "Trocando tarefa", 14: "Base trabalhando (carga)", 15: "Anormal",
    16: "Aspirando e passando pano", 17: "Passando pano", 18: "Mapeamento pausado",
    19: "Retorno p/ retomar", 20: "Retorno no meio da rota", 21: "Retorno do mapeamento",
    22: "Enxague auxiliar da base", 23: "Lavagem auxiliar concluida", 24: "Voltando p/ carregar",
}
SWEEP_MOP_TYPE = {1: "so aspirar", 2: "so pano", 3: "aspirar + pano", 4: "aspirar depois pano"}
SWEEP_TYPE = {
    1: "casa toda", 2: "zona", 3: "comodos", 4: "bordas", 5: "personalizada", 6: "ponto",
    7: "personalizada (sweep)", 8: "agendada", 9: "vinculada", 10: "mapeamento rapido",
    11: "AI gerenciada",
}
SUCTION = {1: "quiet", 2: "standard", 3: "strong", 4: "max"}
WATER = {0: "off", 1: "1", 2: "2", 3: "3"}
CHARGING = {1: "carregando", 2: "nao carregando", 3: "nao carregavel"}

# nome -> (siid, piid, enum|None, unidade)
STATUS_PROPS = {
    "status": (2, 2, STATUS, ""),
    "fault": (2, 3, None, ""),
    "modo": (2, 4, SWEEP_MOP_TYPE, ""),
    "tipo_limpeza": (2, 5, SWEEP_TYPE, ""),
    "area_limpa_m2": (2, 6, None, "x0.01"),
    "tempo_limpeza": (2, 7, None, ""),
    "passadas": (2, 8, None, ""),
    "succao": (2, 9, SUCTION, ""),
    "agua_mop": (2, 10, WATER, ""),
    "progresso_%": (2, 89, None, ""),
    "bateria_%": (3, 1, None, ""),
    "carga": (3, 2, CHARGING, ""),
    "mapa_atual": (10, 6, None, ""),
}
CONSUMABLE_PROPS = {
    "escova_principal_%": (12, 1, None, ""),
    "escova_principal_h": (12, 2, None, ""),
    "escova_lateral_%": (13, 1, None, ""),
    "escova_lateral_h": (13, 2, None, ""),
    "filtro_%": (14, 1, None, ""),
    "filtro_h": (14, 2, None, ""),
    "mop_%": (9, 1, None, ""),
    "mop_h": (9, 2, None, ""),
    "saco_po_%": (19, 1, None, ""),
    "saco_po_h": (19, 2, None, ""),
    "detergente_%": (18, 1, None, ""),
}
# Todas as propriedades legiveis (R) da spec, para o comando "dump"
READABLE = {
    2: list(range(1, 24)) + [25, 26, 27] + list(range(28, 39)) + list(range(40, 65))
       + list(range(66, 103)),
    3: [1, 2, 3], 4: [1, 2], 5: [1, 2], 9: [1, 2],
    10: [1, 2, 3, 4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15],
    11: [1, 2, 3], 12: [1, 2], 13: [1, 2], 14: [1, 2],
    15: [1, 2, 3, 4], 17: [2], 18: [1, 2, 3, 4], 19: [1, 2],
    20: [3, 6, 13], 22: [2],
}
READABLE[2].remove(15)  # vacuum-room-ids nao tem acesso de leitura na spec

# Acoes simples: comando -> (siid, aiid, descricao)
SIMPLE_ACTIONS = {
    "start": (2, 1, "inicia limpeza (modo atual)"),
    "stop": (2, 2, "para"),
    "home": (2, 3, "para e volta para a base"),
    "sweep": (2, 4, "so aspirar"),
    "mop": (2, 5, "so pano"),
    "sweep-mop": (2, 6, "aspirar + pano"),
    "pause": (2, 7, "pausa"),
    "resume": (2, 8, "continua"),
    "build-map": (2, 17, "mapeamento rapido"),
    "dust": (2, 18, "esvazia o po na base"),
    "wash-mop": (2, 19, "lava o mop"),
    "dry": (2, 20, "seca o mop"),
    "stop-wash": (2, 31, "para lavagem do mop"),
    "stop-dry": (2, 32, "para secagem"),
    "sweep-then-mop": (2, 50, "aspira primeiro, depois pano"),
    "spot": (2, 59, "limpeza pontual"),
    "self-clean-base": (2, 63, "autolimpeza da base"),
    "charge": (3, 1, "volta para carregar"),
    "locate": (6, 1, "robo responde (identify)"),
}


def _norm(text: str) -> str:
    """minusculas e sem acento: 'Criança' -> 'crianca'."""
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def _parse_value(raw: str):
    """Converte texto da linha de comando em bool/int/float/str."""
    low = raw.lower()
    if low in ("true", "on"):
        return True
    if low in ("false", "off"):
        return False
    for conv in (int, float):
        try:
            return conv(raw)
        except ValueError:
            pass
    return raw


class H50Pro:
    def __init__(self, ip: str, token: str, timeout: int = 5, debug: bool = False):
        from miio import Device  # import tardio: --help funciona sem python-miio

        self.dev = Device(ip, token, timeout=timeout, model=MODEL, debug=int(debug))

    # -- primitivas MIoT ----------------------------------------------------
    def get(self, pairs: list[tuple[int, int]], chunk: int = 10, retry_count: int | None = None) -> list[dict]:
        out: list[dict] = []
        for i in range(0, len(pairs), chunk):
            req = [{"did": f"{s}-{p}", "siid": s, "piid": p} for s, p in pairs[i : i + chunk]]
            out.extend(self.dev.send("get_properties", req, retry_count=retry_count))
        return out

    def get_tolerant(self, pairs: list[tuple[int, int]], chunk: int = 5, progress: bool = True) -> list[dict]:
        """Le em lotes pequenos; se um lote nao responder, le item a item e segue em frente.

        O robo ignora alguns lotes (resposta grande demais para o buffer UDP de 4 KB do
        python-miio, ou piid que ele nao atende). Assim o dump nao para no primeiro erro.
        """
        from miio.exceptions import DeviceException

        out: list[dict] = []
        for i in range(0, len(pairs), chunk):
            batch = pairs[i : i + chunk]
            label = f"{batch[0][0]}/{batch[0][1]}..{batch[-1][0]}/{batch[-1][1]}"
            try:
                out.extend(self.get(batch, chunk=chunk, retry_count=1))
                if progress:
                    print(f"  ok      {label}", file=sys.stderr)
            except DeviceException:
                if progress:
                    print(f"  lote {label} sem resposta, lendo um a um...", file=sys.stderr)
                for s, p in batch:
                    try:
                        out.extend(self.get([(s, p)], retry_count=1))
                    except DeviceException:
                        out.append({"siid": s, "piid": p, "code": "sem resposta"})
                        if progress:
                            print(f"  falhou  {s}/{p}", file=sys.stderr)
        return out

    def rooms(self) -> dict:
        r = self.get([(2, 16)])[0]
        if r.get("code") != 0:
            raise RuntimeError(f"room-information retornou code {r.get('code')}")
        return json.loads(r["value"])

    def resolve_rooms(self, spec: str) -> str:
        """Aceita ids ('3,4') ou nomes ('cozinha,banheiro', sem acento) e devolve '6,7'."""
        parts = [x.strip() for x in spec.split(",") if x.strip()]
        if all(x.isdigit() for x in parts):
            return ",".join(parts)
        rooms = self.rooms().get("rooms", [])
        ids = []
        for part in parts:
            if part.isdigit():
                ids.append(part)
                continue
            want = _norm(part)
            match = ([r for r in rooms if _norm(r["name"]) == want]
                     or [r for r in rooms if _norm(r["name"]).startswith(want)]
                     or [r for r in rooms if want in _norm(r["name"])])
            if len(match) != 1:
                names = ", ".join(f"{r['id']}={r['name']}" for r in rooms)
                raise ValueError(f"comodo '{part}' nao encontrado ou ambiguo. Disponiveis: {names}")
            ids.append(str(match[0]["id"]))
        return ",".join(ids)

    def set(self, siid: int, piid: int, value):
        return self.dev.send(
            "set_properties", [{"did": f"set-{siid}-{piid}", "siid": siid, "piid": piid, "value": value}]
        )

    def action(self, siid: int, aiid: int, params: list | None = None):
        return self.dev.send(
            "action", {"did": f"call-{siid}-{aiid}", "siid": siid, "aiid": aiid, "in": params or []}
        )

    def info(self):
        return self.dev.send("miIO.info")

    # -- leitura amigavel ---------------------------------------------------
    def read_named(self, table: dict) -> dict:
        pairs = [(s, p) for s, p, _, _ in table.values()]
        by_key = {(r.get("siid"), r.get("piid")): r for r in self.get(pairs)}
        result = {}
        for name, (s, p, enum, _unit) in table.items():
            r = by_key.get((s, p), {})
            if r.get("code", -1) != 0:
                result[name] = f"<erro {r.get('code')}>"
                continue
            v = r.get("value")
            if enum and v in enum:
                v = f"{v} ({enum[v]})"
            if name == "area_limpa_m2" and isinstance(v, int):
                v = round(v / 100, 2)
            result[name] = v
        return result


def _print(data, as_json: bool):
    if as_json or not isinstance(data, dict):
        print(json.dumps(data, ensure_ascii=False, indent=2, default=str))
        return
    width = max(len(k) for k in data) if data else 0
    for k, v in data.items():
        print(f"{k.ljust(width)}  {v}")


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description=f"Controle local do Xiaomi H50 Pro ({MODEL}) via MIoT/UDP 54321",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Acoes simples: "
        + ", ".join(f"{k} ({v[2]})" for k, v in SIMPLE_ACTIONS.items()),
    )
    ap.add_argument("--ip", default=os.environ.get("H50_IP"))
    ap.add_argument("--token", default=os.environ.get("H50_TOKEN"))
    ap.add_argument("--timeout", type=int, default=5)
    ap.add_argument("--json", action="store_true", help="saida em JSON")
    ap.add_argument("--debug", action="store_true", help="mostra pacotes miIO")
    # --json tambem aceito DEPOIS do comando (ex.: "dump --json")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                        help="saida em JSON")
    sub = ap.add_subparsers(dest="cmd", required=True)
    _orig_add_parser = sub.add_parser

    def _add_parser(name, **kw):
        kw.setdefault("parents", [common])
        return _orig_add_parser(name, **kw)

    sub.add_parser = _add_parser  # type: ignore[method-assign]

    sub.add_parser("info", help="miIO.info (firmware, MAC, Wi-Fi)")
    sub.add_parser("status", help="estado, modo, bateria, progresso")
    sub.add_parser("consumables", help="vida util de escovas, filtro, mop, saco")
    sub.add_parser("dump", help="le TODAS as propriedades legiveis da spec")
    sub.add_parser("rooms", help="le room-information (2/16) - ids dos comodos")
    for name, (_s, _a, desc) in SIMPLE_ACTIONS.items():
        sub.add_parser(name, help=desc)

    p = sub.add_parser("clean-rooms", help="limpa comodos: clean-rooms 3,4  ou  clean-rooms cozinha,banheiro")
    p.add_argument("ids", help="ids ou nomes separados por virgula, sem espacos (veja 'rooms')")

    p = sub.add_parser("suction", help="potencia de succao")
    p.add_argument("level", choices=list(SUCTION.values()))
    p = sub.add_parser("water", help="vazao de agua do mop")
    p.add_argument("level", choices=list(WATER.values()))
    p = sub.add_parser("mode", help="aspirar/pano (sweep-mop-type)")
    p.add_argument("mode", type=int, choices=list(SWEEP_MOP_TYPE), help=str(SWEEP_MOP_TYPE))
    p = sub.add_parser("passes", help="numero de passadas")
    p.add_argument("n", type=int, choices=[1, 2, 3])
    p = sub.add_parser("volume", help="volume da voz 0-100")
    p.add_argument("value", type=int)

    p = sub.add_parser("get", help="le siid/piid")
    p.add_argument("siid", type=int)
    p.add_argument("piid", type=int)
    p = sub.add_parser("set", help="escreve siid/piid (true/false/int/float/str)")
    p.add_argument("siid", type=int)
    p.add_argument("piid", type=int)
    p.add_argument("value")
    p = sub.add_parser("action", help="executa siid/aiid; params em JSON (lista)")
    p.add_argument("siid", type=int)
    p.add_argument("aiid", type=int)
    p.add_argument("params", nargs="?", default="[]")
    p = sub.add_parser("scan", help="procura piids que respondem em um siid")
    p.add_argument("siid", type=int)
    p.add_argument("first", type=int)
    p.add_argument("last", type=int)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.ip or not args.token:
        print("Informe --ip e --token (ou H50_IP / H50_TOKEN).", file=sys.stderr)
        return 2
    if len(args.token) != 32:
        print("O token deve ter 32 caracteres hexadecimais.", file=sys.stderr)
        return 2

    for stream in (sys.stdout, sys.stderr):  # acentos ok no console e em "> arquivo.json"
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    vac = H50Pro(args.ip, args.token, timeout=args.timeout, debug=args.debug)
    cmd = args.cmd

    if cmd == "info":
        res = vac.info()
    elif cmd == "status":
        res = vac.read_named(STATUS_PROPS)
    elif cmd == "consumables":
        res = vac.read_named(CONSUMABLE_PROPS)
    elif cmd == "dump":
        pairs = [(s, p) for s, ps in READABLE.items() for p in ps]
        print(f"Lendo {len(pairs)} propriedades (o progresso aparece aqui)...", file=sys.stderr)
        res = {f"{r['siid']}/{r['piid']}": r.get("value", f"<erro {r.get('code')}>")
               for r in vac.get_tolerant(pairs)}
    elif cmd == "rooms":
        data = vac.rooms()
        if args.json:
            res = data
        else:
            res = {f"id {r['id']}": r["name"] for r in data.get("rooms", [])}
            res["map_uid"] = data.get("map_uid")
    elif cmd in SIMPLE_ACTIONS:
        s, a, _ = SIMPLE_ACTIONS[cmd]
        res = vac.action(s, a)
    elif cmd == "clean-rooms":
        ids = vac.resolve_rooms(args.ids)
        print(f"Limpando comodos {ids}", file=sys.stderr)
        res = vac.action(2, 16, [ids])
    elif cmd == "suction":
        level = {v: k for k, v in SUCTION.items()}[args.level]
        res = vac.set(2, 9, level)
    elif cmd == "water":
        level = {v: k for k, v in WATER.items()}[args.level]
        res = vac.set(2, 10, level)
    elif cmd == "mode":
        res = vac.set(2, 4, args.mode)
    elif cmd == "passes":
        res = vac.set(2, 8, args.n)
    elif cmd == "volume":
        res = vac.set(4, 2, max(0, min(100, args.value)))
    elif cmd == "get":
        res = vac.get([(args.siid, args.piid)])
    elif cmd == "set":
        res = vac.set(args.siid, args.piid, _parse_value(args.value))
    elif cmd == "action":
        params = json.loads(args.params)
        if not isinstance(params, list):
            params = [params]
        res = vac.action(args.siid, args.aiid, params)
    elif cmd == "scan":
        found = [r for r in vac.get_tolerant([(args.siid, p) for p in range(args.first, args.last + 1)])
                 if r.get("code") == 0]
        res = {f"{r['siid']}/{r['piid']}": r.get("value") for r in found} or "nenhum piid respondeu"
    else:  # pragma: no cover - argparse ja valida
        return 2

    _print(res, args.json)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except ImportError:
        print("python-miio nao encontrado. Instale com:\n  py -m pip install "
              "https://github.com/rytilahti/python-miio/archive/refs/heads/master.zip", file=sys.stderr)
        sys.exit(1)
    except Exception as ex:  # DeviceException, DeviceError, timeouts
        name = type(ex).__name__
        print(f"{name}: {ex}", file=sys.stderr)
        if name in ("DeviceException", "DeviceInfoUnavailableException") or "timed out" in str(ex).lower():
            print("Dica: confira IP, token (32 hex) e se o PC esta na mesma rede/VLAN do robo "
                  "(UDP 54321).", file=sys.stderr)
        sys.exit(1)
