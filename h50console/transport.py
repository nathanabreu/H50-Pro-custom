"""Transportes para falar com o robô, todos com o mesmo contrato: `send(método, parâmetros, retry)`.

- LAN:   miio.MiioClient (UDP 54321, token do aparelho). Resposta máxima ~1,4 KB.
- Nuvem: CloudClient, a mesma API que o app oficial usa fora de casa (/miotspec/*). Sem limite de tamanho
         (o 10/3 completo vem inteiro), mas mais lenta (~1–2,5 s) e dependente da conta Xiaomi.
- Auto:  AutoClient tenta a LAN e cai para a nuvem quando a LAN não responde (fora de casa, IP trocado).

Os resultados têm o formato da LAN, então Gateway/H50/Poller não sabem qual transporte está em uso.
`mode` ("lan"|"cloud") diz qual foi usado por último; o poller relaxa os intervalos na nuvem.
"""

from __future__ import annotations

import logging
import threading
import time

from .miio import MiioClient, MiioError

log = logging.getLogger(__name__)

# Medido em 12/10/2026 (ov42gl): em tempo real (datasource 2) a nuvem responde até 40 propriedades por pedido
# (~2,8 KB); acima disso o robô não responde a tempo (códigos -704220043/-704083036). O cache (datasource 1)
# devolve tudo de uma vez (149 de 165 props em 2 s) e é o único caminho do 10/3 completo.
CLOUD_BATCH_BYTES = 2800
CLOUD_BATCH_ITEMS = 40
_OK_OR_MISSING = {0, -704040002, -704040003}   # ok; propriedade inexistente / sem acesso de leitura
LAN_RETRY_AFTER = 60.0             # depois de a LAN falhar, só tenta de novo após este tempo


class CloudClient:
    """Fala com o robô pela nuvem Xiaomi (leitura em tempo real: datasource 2)."""

    lan = False
    mode = "cloud"
    oversize_ok = True
    max_batch_bytes = CLOUD_BATCH_BYTES
    max_batch_items = CLOUD_BATCH_ITEMS

    def __init__(self, service, did, model: str = "", fresh: bool = True):
        self.service = service          # cloud.CloudService (sessão, país, chamadas assinadas)
        self.did = str(did)
        self.model = model
        self.fresh = fresh

    def _call(self, path: str, data: dict) -> dict:
        from .cloud import CloudError
        try:
            res = self.service.api(path, data, did=self.did)
        except CloudError as ex:
            raise MiioError(f"nuvem: {ex}") from ex
        if res.get("code") not in (0, None):
            raise MiioError(f"nuvem code {res.get('code')}: {res.get('message', '')}")
        return res

    def _get(self, params: list, datasource: int) -> list[dict]:
        req = [{"did": self.did, "siid": p["siid"], "piid": p["piid"]} for p in params]
        res = self._call("/miotspec/prop/get", {"params": req, "datasource": datasource})
        return [{"did": self.did, "siid": i["siid"], "piid": i["piid"], "code": i.get("code", 0),
                 **({"value": i["value"]} if "value" in i else {})} for i in res.get("result") or []]

    def _get_properties(self, params: list) -> list[dict]:
        from . import catalog
        key = lambda p: f"{p['siid']}/{p['piid']}"           # noqa: E731
        big = [p for p in params if key(p) in catalog.OVERSIZED]    # 10/3: só o cache devolve inteiro
        rest = [p for p in params if key(p) not in catalog.OVERSIZED]
        out: list[dict] = []
        if rest:
            out = self._get(rest, 2 if self.fresh else 1)
            bad = [i for i in out if i["code"] not in _OK_OR_MISSING]      # o robô não respondeu a tempo
            if bad and self.fresh:
                cached = {(i["siid"], i["piid"]): i for i in self._get(bad, 1)}
                out = [cached.get((i["siid"], i["piid"]), i) if i in bad else i for i in out]
        if big:
            out += self._get(big, 1)
        return out

    def send(self, method, params=None, retry=1):
        if method == "get_properties":
            return self._get_properties(params or [])
        if method == "set_properties":
            req = [{"did": self.did, "siid": p["siid"], "piid": p["piid"], "value": p["value"]} for p in params or []]
            res = self._call("/miotspec/prop/set", {"params": req})
            return [{"did": self.did, "siid": i["siid"], "piid": i["piid"], "code": i.get("code", 0)}
                    for i in res.get("result") or []]
        if method == "action":
            a = params or {}
            res = self._call("/miotspec/action", {"params": {"did": self.did, "siid": a["siid"], "aiid": a["aiid"],
                                                              "in": a.get("in", [])}})
            r = res.get("result") or {}
            return {"code": r.get("code", 0), "out": r.get("out", [])}
        if method == "miIO.info":
            return {"model": self.model, "via": "cloud"}
        raise MiioError(f"a nuvem não suporta o método {method}")


