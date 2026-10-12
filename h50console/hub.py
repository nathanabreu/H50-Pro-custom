"""Hub: roteia a API. Rotas da CONTA (robôs, nuvem, descoberta) e rotas por robô (/api/r/<id>/...).

Rotas sem prefixo de robô que não são da conta (ex.: /api/state) valem para o primeiro robô, o que mantém
compatibilidade com a versão de um robô só. Segredos (tokens, sessão da nuvem) nunca saem por aqui.
"""

from __future__ import annotations

import logging
import re

import platform
import sys
import time

from . import __version__, backup, catalog, maint, notify
from .events import EventBus
from .fleet import SUPPORTED_MODELS, Fleet, RobotConfig, TRANSPORTS
from .miio import MiioClient, MiioError, discover as lan_discover
from .web import ApiError, App, Raw

log = logging.getLogger(__name__)
ROBOT_PATH = re.compile(r"/api/r/([\w.-]+)(/.*)?")


class Hub:
    def __init__(self, fleet: Fleet, cloud, raw_enabled: bool = False, version: str = __version__,
                 auth=None, ring=None, notifier=None):
        self.auth = auth
        self.notifier = notifier                  # notify.Notifier (ntfy/Telegram/webhook)
        self.ring = ring                          # maint.RingLog: últimas mensagens de log
        self.started = time.time()
        self.fleet = fleet
        self.cloud = cloud
        self.raw_enabled = raw_enabled
        self.version = version
        self.bus = EventBus()                     # eventos da conta (nuvem, frota)
        for robot in fleet.robots.values():
            self.attach(robot)
        self.routes = [
            ("GET", r"/api/app", self.app_info),
            ("GET", r"/api/robots", self.list_robots),
            ("POST", r"/api/robots", self.add_robot),
            ("GET", r"/api/robots/discover", self.discover),
            ("PUT", r"/api/robots/([\w.-]+)", self.update_robot),
            ("DELETE", r"/api/robots/([\w.-]+)", self.remove_robot),
            ("POST", r"/api/robots/([\w.-]+)/test", self.test_robot),
            ("POST", r"/api/robots/([\w.-]+)/locate", self.locate_robot),
            ("GET", r"/api/notify", self.notify_get),
            ("PUT", r"/api/notify", self.notify_put),
            ("POST", r"/api/notify/test", self.notify_test),
            ("GET", r"/api/maintenance/status", self.maint_status),
            ("PUT", r"/api/maintenance/retention", self.maint_retention),
            ("POST", r"/api/maintenance/optimize", self.maint_optimize),
            ("POST", r"/api/maintenance/purge", self.maint_purge),
            ("GET", r"/api/maintenance/logs", self.maint_logs),
            ("GET", r"/api/maintenance/support", self.maint_support),
            ("POST", r"/api/backup/create", self.backup_create),
            ("POST", r"/api/backup/restore", self.backup_restore),
            ("GET", r"/api/cloud/status", self.cloud_status),
            ("POST", r"/api/cloud/qr", self.cloud_qr),
            ("POST", r"/api/cloud/logout", self.cloud_logout),
            ("GET", r"/api/cloud/devices", self.cloud_devices),
        ]

    def attach(self, robot) -> None:
        robot.app = App(robot.gw, robot.store, self.raw_enabled, robot.cfg.name, self.cloud, robot=robot)
        if self.notifier:
            self.notifier.watch(robot)

    # -- roteamento -------------------------------------------------------------------------------
    def robot(self, rid: str):
        try:
            return self.fleet.get(rid)
        except KeyError:
            raise ApiError(404, f"robô {rid} não existe") from None

    def robot_bus(self, rid: str) -> EventBus:
        return self.robot(rid).bus

    def dispatch(self, method: str, path: str, query: dict, body):
        for m, pattern, fn in self.routes:
            match = re.fullmatch(pattern, path)
            if match and m == method:
                return fn(*match.groups(), query=query, body=body)
        match = ROBOT_PATH.fullmatch(path)
        if match:
            return self.robot(match.group(1)).app.dispatch(method, "/api" + (match.group(2) or ""), query, body)
        if any(re.fullmatch(p, path) for _, p, _ in self.routes):
            raise ApiError(405, "método não permitido")
        default = self.fleet.default()                         # compatibilidade: rota de robô sem prefixo
        if default is None:
            raise ApiError(409, "nenhum robô configurado: adicione um robô na aba Robôs")
        return default.app.dispatch(method, path, query, body)

    # -- conta ----------------------------------------------------------------------------------------
    def app_info(self, **_):
        return {"version": self.version, "raw_enabled": self.raw_enabled, "robots": self.fleet.summaries(),
                "cloud": self.cloud.status() if self.cloud else {"state": "none"},
                "onboarding": not self.fleet.robots}

    def list_robots(self, **_):
        return self.fleet.summaries()

    # -- notificações ---------------------------------------------------------------------------------------
    def _need_notifier(self):
        if self.notifier is None:
            raise ApiError(503, "notificações desligadas")
        return self.notifier

    def notify_get(self, **_):
        n = self._need_notifier()
        return {"channels": n.store.public(), "events": notify.EVENTS, "types": notify.TYPES}

    def notify_put(self, body, **_):
        n = self._need_notifier()
        try:
            n.store.replace((body or {}).get("channels") or [])
        except notify.NotifyError as ex:
            raise ApiError(400, str(ex)) from ex
        return {"channels": n.store.public(), "events": notify.EVENTS, "types": notify.TYPES}

    def notify_test(self, body, **_):
        n = self._need_notifier()
        try:
            ch = n.store.get(str((body or {}).get("id", "")))
        except notify.NotifyError as ex:
            raise ApiError(404, str(ex)) from ex
        try:
            n.sender(ch, "H50 Console: teste", "Se você está lendo isto, o canal funciona.", "test", "")
        except notify.NotifyError as ex:
            return {"ok": False, "error": str(ex)}
        return {"ok": True}

    # -- manutenção e backup -------------------------------------------------------------------------------
    def maint_status(self, **_):
        robots = [maint.db_stats(r) for r in self.fleet.robots.values()]
        return {"version": self.version, "python": sys.version.split()[0], "platform": platform.platform(),
                "uptime_s": int(time.time() - self.started), "data_dir": str(self.fleet.data_dir.resolve()),
                "data_bytes": maint.dir_size(self.fleet.data_dir),
                "retention_days": self.fleet.settings.get("retention_days", 90), "robots": robots,
                "cloud": self.cloud.state if self.cloud else "none"}

    def maint_retention(self, body, **_):
        try:
            days = int((body or {}).get("days"))
        except (TypeError, ValueError):
            raise ApiError(400, "informe os dias (número)") from None
        if not 7 <= days <= 3650:
            raise ApiError(400, "a retenção deve ficar entre 7 e 3650 dias")
        self.fleet.settings.set("retention_days", days)
        return {"retention_days": days}

    def maint_optimize(self, **_):
        return [maint.optimize(r) for r in self.fleet.robots.values()]

    def maint_purge(self, **_):
        days = int(self.fleet.settings.get("retention_days", 90))
        return [maint.purge(r, days) for r in self.fleet.robots.values()]

    def maint_logs(self, query, **_):
        n = max(1, min(500, int(query.get("n", [200])[0])))
        return self.ring.tail(n) if self.ring else []

    def maint_support(self, **_):
        return Raw(maint.bundle_json(self, self.ring, self.version), "application/json; charset=utf-8",
                   "h50console-diagnostico.json")

    def backup_create(self, body, **_):
        body = body or {}
        try:
            blob = backup.create(self.fleet, str(body.get("passphrase", "")), include_cloud=bool(body.get("include_cloud", True)),
                                 app_version=self.version)
        except backup.BackupError as ex:
            raise ApiError(400, str(ex)) from ex
        return Raw(blob, "application/octet-stream", f"h50console-{time.strftime('%Y%m%d-%H%M%S')}.h50bak")

    def backup_restore(self, body, **_):
        try:
            files = backup.read(body["data"], body["passphrase"])
        except backup.BackupError as ex:
            raise ApiError(400, str(ex)) from ex
        res = backup.apply(self.fleet, files)
        for r in self.fleet.robots.values():
            self.attach(r)
        if self.auth:
            self.auth.reload()
        if self.cloud:
            self.cloud.reload()
        self.bus.publish("robots", {"restored": True})
        return res

    # -- nuvem ----------------------------------------------------------------------------------------
    def _need_cloud(self):
        if self.cloud is None:
            raise ApiError(503, "módulo de nuvem desligado")
        return self.cloud

    def cloud_status(self, **_):
        return self._need_cloud().status()

    def cloud_qr(self, **_):
        def done(status):
            self.bus.publish("cloud", status)
            for r in self.fleet.robots.values():            # dispara a sincronização do histórico
                r.bus.publish("cloud", status)
        return self._need_cloud().start_qr(on_done=done)

    def cloud_logout(self, **_):
        return self._need_cloud().logout()

    def cloud_devices(self, **_):
        from .cloud import CloudError
        try:
            return self._need_cloud().devices()
        except (CloudError, FileNotFoundError) as ex:
            raise ApiError(502, str(ex)) from ex

    # -- descoberta e cadastro ---------------------------------------------------------------------------
    def _near_ip(self) -> str | None:
        r = self.fleet.default()
        return r.cfg.ip if r and r.cfg.ip else None

    def discover(self, **_):
        """Aparelhos da conta Xiaomi (com token) + os que respondem na rede local (só DID e IP)."""
        lan = lan_discover(timeout=3, near_ip=self._near_ip())          # {did(int): ip}
        devices: dict[str, dict] = {}
        cloud_error = None
        if self.cloud and self.cloud.state == "ok":
            try:
                for d in self.cloud.devices():
                    if ".vacuum." in (d.get("model") or ""):
                        devices[d["did"]] = {**d, "source": "conta"}
            except Exception as ex:  # noqa: BLE001
                cloud_error = str(ex)
        for did, ip in lan.items():
            item = devices.setdefault(str(did), {"did": str(did), "name": None, "model": None, "has_token": False,
                                                 "source": "rede"})
            item["lan_ip"] = ip
        added = {r.cfg.did for r in self.fleet.robots.values() if r.cfg.did}
        out = []
        for item in devices.values():
            item["added"] = item["did"] in added
            item["supported"] = item.get("model") in SUPPORTED_MODELS if item.get("model") else None
            out.append(item)
        return {"devices": out, "lan_found": len(lan),
                "cloud": {"state": self.cloud.state if self.cloud else "none", "error": cloud_error}}

    def _probe_lan(self, ip: str, token: str) -> dict:
        """Confere IP + token falando de verdade com o robô: devolve {did, model}."""
        c = MiioClient(ip, token, 4)
        c.handshake()
        info = c.send("miIO.info", retry=0)
        return {"did": str(int.from_bytes(c.did, "big")), "model": (info or {}).get("model") or ""}

    def add_robot(self, body, **_):
        from .cloud import CloudError
        body = body or {}
        did, ip = str(body.get("did") or "").strip(), str(body.get("ip") or "").strip()
        token, name = str(body.get("token") or "").strip(), str(body.get("name") or "").strip()
        model, transport = str(body.get("model") or "").strip(), body.get("transport") or "auto"
        if transport not in TRANSPORTS:
            raise ApiError(400, f"transporte inválido: {transport}")
        if did and not token:                                   # token automático: vem da conta Xiaomi
            try:
                c = self._need_cloud().credentials(did)
            except (CloudError, FileNotFoundError) as ex:
                raise ApiError(502, f"não consegui o token pela conta: {ex}") from ex
            token, ip, name, model = c["token"] or "", ip or c.get("ip") or "", name or c["name"] or "", model or c["model"] or ""
        if len(token) != 32:
            raise ApiError(400, "informe o token (32 caracteres hexadecimais) ou escolha um aparelho da conta Xiaomi")
        if not ip and did:                                      # achar o robô sem depender do IP
            ip = lan_discover(timeout=3, near_ip=self._near_ip()).get(int(did), "")
        warning = None
        if ip:
            try:
                probe = self._probe_lan(ip, token)
                did, model = did or probe["did"], model or probe["model"]
                if probe["did"] != did:
                    raise ApiError(409, "o token/IP não pertencem a este aparelho (DID diferente)")
            except MiioError as ex:
                if not (did and self.cloud and self.cloud.state == "ok"):
                    raise ApiError(400, f"não consegui falar com o robô em {ip}: {ex}. Confira IP e token.") from ex
                transport, warning = "cloud", f"sem resposta na rede local ({ip}); cadastrado para usar a nuvem"
        elif not (did and self.cloud and self.cloud.state == "ok"):
            raise ApiError(400, "não achei o robô na rede. Informe o IP ou conecte a conta Xiaomi.")
        else:
            transport, warning = "cloud", "robô não encontrado na rede local; cadastrado para usar a nuvem"
        cfg = RobotConfig(id="", name=name or "Meu robô", ip=ip, token=token, did=did, model=model or catalog.MODEL,
                          transport=transport)
        try:
            robot = self.fleet.add(cfg)
        except ValueError as ex:
            raise ApiError(409, str(ex)) from ex
        self.attach(robot)
        self.bus.publish("robots", {"added": robot.cfg.id})
        return {**robot.summary(), "warning": warning,
                "model_warning": None if robot.cfg.model in SUPPORTED_MODELS else
                f"modelo {robot.cfg.model} sem suporte verificado: alguns recursos podem não funcionar"}

    def update_robot(self, rid, body, **_):
        try:
            robot = self.fleet.update(rid, **(body or {}))
        except KeyError:
            raise ApiError(404, f"robô {rid} não existe") from None
        except ValueError as ex:
            raise ApiError(400, str(ex)) from ex
        self.bus.publish("robots", {"updated": rid})
        return robot.summary()

    def remove_robot(self, rid, query, **_):
        self.robot(rid)
        delete = query.get("delete_data", ["0"])[0] in ("1", "true")
        self.fleet.remove(rid, delete_data=delete)
        self.bus.publish("robots", {"removed": rid})
        return {"removed": rid, "data_deleted": delete}

    def test_robot(self, rid, **_):
        """Fala com o robô por cada transporte e mede."""
        import time
        from .device import H50
        from .transport import CloudClient
        cfg = self.robot(rid).cfg
        out: dict = {"lan": None, "cloud": None}
        if cfg.ip and cfg.token:
            t0 = time.perf_counter()
            try:
                c = MiioClient(cfg.ip, cfg.token, 4)
                c.handshake()
                v = H50(c).values(["2/2"])
                out["lan"] = {"ok": "2/2" in v, "ms": int((time.perf_counter() - t0) * 1000), "ip": cfg.ip}
            except MiioError as ex:
                out["lan"] = {"ok": False, "error": str(ex), "ip": cfg.ip}
        if cfg.did and self.cloud and self.cloud.state == "ok":
            t0 = time.perf_counter()
            try:
                v = H50(CloudClient(self.cloud, cfg.did, cfg.model)).values(["2/2"])
                out["cloud"] = {"ok": "2/2" in v, "ms": int((time.perf_counter() - t0) * 1000)}
            except MiioError as ex:
                out["cloud"] = {"ok": False, "error": str(ex)}
        return out

    def locate_robot(self, rid, **_):
        """Acha o robô pelo DID (broadcast na rede ou IP que a conta Xiaomi informa) e corrige o IP."""
        robot = self.robot(rid)
        cfg = robot.cfg
        if not cfg.did:
            raise ApiError(409, "DID ainda desconhecido: o app o aprende no primeiro contato com o robô")
        ip, source = lan_discover(timeout=3, near_ip=cfg.ip or self._near_ip()).get(int(cfg.did)), "rede"
        if not ip and self.cloud and self.cloud.state == "ok":
            try:
                ip, source = self.cloud.credentials(cfg.did).get("ip"), "conta Xiaomi"
            except Exception:  # noqa: BLE001
                ip = None
        if not ip:
            raise ApiError(404, "não achei o robô agora (desligado, fora da rede ou em outra sub-rede)")
        changed = ip != cfg.ip
        if changed:
            self.fleet.update(rid, ip=ip)
        return {"ip": ip, "source": source, "changed": changed}
