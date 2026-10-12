"""Ferramenta de sondagem do H50 Pro (só biblioteca padrão).

    py -m h50console.probe dump  [--out data/dump-full.json]   lê toda a spec, item a item, com tamanho
    py -m h50console.probe scan  [--out data/scan.json]        procura piids fora da spec (só leitura)
    py -m h50console.probe calls [--out data/calls.json]       ações de consulta (get-*), sem efeito físico
    py -m h50console.probe watch [--out data/monitor.jsonl]    grava mudanças ao longo do tempo (Ctrl+C para)

Credenciais: H50_IP e H50_TOKEN (ambiente ou .env).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .miio import MiioClient, MiioDeviceError, MiioError

# spec ov42gl (xiaomi-h50-pro-hacking.md, anexo A): piids legíveis por siid
SPEC_READ = {
    1: [1, 2, 3, 4, 5],                      # device-information (não listado no anexo)
    2: [p for p in range(1, 103) if p not in (15, 24, 39, 65)],
    3: [1, 2, 3], 4: [1, 2], 5: [1, 2], 9: [1, 2],
    10: list(range(1, 16)), 11: [1, 2, 3], 12: [1, 2], 13: [1, 2], 14: [1, 2],
    15: [1, 2, 3, 4, 5, 6], 17: [1, 2], 18: [1, 2, 3, 4], 19: [1, 2],
    20: [1, 2, 3, 6, 13], 22: [1, 2],
}
# faixas a varrer fora da spec
SCAN = {2: range(103, 131), 3: range(4, 11), 4: range(3, 11), 5: range(3, 11), 6: range(1, 11),
        7: range(1, 11), 8: range(1, 11), 9: range(3, 8), 10: range(16, 31), 11: range(4, 11),
        12: range(3, 8), 13: range(3, 8), 14: range(3, 8), 16: range(1, 11), 17: range(3, 8),
        18: range(5, 11), 19: range(3, 8), 20: [4, 5, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 19, 20],
        21: range(1, 21), 22: range(3, 8), 23: range(1, 11), 24: range(1, 11), 25: range(1, 11),
        26: range(1, 11), 27: range(1, 11), 28: range(1, 11), 29: range(1, 11), 30: range(1, 11)}

# ações de CONSULTA da spec (nomes get-*/query); nenhuma move o robô nem altera ajustes
QUERY_CALLS = [
    ("2/30 get-system-info", 2, 30, []),
    ("2/10 get-zone-configs", 2, 10, []),
    ("2/11 get-room-configs (todos)", 2, 11, []),
    ("2/11 get-room-configs '3'", 2, 11, [{"piid": 15, "value": "3"}]),
    ("2/47 get-vacuum-route", 2, 47, []),
    ("15/2 get-download-status", 15, 2, []),
    ("20/1 get-history-obj", 20, 1, []),
    ("20/2 get-user-define", 20, 2, []),
    ("20/5 get-order-clean", 20, 5, []),
]

FAST = [(2, 2), (2, 3), (2, 96), (2, 89), (2, 6), (2, 7), (3, 1), (3, 2), (2, 18), (2, 88), (2, 90),
        (2, 97), (2, 98), (2, 4), (2, 5), (2, 11), (2, 25), (2, 26), (2, 40), (2, 43), (2, 66), (2, 67),
        (2, 72), (2, 100), (2, 101), (10, 4), (10, 12), (3, 3), (5, 2), (11, 3)]
SLOW = [(2, 17), (2, 19), (2, 42), (2, 85), (2, 86), (2, 87), (9, 1), (9, 2), (12, 1), (12, 2),
        (13, 1), (13, 2), (14, 1), (14, 2), (18, 1), (18, 4), (19, 1), (19, 2), (10, 3), (10, 15),
        (10, 13), (22, 2)]
ACTIVE = {4, 5, 6, 7, 10, 12, 13, 16, 17, 18, 19, 20, 21, 22, 24}


def load_env(path: str = ".env") -> None:
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"'))


def now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def read_one(c: MiioClient, s: int, p: int) -> dict:
    """Lê uma propriedade; devolve {code, value?, bytes, ms} ou {code:'timeout'}."""
    t0 = time.perf_counter()
    try:
        r = c.send("get_properties", [{"did": f"{s}-{p}", "siid": s, "piid": p}], retry=0)[0]
    except MiioError as ex:
        try:
            c.handshake()
        except MiioError:
            pass
        return {"code": "timeout", "err": str(ex), "ms": int((time.perf_counter() - t0) * 1000)}
    out = {"code": r.get("code"), "ms": int((time.perf_counter() - t0) * 1000)}
    if "value" in r:
        out["value"] = r["value"]
        out["bytes"] = len(json.dumps(r, ensure_ascii=False).encode())
    return out


def read_many(c: MiioClient, pairs, budget: int = 1100) -> dict:
    """Lê em lotes cujo tamanho estimado de resposta cabe no limite (~1,4 KB) do robô."""
    out: dict[str, object] = {}
    batch: list[tuple[int, int]] = []

    def flush():
        if not batch:
            return
        try:
            res = c.send("get_properties", [{"did": f"{s}-{p}", "siid": s, "piid": p} for s, p in batch], retry=0)
            for r in res:
                out[f"{r['siid']}/{r['piid']}"] = r.get("value", f"<code {r.get('code')}>")
        except MiioError:
            c.did = None
            for s, p in batch:  # cai para item a item
                r = read_one(c, s, p)
                out[f"{s}/{p}"] = r.get("value", f"<{r['code']}>")
        batch.clear()

    est = 0
    for s, p in pairs:
        size = SIZE_HINT.get((s, p), 70)
        if batch and est + size > budget:
            flush()
            est = 0
        batch.append((s, p))
        est += size
    flush()
    return out


# tamanhos aproximados (bytes) das props grandes, medidos com `dump`
SIZE_HINT = {(2, 16): 400, (2, 19): 330, (2, 42): 520, (2, 66): 120, (2, 40): 140, (10, 3): 1400,
             (10, 15): 400, (10, 13): 300, (2, 18): 90, (2, 1): 100, (22, 2): 400}


def cmd_dump(c, args):
    res = {}
    for s, ps in SPEC_READ.items():
        for p in ps:
            res[f"{s}/{p}"] = read_one(c, s, p)
            print(f"{s}/{p}: {res[f'{s}/{p}'].get('code')} {res[f'{s}/{p}'].get('bytes', '')}", file=sys.stderr)
    return {"ts": now(), "props": res}


def cmd_scan(c, args):
    found = {}
    for s, ps in SCAN.items():
        for p in ps:
            r = read_one(c, s, p)
            if r.get("code") not in (-4001, -4003, -4004, -4005, -704040003):
                found[f"{s}/{p}"] = r
                print(f"  {s}/{p}: {r}", file=sys.stderr)
    return {"ts": now(), "found": found}


def cmd_calls(c, args):
    res = {}
    for label, s, a, params in QUERY_CALLS:
        t0 = time.perf_counter()
        try:
            out = c.send("action", {"did": f"call-{s}-{a}", "siid": s, "aiid": a, "in": params}, retry=0)
        except MiioDeviceError as ex:
            out = {"error": str(ex)}
        except MiioError as ex:
            c.did = None
            out = {"timeout": str(ex)}
        res[label] = {"result": out, "ms": int((time.perf_counter() - t0) * 1000)}
        print(f"{label}: {json.dumps(out, ensure_ascii=False)[:200]}", file=sys.stderr)
        time.sleep(0.5)
    return {"ts": now(), "calls": res}


EXTRA = [(2, p) for p in range(103, 107)] + [(21, p) for p in range(1, 9)] + [(23, 1), (23, 2), (23, 3), (20, 4)]
ALL = [(s, p) for s, ps in SPEC_READ.items() for p in ps if (s, p) != (10, 3)] + EXTRA


def cmd_watch(c, args):
    """Grava em JSONL só o que muda. Rápido: 5 s ativo / 30 s ocioso. Lento: a cada 10 min.

    Com --all, lê TODAS as props (spec + extras) a cada ciclo: para flagrar edições feitas no app.
    """
    if args.all:
        global FAST, SLOW
        FAST, SLOW = ALL, [(10, 3)]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    last: dict[str, object] = {}
    next_slow = 0.0
    fails = 0
    with out.open("a", encoding="utf-8") as f:
        def emit(kind, **kw):
            f.write(json.dumps({"ts": now(), "kind": kind, **kw}, ensure_ascii=False) + "\n")
            f.flush()

        emit("start")
        while True:
            pairs = list(FAST)
            if time.monotonic() >= next_slow:
                pairs += SLOW
                next_slow = time.monotonic() + 600
            try:
                t0 = time.perf_counter()
                state = read_many(c, pairs)
                ms = int((time.perf_counter() - t0) * 1000)
                if fails:
                    emit("online", after_fails=fails)
                fails = 0
                changes = {k: v for k, v in state.items() if last.get(k) != v}
                if changes:
                    emit("change", ms=ms, changes={k: [last.get(k), v] for k, v in changes.items()})
                last.update(state)
                interval = 5 if last.get("2/2") in ACTIVE or args.all else 30
            except MiioError as ex:
                fails += 1
                emit("offline", fails=fails, err=str(ex))
                interval = min(300, 10 * 2 ** fails)
            time.sleep(interval)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Sondagem do H50 Pro")
    ap.add_argument("cmd", choices=["dump", "scan", "calls", "watch"])
    ap.add_argument("--out")
    ap.add_argument("--all", action="store_true", help="watch: lê todas as props a cada ciclo")
    args = ap.parse_args(argv)
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            st.reconfigure(encoding="utf-8", errors="replace")
    load_env()
    c = MiioClient(os.environ["H50_IP"], os.environ["H50_TOKEN"], timeout=4)
    if args.cmd == "watch":
        args.out = args.out or "data/monitor.jsonl"
        try:
            cmd_watch(c, args)
        except KeyboardInterrupt:
            return 0
    result = {"dump": cmd_dump, "scan": cmd_scan, "calls": cmd_calls}[args.cmd](c, args)
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"gravado em {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
