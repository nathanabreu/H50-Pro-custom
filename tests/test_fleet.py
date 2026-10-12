import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from h50console.fleet import Fleet, RobotConfig, slugify
from h50console.hub import Hub
from h50console.miio import MiioError
from h50console.store import Store
from h50console.transport import OfflineClient
from h50console.web import ApiError

from .fake import FakeClient

TOKEN = "ab" * 16
DID = "1000000001"


class FakeCloud:
    state = "ok"

    def __init__(self, devices=None):
        self._devices = devices if devices is not None else [
            {"did": DID, "name": "Rex", "model": "xiaomi.vacuum.ov42gl", "online": True, "localip": "10.0.0.7", "has_token": True},
            {"did": "999", "name": "Outro", "model": "roborock.vacuum.s5", "online": True, "localip": "10.0.0.8", "has_token": True},
            {"did": "5", "name": "Lâmpada", "model": "yeelink.light.x", "online": True, "localip": "10.0.0.9", "has_token": True},
        ]

    def devices(self):
        return self._devices

    def credentials(self, did):
        for d in self._devices:
            if d["did"] == did:
                return {"did": did, "name": d["name"], "model": d["model"], "token": TOKEN, "ip": d["localip"]}
        raise RuntimeError("fora da conta")

    def status(self):
        return {"state": self.state}


class FleetCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)           # registrado primeiro = roda por ÚLTIMO (depois de fechar os bancos)
        self.dir = Path(self.tmp.name)

    def fleet(self, factory=None):
        f = Fleet(self.dir, FakeCloud(), client_factory=factory or (lambda cfg: FakeClient({"2/2": 2})), start_threads=False)
        self.addCleanup(f.stop_all)
        return f


class FleetStorage(FleetCase):
    def test_roundtrip_keeps_token_but_public_hides_it(self):
        f = self.fleet()
        r = f.add(RobotConfig(id="", name="Sala 1", ip="10.0.0.7", token=TOKEN, did=DID), start=False)
        raw = json.loads((self.dir / "robots.json").read_text(encoding="utf-8"))
        self.assertEqual(raw["robots"][0]["token"], TOKEN)
        self.assertNotIn("token", r.cfg.public())
        self.assertTrue(r.cfg.public()["has_token"])
        f.stop_all()
        g = self.fleet()
        g.load()
        self.assertEqual([(x.cfg.id, x.cfg.token) for x in g.robots.values()], [("sala-1", TOKEN)])

    def test_unique_ids_and_duplicate_did(self):
        f = self.fleet()
        f.add(RobotConfig(id="", name="Rex", did="1"), start=False)
        b = f.add(RobotConfig(id="", name="Rex", did="2"), start=False)
        self.assertEqual(b.cfg.id, "rex-2")
        with self.assertRaises(ValueError):
            f.add(RobotConfig(id="", name="Outro", did="1"), start=False)

    def test_legacy_install_is_migrated(self):
        st = Store(self.dir / "h50.db")
        st.set_setting("robot_ip", "10.0.0.7"); st.set_setting("robot_did", int(DID)); st.set_setting("device_name", "Rex")
        st.close()
        f = self.fleet()
        f.load(seed={"token": TOKEN, "ip": "1.1.1.1", "name": "x"})
        r = f.default()
        self.assertEqual((r.cfg.name, r.cfg.ip, r.cfg.did, r.cfg.db), ("Rex", "10.0.0.7", DID, "h50.db"))
        self.assertTrue((self.dir / "robots.json").exists())          # a partir daqui robots.json manda

    def test_no_token_no_robots(self):
        f = self.fleet()
        f.load(seed={"ip": "10.0.0.7"})
        self.assertEqual(f.robots, {})

    def test_update_validates_and_keeps_token_when_blank(self):
        f = self.fleet()
        r = f.add(RobotConfig(id="", name="Rex", ip="10.0.0.7", token=TOKEN, did=DID), start=False)
        f.update("rex", name="Hector", ip="10.0.0.9", token="", transport="lan")
        self.assertEqual((r.cfg.name, r.cfg.ip, r.cfg.token, r.cfg.transport), ("Hector", "10.0.0.9", TOKEN, "lan"))
        with self.assertRaises(ValueError):
            f.update("rex", token="curto")
        with self.assertRaises(ValueError):
            f.update("rex", transport="satelite")
        with self.assertRaises(KeyError):
            f.update("nao", name="x")

    def test_remove_with_and_without_data(self):
        f = self.fleet()
        r = f.add(RobotConfig(id="", name="Rex", did=DID), start=False)
        db = r.db_path
        f.remove("rex")
        self.assertTrue(db.exists())                                   # padrão: guarda os dados
        r2 = f.add(RobotConfig(id="", name="Rex", did=DID), start=False)
        f.remove("rex", delete_data=True)
        self.assertFalse(r2.db_path.exists())
        self.assertEqual(f.robots, {})

    def test_robot_without_any_path_gets_offline_client(self):
        f = Fleet(self.dir, FakeCloud(), start_threads=False)           # sem factory: monta o cliente real
        self.addCleanup(f.stop_all)
        r = f.add(RobotConfig(id="", name="Sem nada"), start=False)
        self.assertIsInstance(r.client, OfflineClient)
        with self.assertRaises(MiioError):
            r.client.send("get_properties", [])

    def test_slugify(self):
        self.assertEqual(slugify("Quarto da Criança!"), "quarto-da-crianca")
        self.assertEqual(slugify("???"), "robo")