class AutoClient:
    """LAN primeiro; se falhar e houver nuvem, usa a nuvem e volta à LAN quando ela responder de novo."""

    lan = True

    def __init__(self, lan: MiioClient, cloud: CloudClient | None, retry_after: float = LAN_RETRY_AFTER):
        self.lan_client = lan
        self.cloud_client = cloud
        self.retry_after = retry_after
        self.mode = "lan"
        self._lan_down_until = 0.0
        self._lock = threading.Lock()

    # atributos que o resto do app consulta no cliente LAN
    @property
    def ip(self):
        return self.lan_client.ip

    @property
    def expected_did(self):
        return self.lan_client.expected_did

    @property
    def oversize_ok(self) -> bool:
        return self.mode == "cloud"

    @property
    def max_batch_bytes(self):
        return CLOUD_BATCH_BYTES if self.mode == "cloud" else None

    @property
    def max_batch_items(self):
        return CLOUD_BATCH_ITEMS if self.mode == "cloud" else None

    def _lan_usable(self) -> bool:
        if time.monotonic() < self._lan_down_until:
            return False
        if self._lan_down_until:                       # janela de espera acabou: sonda a LAN antes de voltar
            try:
                self.lan_client.handshake()
            except MiioError:
                self._lan_down_until = time.monotonic() + self.retry_after
                return False
            self._lan_down_until = 0.0
            log.info("LAN voltou a responder; saindo do modo nuvem")
        return True

    def prepare(self) -> None:
        """Decide o transporte ANTES de planejar os lotes (o limite de tamanho depende dele)."""
        with self._lock:
            if self.cloud_client is None:
                self.mode = "lan"
            elif self._lan_usable():
                self.mode = "lan"
            else:
                self.mode = "cloud"

    def send(self, method, params=None, retry=1):
        self.prepare()
        if self.mode == "lan":
            try:
                return self.lan_client.send(method, params, retry=retry)
            except MiioError:
                if self.cloud_client is None:
                    raise
                self._lan_down_until = time.monotonic() + self.retry_after
                self.mode = "cloud"
                log.warning("LAN sem resposta; usando a nuvem por %.0f s", self.retry_after)
        if self.cloud_client is None:
            raise MiioError("sem transporte disponível")
        self.mode = "cloud"
        return self.cloud_client.send(method, params, retry)

    def handshake(self) -> None:
        self.lan_client.handshake()


def build_client(transport: str, lan: MiioClient | None, cloud: CloudClient | None):
    """transport: "lan" | "cloud" | "auto" (nuvem só se existir)."""
    if transport == "cloud" and cloud is not None:
        return cloud
    if transport == "auto" and cloud is not None and lan is not None:
        return AutoClient(lan, cloud)
    if lan is None:
        raise ValueError("robô sem IP/token para a LAN e sem nuvem")
    return lan


class OfflineClient:
    """Robô sem como ser alcançado (sem IP/token e sem nuvem): toda chamada falha com uma mensagem útil."""

    lan = False
    mode = "lan"
    oversize_ok = False
    max_batch_bytes = None
    max_batch_items = None

    def __init__(self, reason: str):
        self.reason = reason

    def send(self, method, params=None, retry=1):
        raise MiioError(self.reason)
