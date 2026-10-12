"""Notificações: ntfy, Telegram e webhook (só urllib, sem dependências).

Eventos (por canal você escolhe quais quer): limpeza concluída, falha, tanque de água suja cheio, tanque de água
limpa vazio, consumível acabando (< 10 %), robô sem resposta por 2 min e robô de volta.
Os segredos (tópico do ntfy, token do Telegram, URL do webhook) ficam em <data>/notify.json (0600) e a API nunca
os devolve inteiros. Mensagens iguais são agrupadas: 10 min entre repetições (24 h para consumíveis).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from . import catalog

log = logging.getLogger(__name__)

EVENTS = {
    "cleaning_done": "Limpeza concluída",
    "fault": "Falha do robô",
    "tank_dirty": "Tanque de água suja cheio",
    "tank_clean": "Tanque de água limpa vazio",
    "consumable_low": "Consumível acabando (menos de 10 %)",
    "offline": "Robô sem resposta (2 min)",
    "online": "Robô voltou a responder",
}
TYPES = {"ntfy": "ntfy (app no celular)", "telegram": "Telegram", "webhook": "Webhook (JSON)"}
OFFLINE_AFTER = 120
REPEAT_AFTER = 600
CONSUMABLE_REPEAT = 24 * 3600
CONSUMABLE_NAMES = {"mop": "Mop", "main_brush": "Escova principal", "side_brush": "Escova lateral",
                    "filter": "Filtro", "detergent": "Detergente", "dust_bag": "Saco de pó"}


class NotifyError(Exception):
    pass


# -- envio ------------------------------------------------------------------------------------------------------
def _post_json(url: str, payload: dict, timeout: float = 10.0) -> None:
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "h50console"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        r.read()


def send(channel: dict, title: str, text: str, event: str = "test", robot: str = "") -> None:
    """Envia por um canal. Lança NotifyError com a causa."""
    kind = channel.get("type")
    try:
        if kind == "ntfy":
            u = urlparse(channel["url"])
            topic = u.path.strip("/")
            if not topic:
                raise NotifyError("o endereço do ntfy precisa do tópico, ex.: https://ntfy.sh/meu-topico-secreto")
            _post_json(f"{u.scheme}://{u.netloc}/", {"topic": topic, "title": title, "message": text,
                                                    "priority": 4 if event in ("fault", "offline") else 3,
                                                    "tags": ["robot"]})
        elif kind == "telegram":
            _post_json(f"https://api.telegram.org/bot{channel['token']}/sendMessage",
                       {"chat_id": channel["chat_id"], "text": f"{title}\n{text}"})
        elif kind == "webhook":
            _post_json(channel["url"], {"event": event, "robot": robot, "title": title, "text": text,
                                        "ts": int(time.time())})
        else:
            raise NotifyError(f"tipo de canal desconhecido: {kind}")
    except NotifyError:
        raise
    except KeyError as ex:
        raise NotifyError(f"canal incompleto: falta {ex.args[0]}") from ex
    except Exception as ex:  # noqa: BLE001 - rede, HTTP, certificado...
        raise NotifyError(str(ex)) from ex


# -- configuração -----------------------------------------------------------------------------------------------------
def _mask(value: str) -> str:
    return "" if not value else (value[:4] + "…" + value[-3:] if len(value) > 10 else "…")


class NotifyStore:
    SECRETS = ("url", "token")

    def __init__(self, path: Path):
        self.path = Path(path)
        self.lock = threading.Lock()
        try:
            self.channels: list[dict] = json.loads(self.path.read_text(encoding="utf-8")).get("channels", [])
        except (OSError, ValueError):
            self.channels = []

    def public(self) -> list[dict]:
        """Canais sem os segredos inteiros (só o suficiente para reconhecer)."""
        out = []
        for c in self.channels:
            p = {k: v for k, v in c.items() if k not in self.SECRETS}
            p["url_hint"] = _mask(c.get("url", ""))
            p["has_token"] = bool(c.get("token"))
            out.append(p)
        return out

    def replace(self, incoming: list[dict]) -> None:
        """Substitui a lista. Segredo em branco/ausente mantém o que já existia para o mesmo id."""
        old = {c["id"]: c for c in self.channels}
        new = []
        for c in incoming:
            kind = c.get("type")
            if kind not in TYPES:
                raise NotifyError(f"tipo inválido: {kind}")
            events = [e for e in c.get("events", []) if e in EVENTS]
            if not events:
                raise NotifyError("escolha pelo menos um evento")
            cid = c.get("id") or secrets.token_hex(4)
            prev = old.get(cid, {})
            ch = {"id": cid, "name": str(c.get("name") or TYPES[kind])[:40], "type": kind,
                  "enabled": bool(c.get("enabled", True)), "events": events,
                  "url": str(c.get("url") or prev.get("url") or "").strip(),
                  "token": str(c.get("token") or prev.get("token") or "").strip(),
                  "chat_id": str(c.get("chat_id") or prev.get("chat_id") or "").strip()}
            if kind in ("ntfy", "webhook"):
                if urlparse(ch["url"]).scheme not in ("http", "https") or not urlparse(ch["url"]).netloc:
                    raise NotifyError("informe o endereço completo (http:// ou https://)")
            if kind == "telegram" and not (ch["token"] and ch["chat_id"]):
                raise NotifyError("Telegram precisa do token do bot e do chat_id")
            new.append(ch)
        with self.lock:
            self.channels = new
            tmp = self.path.with_suffix(".tmp")
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({"channels": new}, ensure_ascii=False, indent=1), encoding="utf-8")
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            tmp.replace(self.path)

    def get(self, cid: str) -> dict:
        for c in self.channels:
            if c["id"] == cid:
                return c
        raise NotifyError("canal não encontrado")


# -- gatilhos ------------------------------------------------------------------------------------------------------------
class Notifier:
    def __init__(self, store: NotifyStore, sender=send, clock=time.time):
        self.store = store
        self.sender = sender
        self.clock = clock
        self._last: dict[tuple, float] = {}
        self._offline_since: dict[str, float] = {}
        self._offline_sent: set[str] = set()
        self._stop = threading.Event()
        self._lock = threading.Lock()

    # -- envio com agrupamento ------------------------------------------------------------------------------------
    def emit(self, robot, key: str, event: str, text: str, repeat: float = REPEAT_AFTER) -> int:
        """Manda para os canais que querem este evento. Devolve quantos enviou."""
        channels = [c for c in list(self.store.channels) if c.get("enabled", True) and event in c.get("events", [])]
        if not channels:
            return 0                                    # ninguém quer este evento: não gasta o agrupamento
        now = self.clock()
        with self._lock:
            token = (robot.cfg.id, key)
            if now - self._last.get(token, -1e12) < repeat:
                return 0
            self._last[token] = now
        title = f"{robot.cfg.name}: {EVENTS[event]}"
        sent = 0
        for ch in channels:
            try:
                self.sender(ch, title, text, event, robot.cfg.name)
                sent += 1
            except NotifyError as ex:
                log.warning("notificação (%s) falhou: %s", ch.get("name"), ex)
        return sent

    # -- eventos do robô -------------------------------------------------------------------------------------------------
    def on_event(self, robot, name: str, data) -> None:
        data = data or {}
        if name == "cleaning" and data.get("source") != "cloud":
            rows = robot.store.cleanings()
            if rows:
                r = rows[0]
                area = f"{r['area_m2']:.1f}".replace(".", ",") if r["area_m2"] else "?"
                self.emit(robot, f"clean:{r['stime']}", "cleaning_done",
                          f"{area} m² em {round((r['duration_s'] or 0) / 60)} min")
        elif name == "fault":
            codes = data.get("codes") or []
            self.emit(robot, f"fault:{codes}", "fault", "código(s) " + ", ".join(map(str, codes)))
        elif name == "state":
            ch = data.get("changes") or {}
            if ch.get("2/97") == 1:
                self.emit(robot, "tank_dirty", "tank_dirty", "Esvazie o tanque de água suja da base.")
            if ch.get("2/98") == 1:
                self.emit(robot, "tank_clean", "tank_clean", "Encha o tanque de água limpa da base.")
            for item, (pct, _hours) in catalog.CONSUMABLE_PROPS.items():
                if isinstance(ch.get(pct), int) and ch[pct] < 10:
                    self.emit(robot, f"low:{item}", "consumable_low", f"{CONSUMABLE_NAMES[item]}: {ch[pct]} %", CONSUMABLE_REPEAT)
        elif name == "offline":
            self._offline_since.setdefault(robot.cfg.id, self.clock())
        elif name == "online":
            self._offline_since.pop(robot.cfg.id, None)
            if robot.cfg.id in self._offline_sent:
                self._offline_sent.discard(robot.cfg.id)
                self.emit(robot, "online", "online", "O robô respondeu de novo.", 0)

    def tick(self, robot) -> None:
        """Confere o tempo sem resposta (chamado a cada poucos segundos)."""
        since = self._offline_since.get(robot.cfg.id)
        if since is not None and robot.cfg.id not in self._offline_sent and self.clock() - since >= OFFLINE_AFTER:
            self._offline_sent.add(robot.cfg.id)
            self.emit(robot, "offline", "offline", f"Sem resposta há {int((self.clock() - since) // 60)} min. Confira o Wi-Fi e a energia.")

    # -- threads ------------------------------------------------------------------------------------------------------------
    def watch(self, robot) -> None:
        q = robot.bus.subscribe()

        def loop():
            while not self._stop.is_set() and robot.fleet.robots.get(robot.cfg.id) is robot:   # robô removido/recarregado: encerra
                try:
                    name, data = q.get(timeout=5)
                except Exception:  # noqa: BLE001 - fila vazia: aproveita para conferir o relógio
                    self.tick(robot)
                    continue
                try:
                    self.on_event(robot, name, data)
                except Exception:  # noqa: BLE001 - notificação nunca derruba o app
                    log.exception("erro tratando evento %s", name)

        threading.Thread(target=loop, name=f"notify-{robot.cfg.id}", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
