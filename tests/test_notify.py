import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from h50console import notify
from h50console.fleet import Fleet, RobotConfig
from h50console.hub import Hub
from h50console.notify import Notifier, NotifyError, NotifyStore
from h50console.web import ApiError

from .fake import FakeClient

NTFY = {"name": "Celular", "type": "ntfy", "url": "https://ntfy.sh/topico-secreto-123", "events": ["cleaning_done", "fault", "offline", "online"]}


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fleet = Fleet(Path(self.tmp.name), None, client_factory=lambda cfg: FakeClient({"2/2": 2}), start_threads=False)
        self.addCleanup(self.fleet.stop_all)
        self.robot = self.fleet.add(RobotConfig(id="", name="Rex", did="1000000001"), start=False)
        self.store = NotifyStore(Path(self.tmp.name) / "notify.json")
        self.store.replace([NTFY])
        self.sent = []
        self.clock = Clock()
        self.n = Notifier(self.store, sender=lambda ch, title, text, event, robot: self.sent.append((ch["type"], title, text, event)),
                          clock=self.clock)


class Config(Base):
    def test_public_hides_secrets_and_replace_keeps_them(self):
        pub = self.store.public()[0]
        self.assertNotIn("url", pub)
        self.assertNotIn("token", pub)
        self.assertEqual(pub["url_hint"], "http…123")
        cid = pub["id"]
        self.store.replace([{"id": cid, "type": "ntfy", "name": "Novo nome", "events": ["fault"]}])     # sem enviar o segredo
        self.assertEqual(self.store.get(cid)["url"], NTFY["url"])
        self.assertEqual(self.store.get(cid)["name"], "Novo nome")
        self.assertEqual(json.loads((Path(self.tmp.name) / "notify.json").read_text())["channels"][0]["url"], NTFY["url"])

    def test_validation(self):
        bad = [{"type": "sms", "events": ["fault"]},
               {"type": "ntfy", "url": "https://ntfy.sh/x", "events": []},
               {"type": "ntfy", "url": "ntfy.sh/x", "events": ["fault"]},
               {"type": "telegram", "token": "abc", "events": ["fault"]},
               {"type": "webhook", "url": "ftp://x", "events": ["fault"]}]
        for ch in bad:
            with self.assertRaises(NotifyError, msg=ch):
                self.store.replace([ch])
        self.assertEqual(self.store.public()[0]["name"], "Celular")                # a lista boa não foi perdida

    def test_persists(self):
        again = NotifyStore(Path(self.tmp.name) / "notify.json")
        self.assertEqual(again.channels[0]["url"], NTFY["url"])


class Events(Base):
    def test_cleaning_done_message_uses_the_saved_record(self):
        self.robot.store.upsert_cleaning(1_700_000_000, 1200, 13.06, 3, "derived")
        self.n.on_event(self.robot, "cleaning", {"stime": 1_700_000_000})
        self.assertEqual(self.sent, [("ntfy", "Rex: Limpeza concluída", "13,1 m² em 20 min", "cleaning_done")])
        self.n.on_event(self.robot, "cleaning", {"source": "cloud"})                   # sincronização do histórico: não avisa
        self.assertEqual(len(self.sent), 1)

    def test_only_channels_that_asked_for_the_event(self):
        self.n.on_event(self.robot, "state", {"changes": {"2/97": 1}})                  # tanque: o canal não pediu
        self.assertEqual(self.sent, [])
        self.store.replace([{**NTFY, "id": self.store.channels[0]["id"], "events": ["tank_dirty"]}])
        self.n.on_event(self.robot, "state", {"changes": {"2/97": 1, "2/98": 1}})
        self.assertEqual([s[3] for s in self.sent], ["tank_dirty"])

    def test_repeats_are_grouped(self):
        self.n.on_event(self.robot, "fault", {"codes": [210013]})
        self.n.on_event(self.robot, "fault", {"codes": [210013]})
        self.assertEqual(len(self.sent), 1)
        self.clock.t += 601
        self.n.on_event(self.robot, "fault", {"codes": [210013]})
        self.assertEqual(len(self.sent), 2)
        self.n.on_event(self.robot, "fault", {"codes": [999]})                          # outro código: avisa
        self.assertEqual(len(self.sent), 3)

    def test_consumable_low_once_per_day(self):
        self.store.replace([{**NTFY, "id": self.store.channels[0]["id"], "events": ["consumable_low"]}])
        self.n.on_event(self.robot, "state", {"changes": {"14/1": 9, "9/1": 80}})
        self.clock.t += 7200
        self.n.on_event(self.robot, "state", {"changes": {"14/1": 8}})
        self.assertEqual([s[2] for s in self.sent], ["Filtro: 9 %"])
        self.clock.t += 24 * 3600
        self.n.on_event(self.robot, "state", {"changes": {"14/1": 8}})
        self.assertEqual(len(self.sent), 2)

    def test_offline_only_after_two_minutes_and_online_only_if_notified(self):
        self.n.on_event(self.robot, "offline", {})
        self.clock.t += 60
        self.n.tick(self.robot)
        self.assertEqual(self.sent, [])                                                 # oscilação curta: nada
        self.n.on_event(self.robot, "online", {})
        self.assertEqual(self.sent, [])                                                 # voltou antes: não avisa
        self.n.on_event(self.robot, "offline", {})
        self.clock.t += 130
        self.n.tick(self.robot)
        self.n.tick(self.robot)                                                         # não repete
        self.assertEqual([s[3] for s in self.sent], ["offline"])
        self.n.on_event(self.robot, "online", {})
        self.assertEqual([s[3] for s in self.sent], ["offline", "online"])

    def test_stuck_robot_notice(self):
        self.store.replace([{**NTFY, "id": self.store.channels[0]["id"], "events": ["stuck"]}])
        cache = self.robot.gw.cache
        cache.update({"2/2": 5})                                                        # pausado
        self.n.tick(self.robot)                                                         # começa a contar
        self.clock.t += 20 * 60
        self.n.tick(self.robot)
        self.assertEqual(self.sent, [])                                                 # 20 min: ainda cedo
        self.clock.t += 11 * 60
        self.n.tick(self.robot)
        self.n.tick(self.robot)                                                         # não repete
        self.assertEqual([s[3] for s in self.sent], ["stuck"])
        self.assertIn("Pausado há 31 min", self.sent[0][2])
        cache.update({"2/2": 2})                                                        # voltou à base: zera a contagem
        self.n.tick(self.robot)
        self.clock.t += 7 * 3600
        self.n.tick(self.robot)
        self.assertEqual(len(self.sent), 1)                                             # carregando por horas é normal
        cache.update({"2/2": 4})                                                        # limpando por mais de 3 h
        self.n.tick(self.robot)
        self.clock.t += 3 * 3600 + 5
        self.n.tick(self.robot)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("Limpando há 3 h", self.sent[1][2])

    def test_failing_channel_does_not_break_the_others(self):
        calls = []

        def flaky(ch, title, text, event, robot):
            calls.append(ch["name"])
            if ch["name"] == "A":
                raise NotifyError("fora do ar")
        self.store.replace([{**NTFY, "name": "A"}, {**NTFY, "name": "B"}])
        n = Notifier(self.store, sender=flaky, clock=self.clock)
        self.assertEqual(n.emit(self.robot, "k", "fault", "x"), 1)
        self.assertEqual(calls, ["A", "B"])