class HubAccount(FleetCase):
    def setUp(self):
        super().setUp()
        self.fl = self.fleet()
        self.cloud = FakeCloud()
        self.hub = Hub(self.fl, self.cloud)
        self.probe = mock.patch.object(Hub, "_probe_lan", return_value={"did": DID, "model": "xiaomi.vacuum.ov42gl"})
        self.probe.start()
        self.addCleanup(self.probe.stop)
        self.lan = mock.patch("h50console.hub.lan_discover", return_value={int(DID): "10.0.0.7"})
        self.lan.start()
        self.addCleanup(self.lan.stop)

    def post(self, body):
        return self.hub.dispatch("POST", "/api/robots", {}, body)

    def test_add_by_did_gets_token_from_account(self):
        res = self.post({"did": DID})
        self.assertEqual((res["name"], res["ip"], res["transport"], res["has_token"]), ("Rex", "10.0.0.7", "auto", True))
        self.assertNotIn("token", res)
        self.assertEqual(self.fl.get("rex").cfg.token, TOKEN)          # guardado, mas nunca devolvido
        with self.assertRaises(ApiError) as cm:
            self.post({"did": DID})
        self.assertEqual(cm.exception.status, 409)

    def test_add_finds_ip_without_one(self):
        self.cloud._devices[0]["localip"] = ""
        res = self.post({"did": DID})
        self.assertEqual(res["ip"], "10.0.0.7")                         # achou pelo DID na rede

    def test_lan_down_falls_back_to_cloud_transport(self):
        with mock.patch.object(Hub, "_probe_lan", side_effect=MiioError("timeout")):
            res = self.post({"did": DID})
        self.assertEqual(res["transport"], "cloud")
        self.assertIn("nuvem", res["warning"])

    def test_manual_add_validates_token_and_did(self):
        with self.assertRaises(ApiError) as cm:
            self.post({"ip": "10.0.0.7", "token": "curto"})
        self.assertEqual(cm.exception.status, 400)
        with mock.patch.object(Hub, "_probe_lan", return_value={"did": "777", "model": "m"}):
            with self.assertRaises(ApiError) as cm:
                self.post({"ip": "10.0.0.7", "token": TOKEN, "did": DID})
        self.assertEqual(cm.exception.status, 409)                      # DID do aparelho não confere
        res = self.post({"ip": "10.0.0.7", "token": TOKEN, "name": "Manual"})
        self.assertEqual((res["did"], res["name"]), (DID, "Manual"))

    def test_manual_add_without_cloud_and_unreachable_is_400(self):
        self.cloud.state = "none"
        with mock.patch.object(Hub, "_probe_lan", side_effect=MiioError("timeout")):
            with self.assertRaises(ApiError) as cm:
                self.post({"ip": "10.0.0.7", "token": TOKEN})
        self.assertEqual(cm.exception.status, 400)

    def test_unsupported_model_is_added_with_warning(self):
        with mock.patch.object(Hub, "_probe_lan", return_value={"did": "999", "model": "roborock.vacuum.s5"}):
            res = self.post({"did": "999"})
        self.assertFalse(res["supported"])
        self.assertIn("sem suporte verificado", res["model_warning"])

    def test_discover_merges_account_and_network(self):
        self.post({"did": DID})
        with mock.patch("h50console.hub.lan_discover", return_value={int(DID): "10.0.0.7", 4242: "10.0.0.50"}):
            out = self.hub.dispatch("GET", "/api/robots/discover", {}, None)
        by = {d["did"]: d for d in out["devices"]}
        self.assertEqual(set(by), {DID, "999", "4242"})                 # a lâmpada não é aspirador
        self.assertTrue(by[DID]["added"])
        self.assertTrue(by[DID]["supported"])
        self.assertFalse(by["999"]["supported"])
        self.assertEqual((by["4242"]["source"], by["4242"]["lan_ip"]), ("rede", "10.0.0.50"))
        self.assertTrue(all("token" not in d for d in out["devices"]))

    def test_locate_updates_ip(self):
        self.post({"did": DID})
        self.fl.update("rex", ip="10.0.0.99")
        res = self.hub.dispatch("POST", "/api/robots/rex/locate", {}, None)
        self.assertEqual((res["ip"], res["changed"]), ("10.0.0.7", True))
        self.assertEqual(self.fl.get("rex").cfg.ip, "10.0.0.7")

    def test_test_robot_reports_both_transports(self):
        self.post({"did": DID})

        class FakeMiio:
            def __init__(self, *a, **k): ...
            def handshake(self): ...
            def send(self, *a, **k): return [{"siid": 2, "piid": 2, "code": 0, "value": 2}]
        with mock.patch("h50console.hub.MiioClient", FakeMiio), \
             mock.patch("h50console.transport.CloudClient.send", return_value=[{"siid": 2, "piid": 2, "code": 0, "value": 2}]):
            res = self.hub.dispatch("POST", "/api/robots/rex/test", {}, None)
        self.assertTrue(res["lan"]["ok"])
        self.assertTrue(res["cloud"]["ok"])

    def test_remove_and_empty_fleet_routes(self):
        self.post({"did": DID})
        self.hub.dispatch("DELETE", "/api/robots/rex", {}, None)
        with self.assertRaises(ApiError) as cm:
            self.hub.dispatch("GET", "/api/state", {}, None)            # sem robôs: 409 com instrução
        self.assertEqual(cm.exception.status, 409)
        self.assertTrue(self.hub.dispatch("GET", "/api/app", {}, None)["onboarding"])


if __name__ == "__main__":
    unittest.main()
