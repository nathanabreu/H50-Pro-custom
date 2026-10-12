"""Histórico de limpezas do robô (10/3) pela NUVEM Xiaomi.

Pela LAN o 10/3 nunca chega: com 40 registros o valor tem ~2 KB (2,25 KB escapado no pacote) e o robô
não envia respostas UDP acima de ~1,4 KB (captura de 12/10: o pedido sai, o robô fica em silêncio e
volta a responder o handshake logo depois). A nuvem devolve o valor inteiro em
/miotspec/prop/get. A lista vem com cada registro DUPLICADO e é limitada a 40 itens (cerca de 20
limpezas; em 12/10: 40 itens = 21 únicas, e total_count = 22 porque a mais antiga já saiu da lista).
Por isso o app também guarda o próprio histórico: o robô só lembra as últimas ~20 limpezas.

O que o app derivou sozinho (2/17 + 2/6 + 2/7) bate com a nuvem: nas 7 limpezas comparadas em
12/10, duração, área e tipo eram idênticos. Aqui a nuvem completa o que faltou (limpezas de antes do
app, tipo de limpezas feitas com o app fechado) sem apagar nomes de rotina e zonas, que só o app guarda.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

from . import decoders
from .store import Store

log = logging.getLogger(__name__)


def import_records(store: Store, raw: str) -> dict:
    """Grava no banco os registros do 10/3 (string JSON). Idempotente. Devolve contagens."""
    data = decoders.clean_record(raw)
    unique = {}
    for r in data["records"]:
        unique.setdefault(r["stime"], r)            # a nuvem repete cada registro
    existing = {c["stime"]: c for c in store.cleanings()}
    added = updated = 0
    for stime, r in sorted(unique.items()):
        ex = existing.get(stime)
        # o rótulo do robô ("00240_4230_2_0_0") não substitui "custom:<rotina>" / "zones:<n>" do app
        label = None if ex and ex.get("raw_label") else r["raw_label"]
        store.upsert_cleaning(stime, r["duration_s"], r["area_m2"], r["sweep_type"], "robot", raw_label=label)
        if ex is None:
            added += 1
        elif ex["source"] != "robot" or ex["sweep_type"] != r["sweep_type"]:
            updated += 1
    return {"records": len(unique), "added": added, "updated": updated,
            "total_count": data["total_count"], "total_min": data["total_min"]}


def sync(service, store: Store, did) -> dict:
    """Baixa o 10/3 pela nuvem e importa. `service` = cloud.CloudService."""
    res = import_records(store, service.clean_record(did))
    log.info("histórico da nuvem: %(records)s registros, %(added)s novos, %(updated)s atualizados", res)
    return res


def start_sync(bus, service, store: Store, did_fn, first_delay: float = 20, every: float = 3600,
               stop: threading.Event | None = None, settle: float = 60) -> threading.Thread:
    """Thread que sincroniza na partida, depois de cada limpeza (com `settle` s para o robô enviar à nuvem),
    ao conectar a nuvem e a cada hora. `stop` encerra a thread (robô removido / app fechando)."""
    q = bus.subscribe()
    stop = stop or threading.Event()

    def loop():
        due = time.monotonic() + first_delay
        while not stop.is_set():
            try:
                event, payload = q.get(timeout=1.0)
            except queue.Empty:
                if time.monotonic() < due:
                    continue
                event, payload = "tick", None
            due = time.monotonic() + every
            if event not in ("tick", "cleaning", "cloud") or (payload or {}).get("source") == "cloud":
                continue
            if event == "cleaning" and stop.wait(settle):
                break
            if service.state != "ok" or not did_fn():
                continue
            try:
                res = sync(service, store, did_fn())
                if res["added"] or res["updated"]:
                    bus.publish("cleaning", {"source": "cloud"})
            except Exception as ex:  # noqa: BLE001 - a nuvem pode estar fora; tenta de novo na próxima
                log.warning("sincronização do histórico falhou: %s", ex)

    t = threading.Thread(target=loop, name="history-sync", daemon=True)
    t.start()
    return t