class Sending(unittest.TestCase):
    def post(self, channel, event="test"):
        with mock.patch.object(notify, "_post_json") as p:
            notify.send(channel, "Título", "texto", event, "Rex")
        return p.call_args.args

    def test_ntfy_posts_json_to_the_server_root(self):
        url, payload = self.post({"type": "ntfy", "url": "https://ntfy.sh/meu-topico"}, "fault")
        self.assertEqual(url, "https://ntfy.sh/")
        self.assertEqual((payload["topic"], payload["title"], payload["message"], payload["priority"]), ("meu-topico", "Título", "texto", 4))

    def test_telegram_and_webhook(self):
        url, payload = self.post({"type": "telegram", "token": "123:abc", "chat_id": "42"})
        self.assertEqual((url, payload["chat_id"]), ("https://api.telegram.org/bot123:abc/sendMessage", "42"))
        url, payload = self.post({"type": "webhook", "url": "http://10.0.0.5/hook"}, "fault")
        self.assertEqual((url, payload["event"], payload["robot"]), ("http://10.0.0.5/hook", "fault", "Rex"))

    def test_errors_become_notify_error(self):
        with mock.patch.object(notify, "_post_json", side_effect=OSError("sem rede")):
            with self.assertRaises(NotifyError):
                notify.send({"type": "ntfy", "url": "https://ntfy.sh/x"}, "t", "x")
        with self.assertRaises(NotifyError):
            notify.send({"type": "ntfy", "url": "https://ntfy.sh/"}, "t", "x")           # sem tópico
        with self.assertRaises(NotifyError):
            notify.send({"type": "telegram", "token": "x"}, "t", "x")                      # falta o chat_id


class HubRoutes(Base):
    def test_routes(self):
        hub = Hub(self.fleet, None, notifier=self.n)
        d = hub.dispatch("GET", "/api/notify", {}, None)
        self.assertEqual(d["channels"][0]["name"], "Celular")
        self.assertIn("cleaning_done", d["events"])
        self.assertNotIn(NTFY["url"], json.dumps(d))
        cid = d["channels"][0]["id"]
        res = hub.dispatch("PUT", "/api/notify", {}, {"channels": [{"id": cid, "type": "ntfy", "events": ["fault"], "name": "Celular"}]})
        self.assertEqual(res["channels"][0]["events"], ["fault"])
        with self.assertRaises(ApiError) as cm:
            hub.dispatch("PUT", "/api/notify", {}, {"channels": [{"type": "sms", "events": ["fault"]}]})
        self.assertEqual(cm.exception.status, 400)
        out = hub.dispatch("POST", "/api/notify/test", {}, {"id": cid})                     # o remetente falso aceita
        self.assertTrue(out["ok"])
        self.assertEqual(self.sent[-1][3], "test")
        with self.assertRaises(ApiError):
            hub.dispatch("POST", "/api/notify/test", {}, {"id": "nao-existe"})


if __name__ == "__main__":
    unittest.main()
