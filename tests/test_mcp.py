import io
import json
import tempfile
import threading
import unittest
from pathlib import Path

from h50console.auth import Auth
from h50console.fleet import Fleet, RobotConfig
from h50console.hub import Hub
from h50console.mcp import ALLOWED_ACTIONS, TOOLS, Api, Server, Tools
from h50console.web import make_server

from .fake import FakeClient, load_dump

ADMIN, VIEWER = "senha-admin-1234", "senha-leitura-1234"


class McpBase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        vals = load_dump()
        vals.update({"2/2": 2, "2/3": 0, "2/66": "", "11/2": 385877504, "11/1": True})
        cls.fake = FakeClient(vals)
        cls.tmp = tempfile.TemporaryDirectory()
        fleet = Fleet(Path(cls.tmp.name), None, client_factory=lambda cfg: cls.fake, start_threads=False)
        cls.robot = fleet.add(RobotConfig(id="", name="Rex", did="1000000001"), start=False)
        cls.robot.poller.tick()
        cls.fleet = fleet
        auth = Auth(cls.tmp.name, iters=1000)
        auth.setup(auth.setup_code, ADMIN)
        auth.set_viewer_password(VIEWER)
        cls.srv = make_server(Hub(fleet, None), "127.0.0.1", 0, auth=auth)
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        cls.fleet.stop_all()
        cls.tmp.cleanup()

    def server(self, password=ADMIN) -> Server:
        return Server(Tools(Api(self.base, password)))

    def rpc(self, srv, method, params=None, mid=1):
        return srv.handle({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}})

    def tool(self, srv, name, **args):
        res = self.rpc(srv, "tools/call", {"name": name, "arguments": args})["result"]
        text = res["content"][0]["text"]
        return res["isError"], (text if res["isError"] else json.loads(text))


class Protocol(McpBase):
    def test_handshake_and_tool_list(self):
        s = self.server()
        init = self.rpc(s, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}})["result"]
        self.assertEqual((init["protocolVersion"], init["serverInfo"]["name"]), ("2024-11-05", "h50console"))
        self.assertIsNone(s.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}))     # notificação: sem resposta
        names = {t["name"] for t in self.rpc(s, "tools/list")["result"]["tools"]}
        self.assertEqual(names, {t["name"] for t in TOOLS})
        for t in TOOLS:                                         # todo esquema é um objeto JSON válido
            self.assertEqual(t["inputSchema"]["type"], "object")
            json.dumps(t)
        self.assertEqual(self.rpc(s, "ping")["result"], {})

    def test_errors(self):
        s = self.server()
        self.assertEqual(self.rpc(s, "nao/existe")["error"]["code"], -32601)
        self.assertEqual(self.rpc(s, "tools/call", {"name": "nada"})["error"]["code"], -32602)
        self.assertEqual(s.handle({"id": 1})["error"]["code"], -32600)
        out = io.StringIO()
        s.serve(io.StringIO('{"jsonrpc":"2.0","id":7,"method":"ping"}\nnão é json\n\n'), out)
        lines = [json.loads(x) for x in out.getvalue().splitlines()]
        self.assertEqual((lines[0]["id"], lines[1]["error"]["code"]), (7, -32700))           # a linha ruim não derruba o laço

    def test_every_tool_is_declared_with_a_handler(self):
        for t in TOOLS:
            self.assertTrue(callable(getattr(Tools, t["name"])), t["name"])


