"""Robô falso para testes: responde com os valores de um dump real e imita os limites do aparelho."""

import json
from pathlib import Path

from h50console.miio import MiioError

FIXTURES = Path(__file__).with_name("fixtures")
DID = "1000000001"   # did fictício das respostas simuladas


def load_dump() -> dict[str, object]:
    """Valores do dump completo de 11/10/2026 ({"2/2": 1, …}); 10/3 vem do dump antigo."""
    full = json.loads((FIXTURES / "dump-full.json").read_text(encoding="utf-8"))["props"]
    vals = {k: v["value"] for k, v in full.items() if "value" in v}
    scan = json.loads((FIXTURES / "scan.json").read_text(encoding="utf-8"))["found"]
    vals.update({k: v["value"] for k, v in scan.items() if "value" in v})  # props fora da spec
    old = json.loads((FIXTURES / "dump.json").read_text(encoding="utf-8"))
    vals["10/3"] = old["10/3"]
    return vals


class FakeClient:
    """Mesmo send() do MiioClient. Resposta > max_bytes = timeout (como o robô real)."""

    def __init__(self, values: dict, max_bytes: int = 1350, offline: bool = False):
        self.values = dict(values)
        self.max_bytes = max_bytes
        self.offline = offline
        self.calls: list[tuple[str, object]] = []

    def send(self, method, params=None, retry=1):
        self.calls.append((method, params))
        if self.offline:
            raise MiioError("timeout")
        if method == "get_properties":
            res = []
            for p in params:
                k = f"{p['siid']}/{p['piid']}"
                item = {"did": DID, "siid": p["siid"], "piid": p["piid"]}  # did do aparelho (D2)
                item.update({"code": 0, "value": self.values[k]} if k in self.values else {"code": -4004})
                res.append(item)
            if len(json.dumps({"id": 1, "result": res}).encode()) > self.max_bytes:
                raise MiioError("timeout")
            return res
        if method == "set_properties":
            p = params[0]
            self.values[f"{p['siid']}/{p['piid']}"] = p["value"]
            return [{"did": DID, "siid": p["siid"], "piid": p["piid"], "code": 0}]
        if method == "action":
            return {"code": 0, "out": []}
        if method == "miIO.info":
            return {"model": "xiaomi.vacuum.ov42gl", "fw_ver": "4.5.8_0087"}
        raise AssertionError(method)
