import unittest

from h50console import catalog
from h50console.device import H50
from h50console.miio import MiioError
from h50console.transport import AutoClient, CloudClient, build_client

from .fake import FIXTURES, FakeClient, load_dump


class FakeCloudService:
    """Imita CloudService.api: responde como a nuvem Xiaomi (formato /miotspec/*)."""

    def __init__(self, values: dict, fail: bool = False):
        self.values = dict(values)
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def api(self, path, data, did=None):
        from h50console.cloud import CloudError
        self.calls.append((path, data))
        if self.fail:
            raise CloudError("sessão expirada: rode login de novo")
        if path == "/miotspec/prop/get":
            res = []
            for p in data["params"]:
                k = f"{p['siid']}/{p['piid']}"
                item = {"did": p["did"], "siid": p["siid"], "piid": p["piid"], "updateTime": 1}
                item.update({"code": 0, "value": self.values[k]} if k in self.values else {"code": -4004})
                res.append(item)
            return {"code": 0, "result": res}
        if path == "/miotspec/prop/set":
            for p in data["params"]:
                self.values[f"{p['siid']}/{p['piid']}"] = p["value"]
            return {"code": 0, "result": [{**{k: p[k] for k in ("did", "siid", "piid")}, "code": 0} for p in data["params"]]}
        if path == "/miotspec/action":
            return {"code": 0, "result": {"code": 0, "out": []}}
        raise AssertionError(path)


class CloudClientTests(unittest.TestCase):
    def setUp(self):
        self.svc = FakeCloudService({"2/2": 4, "3/1": 80, "4/2": 60})
        self.c = CloudClient(self.svc, "1000000001", "xiaomi.vacuum.ov42gl")

    def test_get_set_action_have_lan_format(self):
        r = self.c.send("get_properties", [{"did": "x", "siid": 2, "piid": 2}, {"did": "x", "siid": 9, "piid": 9}])
        self.assertEqual(r[0], {"did": "1000000001", "siid": 2, "piid": 2, "code": 0, "value": 4})
        self.assertEqual(r[1]["code"], -4004)
        self.assertEqual(self.svc.calls[0][1]["datasource"], 2)           # leitura em tempo real
        s = self.c.send("set_properties", [{"did": "x", "siid": 4, "piid": 2, "value": 30}])
        self.assertEqual((s[0]["code"], self.svc.values["4/2"]), (0, 30))
        a = self.c.send("action", {"did": "x", "siid": 6, "aiid": 1, "in": []})
        self.assertEqual(a, {"code": 0, "out": []})
        self.assertEqual(self.svc.calls[-1][1]["params"], {"did": "1000000001", "siid": 6, "aiid": 1, "in": []})

    def test_errors_become_miio_error(self):
        self.svc.fail = True
        with self.assertRaises(MiioError):
            self.c.send("get_properties", [{"did": "x", "siid": 2, "piid": 2}])
        with self.assertRaises(MiioError):
            self.c.send("miio.nada")

    def test_h50_over_cloud_reads_oversized_10_3_from_cache(self):
        vals = {k: 0 for k in catalog.READABLE}
        vals["10/3"] = "x" * 2000                       # maior que o limite do UDP
        dev = H50(CloudClient(FakeCloudService(vals), "1000000001"))
        res = dev.get(["2/2", "10/3", "3/1"])
        self.assertEqual(res["10/3"]["code"], 0)
        sources = [c[1]["datasource"] for c in dev.client.service.calls]
        self.assertEqual(sorted(sources), [1, 2])       # 10/3 pelo cache; o resto em tempo real

    def test_batches_respect_cloud_item_limit(self):
        vals = {k: 0 for k in catalog.READABLE}
        dev = H50(CloudClient(FakeCloudService(vals), "1000000001"))
        dev.get([k for k in catalog.READABLE if k != "10/3"][:100])
        for _path, data in dev.client.service.calls:
            self.assertLessEqual(len(data["params"]), 40)

    def test_realtime_timeouts_are_retried_from_cache(self):
        class Flaky(FakeCloudService):
            def api(self, path, data, did=None):
                res = super().api(path, data, did)
                if path == "/miotspec/prop/get" and data["datasource"] == 2:
                    for i in res["result"]:
                        i.pop("value", None); i["code"] = -704220043      # robô não respondeu a tempo
                return res
        c = CloudClient(Flaky({"2/2": 4, "3/1": 80}), "1000000001")
        r = c.send("get_properties", [{"did": "x", "siid": 2, "piid": 2}, {"did": "x", "siid": 3, "piid": 1}])
        self.assertEqual([(i["code"], i["value"]) for i in r], [(0, 4), (0, 80)])


class AutoClientTests(unittest.TestCase):
    def setUp(self):
        self.lan = FakeClient({"2/2": 2, "3/1": 90})
        self.lan.handshake = lambda: (_ for _ in ()).throw(MiioError("off")) if self.lan.offline else None
        self.svc = FakeCloudService({"2/2": 4, "3/1": 80})
        self.auto = AutoClient(self.lan, CloudClient(self.svc, "1000000001"), retry_after=0.05)
        self.req = [{"did": "x", "siid": 3, "piid": 1}]

    def test_lan_first(self):
        r = self.auto.send("get_properties", self.req)
        self.assertEqual((r[0]["value"], self.auto.mode), (90, "lan"))
        self.assertEqual(self.svc.calls, [])

    def test_falls_back_to_cloud_and_returns_to_lan(self):
        self.lan.offline = True
        r = self.auto.send("get_properties", self.req)
        self.assertEqual((r[0]["value"], self.auto.mode), (80, "cloud"))
        self.assertFalse(self.auto.lan_client is None)
        import time
        self.lan.offline = False
        time.sleep(0.1)                                  # passou a janela de espera: sonda a LAN
        r = self.auto.send("get_properties", self.req)
        self.assertEqual((r[0]["value"], self.auto.mode), (90, "lan"))

    def test_lan_still_down_stays_on_cloud(self):
        import time
        self.lan.offline = True
        self.auto.send("get_properties", self.req)
        time.sleep(0.1)
        self.auto.send("get_properties", self.req)
        self.assertEqual(self.auto.mode, "cloud")

    def test_batch_budget_follows_mode(self):
        self.assertIsNone(self.auto.max_batch_bytes)
        self.lan.offline = True
        self.auto.send("get_properties", self.req)
        self.assertEqual((self.auto.max_batch_bytes, self.auto.max_batch_items), (2800, 40))   # limites medidos
        self.assertTrue(self.auto.oversize_ok)

    def test_without_cloud_raises(self):
        a = AutoClient(self.lan, None)
        self.lan.offline = True
        with self.assertRaises(MiioError):
            a.send("get_properties", self.req)

    def test_build_client(self):
        cloud = CloudClient(self.svc, "1")
        self.assertIs(build_client("lan", self.lan, cloud), self.lan)
        self.assertIs(build_client("cloud", self.lan, cloud), cloud)
        self.assertIsInstance(build_client("auto", self.lan, cloud), AutoClient)
        self.assertIs(build_client("auto", self.lan, None), self.lan)       # sem nuvem, só LAN


if __name__ == "__main__":
    unittest.main()