class Reading(McpBase):
    def test_read_tools(self):
        s = self.server()
        bad, robots = self.tool(s, "robots_list")
        self.assertFalse(bad)
        self.assertEqual(robots[0]["name"], "Rex")
        self.assertNotIn("ip", robots[0])
        bad, st = self.tool(s, "robot_status")
        self.assertEqual((bad, st["status"], st["active"]), (False, "Carregando", False))
        self.assertIsInstance(self.tool(s, "consumables")[1], list)
        self.assertIsInstance(self.tool(s, "rooms", robot="rex")[1], list)           # por nome, sem diferenciar maiúsculas
        self.assertGreater(len(self.tool(s, "settings")[1]), 5)
        self.assertIn("latest", self.tool(s, "cleaning_history", limit=3)[1])
        self.assertIsInstance(self.tool(s, "faults")[1], list)

    def test_unknown_robot(self):
        bad, msg = self.tool(self.server(), "robot_status", robot="outro")
        self.assertTrue(bad)
        self.assertIn("robots_list", msg)


class Commands(McpBase):
    def test_moving_commands_need_confirmation(self):
        s = self.server()
        before = len(self.fake.calls)
        bad, res = self.tool(s, "robot_action", action="start")
        self.assertEqual((bad, res["executed"]), (False, False))
        self.assertIn("confirm=true", res["next_step"])
        names = [c[0] for c in self.fake.calls[before:]]
        self.assertNotIn("action", names)                                   # nada foi enviado ao robô
        bad, res = self.tool(s, "clean_rooms", rooms=["Sala de estar"])
        self.assertEqual(res["executed"], False)
        self.assertNotIn("action", [c[0] for c in self.fake.calls[before:]])

    def test_safe_action_runs_without_confirmation_and_confirmed_ones_run(self):
        s = self.server()
        bad, res = self.tool(s, "robot_action", action="locate")
        self.assertEqual((bad, res["executed"]), (False, True))
        bad, res = self.tool(s, "robot_action", action="home", confirm=True)
        self.assertTrue(res["executed"])

    def test_clean_rooms_resolves_names_and_rejects_unknown(self):
        s = self.server()
        bad, msg = self.tool(s, "clean_rooms", rooms=["Cômodo que não existe"], confirm=True)
        self.assertTrue(bad)
        self.assertIn("opções", msg)

    def test_action_whitelist(self):
        bad, msg = self.tool(self.server(), "robot_action", action="build-map", confirm=True)
        self.assertTrue(bad)                                                 # fora da lista do assistente
        self.assertNotIn("build-map", ALLOWED_ACTIONS)

    def test_set_setting_needs_confirmation(self):
        s = self.server()
        bad, res = self.tool(s, "set_setting", key="4/2", value=40)
        self.assertEqual(res["executed"], False)
        self.assertNotEqual(self.fake.values.get("4/2"), 40)
        bad, res = self.tool(s, "set_setting", key="4/2", value=40, confirm=True)
        self.assertEqual((bad, res["executed"]), (False, True))
        self.assertEqual(self.fake.values["4/2"], 40)


class ReadOnlyProfile(McpBase):
    def test_viewer_password_reads_but_cannot_command(self):
        s = self.server(VIEWER)
        self.assertFalse(self.tool(s, "robot_status")[0])
        before = len(self.fake.calls)
        bad, msg = self.tool(s, "robot_action", action="home", confirm=True)
        self.assertTrue(bad)
        self.assertIn("somente leitura", msg)
        bad, msg = self.tool(s, "set_setting", key="4/2", value=10, confirm=True)
        self.assertTrue(bad)
        self.assertNotIn("set_properties", [c[0] for c in self.fake.calls[before:]])

    def test_wrong_password_and_missing_password(self):
        bad, msg = self.tool(self.server("errada-1234567"), "robots_list")
        self.assertTrue(bad)
        self.assertIn("401", msg)
        bad, msg = self.tool(self.server(""), "robots_list")
        self.assertTrue(bad)
        self.assertIn("H50_MCP_PASSWORD", msg)

    def test_server_down_is_a_tool_error(self):
        s = Server(Tools(Api("http://127.0.0.1:9", ADMIN, timeout=2)))
        bad, msg = self.tool(s, "robots_list")
        self.assertTrue(bad)
        self.assertIn("não consegui falar", msg)


if __name__ == "__main__":
    unittest.main()
