import json
import threading
import unittest
import urllib.error
import urllib.request

import tempfile
from pathlib import Path

from h50console.fleet import Fleet, RobotConfig
from h50console.hub import Hub
from h50console.web import ApiError, make_server

from .fake import FIXTURES, FakeClient, load_dump
from .test_stage23 import FakeClock

HAS_FIXTURES = (FIXTURES / "dump-full.json").exists()


@unittest.skipUnless(HAS_FIXTURES, "fixtures reais ausentes (tests/fixtures)")
class WebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        vals = load_dump()
        vals.update({"2/2": 2, "2/3": 0, "2/66": "", "11/2": 385877504, "11/1": True})
        cls.fake = FakeClient(vals)
        cls.tmp = tempfile.TemporaryDirectory()
        cls.fleet = Fleet(Path(cls.tmp.name), None, client_factory=lambda cfg: cls.fake, start_threads=False)
        cls.robot = cls.fleet.add(RobotConfig(id="", name="Rex", did="1000000001"), start=False)
        cls.robot.poller.clock = FakeClock()
        cls.robot.poller.tick()
        cls.hub = Hub(cls.fleet, None, raw_enabled=False)
        cls.store, cls.gw, cls.bus, cls.app = cls.robot.store, cls.robot.gw, cls.robot.bus, cls.robot.app
        cls.srv = make_server(cls.hub, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.fleet.stop_all()
        cls.tmp.cleanup()

    def call(self, method, path, body=None):
        req = urllib.request.Request(self.base + path, method=method,
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as ex:
            with ex:
                return ex.code, json.loads(ex.read())

    def test_state(self):
        st, d = self.call("GET", "/api/state")
        self.assertEqual(st, 200)
        self.assertEqual(d["status_label"], "Carregando")
        rows = {r["key"]: r for r in d["rows"]}
        self.assertEqual(rows["2/6"]["value"], "0,87 m²")   # 2/6 = 87 no fixture

    def test_settings_and_put(self):
        _, items = self.call("GET", "/api/settings")
        by = {i["key"]: i for i in items}
        self.assertEqual(by["11/2"]["display"], "23:00–06:00")
        self.assertNotIn("2/29", by)                         # variante: sem troca automática de água
        self.assertEqual([v for v, _ in by["2/61"]["options"]][:3], [0, 2, 1])
        st, res = self.call("PUT", "/api/settings/11-2", {"value": "22:30-07:00"})
        self.assertEqual((st, res["code"]), (200, 0))
        self.assertEqual(self.fake.values["11/2"], 22 << 24 | 30 << 16 | 7 << 8)
        self.assertEqual(self.call("PUT", "/api/settings/2-31", {"value": 9})[0], 400)
        self.assertEqual(self.call("PUT", "/api/settings/2-2", {"value": 1})[0], 403)

    def test_rooms_custom_and_clean(self):
        _, rooms = self.call("GET", "/api/rooms")
        self.assertEqual(len(rooms), 6)
        _, custom = self.call("GET", "/api/custom")
        sala = next(c for c in custom if c["name"] == "Sala intenso")
        self.assertEqual(sala["rooms"], ["Sala de estar", "Corredor"])
        st, res = self.call("POST", f"/api/clean/custom/{sala['id']}")
        self.assertEqual((st, res["fallback"]), (200, "clean_rooms"))
        self.assertEqual(self.fake.calls[-1][1]["in"], [{"piid": 15, "value": "3,8"}])
        self.assertEqual(self.call("POST", "/api/clean/rooms", {"ids": []})[0], 400)

    def test_actions_blocked(self):
        self.gw.cache.update({"2/2": 12})
        try:
            st, res = self.call("POST", "/api/actions/start")
            self.assertEqual(st, 409)
            self.assertIn("base", res["error"])
            self.assertEqual(self.call("POST", "/api/actions/home")[0], 200)
            self.assertEqual(self.call("POST", "/api/actions/explode")[0], 404)
        finally:
            self.gw.cache.update({"2/2": 2})

    def test_misc_routes(self):
        for path in ("/api/health", "/api/consumables", "/api/history", "/api/schedules",
                     "/api/commands", "/api/faults", "/api/app"):
            self.assertEqual(self.call("GET", path)[0], 200, path)
        _, h = self.call("GET", "/api/history")
        self.assertEqual(h["totals"]["count"], 1)
        self.assertEqual(self.call("POST", "/api/raw/get", {"keys": ["2/2"]})[0], 403)
        self.assertEqual(self.call("GET", "/api/nada")[0], 404)
        self.assertEqual(self.call("PUT", "/api/app/name", {"value": "Rex"})[1]["name"], "Rex")

    def test_static_and_traversal(self):
        with urllib.request.urlopen(self.base + "/", timeout=5) as r:
            self.assertIn(b"H50 Console", r.read())
        with urllib.request.urlopen(self.base + "/app.js", timeout=5) as r:
            self.assertIn("javascript", r.headers["Content-Type"])
        self.assertEqual(self.call("GET", "/../config.py")[0], 404)

    def test_sse(self):
        with urllib.request.urlopen(self.base + "/api/r/rex/stream", timeout=5) as r:
            self.assertIn("text/event-stream", r.headers["Content-Type"])
            self.assertEqual(r.readline(), b"retry: 3000\n")
            r.readline()
            self.bus.publish("state", {"changes": {"2/2": 4}})
            self.assertEqual(r.readline(), b"event: state\n")
            self.assertIn(b'"2/2": 4', r.readline())

    def test_robot_prefix_and_default_route_agree(self):
        _, a = self.call("GET", "/api/state")
        _, b = self.call("GET", "/api/r/rex/state")
        self.assertEqual(a["values"]["2/2"], b["values"]["2/2"])
        self.assertEqual(self.call("GET", "/api/r/naoexiste/state")[0], 404)
        _, robots = self.call("GET", "/api/robots")
        self.assertEqual([(r["id"], r["name"]) for r in robots], [("rex", "Rex")])
        self.assertNotIn("token", robots[0])                     # segredos nunca saem pela API

    def test_dispatch_unit(self):
        with self.assertRaises(ApiError):
            self.hub.dispatch("DELETE", "/api/state", {}, None)


if __name__ == "__main__":
    unittest.main()
