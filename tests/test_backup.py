import io
import json
import logging
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from h50console import backup, maint
from h50console.__main__ import main as cli
from h50console.backup import BackupError
from h50console.fleet import Fleet, RobotConfig
from h50console.hub import Hub
from h50console.store import Store
from h50console.web import ApiError, Raw

from .fake import FakeClient

PW = "senha-de-backup-1"
TOKEN = "cd" * 16
DID = "1000000001"


class Env(unittest.TestCase):
    """Uma frota de verdade (client falso) numa pasta temporária."""

    def new_fleet(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)                       # registrado antes do stop_all => roda depois
        fleet = Fleet(tmp.name, None, client_factory=lambda cfg: FakeClient({"2/2": 2}), start_threads=False)
        self.addCleanup(fleet.stop_all)
        return fleet

    def seeded(self):
        fleet = self.new_fleet()
        r = fleet.add(RobotConfig(id="", name="Rex", ip="10.0.0.7", token=TOKEN, did=DID), start=False)
        r.store.upsert_cleaning(1_700_000_000, 600, 12.5, 3, "derived", rooms=[5], raw_label="custom:Pelos gatos")
        r.store.save_changes({"2/2": (None, 4)})
        r.store.replace_rooms(1, [{"id": 5, "name": "Quarto"}])
        r.store.set_setting("nota", "oi")
        fleet.settings.set("retention_days", 45)
        r.map_dir.mkdir(parents=True, exist_ok=True)
        (r.map_dir / "latest.json").write_text('{"width": 3}', encoding="utf-8")
        (fleet.data_dir / "secret.key").write_text("ab" * 32, encoding="utf-8")
        return fleet, r


class Crypto(unittest.TestCase):
    def test_roundtrip_wrong_password_and_tampering(self):
        blob = backup.seal(b"conteudo secreto" * 100, PW, iters=2000)
        self.assertEqual(backup.unseal(blob, PW), b"conteudo secreto" * 100)
        with self.assertRaises(BackupError):
            backup.unseal(blob, "outra-senha-aqui")
        bad = bytearray(blob)
        bad[60] ^= 1                                             # um bit no texto cifrado
        with self.assertRaises(BackupError):
            backup.unseal(bytes(bad), PW)
        with self.assertRaises(BackupError):
            backup.unseal(blob[:-1], PW)
        with self.assertRaises(BackupError):
            backup.unseal(b"nao e um backup" * 10, PW)
        self.assertNotIn(b"secreto", blob)                       # cifrado de verdade
        self.assertNotEqual(blob, backup.seal(b"conteudo secreto" * 100, PW, iters=2000))   # sal/iv novos

    def test_short_passphrase_refused(self):
        with self.assertRaises(BackupError):
            backup.seal(b"x", "curta")


class Contents(Env):
    def test_create_read_apply_restores_everything_but_the_session_key(self):
        fleet, r = self.seeded()
        blob = backup.create(fleet, PW, app_version="9.9")
        files = backup.read(blob, PW)
        self.assertIn("manifest.json", files)
        self.assertNotIn("secret.key", files)
        manifest = json.loads(files["manifest.json"])
        self.assertEqual((manifest["app_version"], manifest["robots"]), ("9.9", ["rex"]))
        self.assertEqual(json.loads(files["robots.json"])["robots"][0]["token"], TOKEN)   # só dentro do cifrado
        self.assertNotIn(TOKEN.encode(), blob)

        other = self.new_fleet()
        res = backup.apply(other, files, start=False)
        self.assertIn("robots/rex/h50.db", res["written"])
        robot = other.get("rex")
        self.assertEqual(robot.cfg.token, TOKEN)
        rec = robot.store.cleanings()[0]
        self.assertEqual((rec["duration_s"], rec["raw_label"], rec["rooms"]), (600, "custom:Pelos gatos", [5]))
        self.assertEqual(robot.store.get_setting("nota"), "oi")
        self.assertEqual(other.settings.get("retention_days"), 45)
        self.assertEqual(json.loads((robot.map_dir / "latest.json").read_text())["width"], 3)

    def test_restore_over_a_live_fleet_replaces_data(self):
        fleet, _ = self.seeded()
        blob = backup.create(fleet, PW)
        fleet.get("rex").store.upsert_cleaning(1_800_000_000, 1, 1.0, 1, "derived")      # algo novo depois do backup
        self.assertEqual(len(fleet.get("rex").store.cleanings()), 2)
        backup.apply(fleet, backup.read(blob, PW), start=False)
        self.assertEqual(len(fleet.get("rex").store.cleanings()), 1)                       # voltou ao estado do backup

    def test_hostile_archives_are_rejected(self):
        for name in ("../evil.json", "robots/x/../../a.db", "/etc/passwd", "robots/x/other.txt", "app.json.exe"):
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as z:
                z.writestr("manifest.json", "{}")
                z.writestr(name, "x")
            with self.assertRaises(BackupError, msg=name):
                backup.read(backup.seal(buf.getvalue(), PW, iters=2000), PW)

    def test_zip_bomb_guard_and_missing_manifest(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("manifest.json", "{}")
            z.writestr("robots.json", "0" * 50_000)
        blob = backup.seal(buf.getvalue(), PW, iters=2000)
        with mock.patch.object(backup, "MAX_UNCOMPRESSED", 10_000):
            with self.assertRaises(BackupError):
                backup.read(blob, PW)
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, "w") as z:
            z.writestr("robots.json", "{}")
        with self.assertRaises(BackupError):
            backup.read(backup.seal(buf2.getvalue(), PW, iters=2000), PW)


class HubMaintenance(Env):
    def setUp(self):
        self.fleet, self.robot = self.seeded()
        self.hub = Hub(self.fleet, None, ring=maint.RingLog())

    def test_status_counts_rows_and_sizes(self):
        st = self.hub.dispatch("GET", "/api/maintenance/status", {}, None)
        r = st["robots"][0]
        self.assertEqual((st["retention_days"], r["rows"]["cleaning_record"], r["rows"]["prop_change"]), (45, 1, 1))
        self.assertGreater(r["db_bytes"], 0)
        self.assertGreater(st["data_bytes"], 0)

    def test_retention_validation_and_purge_keeps_cleanings(self):
        for bad in ({"days": 3}, {"days": "abc"}, {}, {"days": 99999}):
            with self.assertRaises(ApiError):
                self.hub.dispatch("PUT", "/api/maintenance/retention", {}, bad)
        self.hub.dispatch("PUT", "/api/maintenance/retention", {}, {"days": 30})
        self.assertEqual(self.fleet.settings.get("retention_days"), 30)
        st = self.robot.store
        st._exec("UPDATE prop_change SET ts = '2000-01-01T00:00:00+00:00'")
        res = self.hub.dispatch("POST", "/api/maintenance/purge", {}, None)
        self.assertEqual(res[0]["deleted"], 1)
        self.assertEqual(len(st.cleanings()), 1)                    # histórico de limpezas nunca é apagado
        self.assertEqual(self.robot.poller.retention_days(), 30)    # o poller usa a mesma configuração

    def test_optimize_runs(self):
        out = self.hub.dispatch("POST", "/api/maintenance/optimize", {}, None)
        self.assertEqual(out[0]["id"], "rex")
        self.assertGreater(out[0]["after"], 0)

    def test_hub_backup_create_and_restore(self):
        raw = self.hub.dispatch("POST", "/api/backup/create", {}, {"passphrase": PW})
        self.assertIsInstance(raw, Raw)
        self.assertTrue(raw.filename.endswith(".h50bak"))
        with self.assertRaises(ApiError) as cm:
            self.hub.dispatch("POST", "/api/backup/create", {}, {"passphrase": "curta"})
        self.assertEqual(cm.exception.status, 400)
        with self.assertRaises(ApiError):
            self.hub.dispatch("POST", "/api/backup/restore", {}, {"data": raw.data, "passphrase": "errada-errada"})
        self.robot.store.upsert_cleaning(1_800_000_000, 1, 1.0, 1, "derived")
        res = self.hub.dispatch("POST", "/api/backup/restore", {}, {"data": raw.data, "passphrase": PW})
        self.assertEqual(res["robots"], ["rex"])
        self.assertIsNotNone(self.fleet.get("rex").app)             # as rotas do robô foram religadas
        self.assertEqual(len(self.fleet.get("rex").store.cleanings()), 1)

    def test_support_bundle_has_no_secrets(self):
        logging.getLogger("teste").addHandler(self.hub.ring)
        logging.getLogger("teste").setLevel(logging.INFO)
        logging.getLogger("teste").info("falei com 10.0.0.7 agora")
        raw = self.hub.dispatch("GET", "/api/maintenance/support", {}, None)
        text = raw.data.decode()
        for secret in (TOKEN, DID, "10.0.0.7"):
            self.assertNotIn(secret, text)
        self.assertIn("10.0.0.x", text)
        self.assertIn("xiaomi.vacuum.ov42gl", text)

    def test_logs_ring_and_csv_export(self):
        logs = self.hub.dispatch("GET", "/api/maintenance/logs", {"n": ["5"]}, None)
        self.assertIsInstance(logs, list)
        csv_ = self.hub.dispatch("GET", "/api/r/rex/export/cleanings.csv", {}, None)
        text = csv_.data.decode("utf-8-sig")
        self.assertIn("inicio,duracao_s,area_m2", text)
        self.assertIn("600,12.5,Cômodos,Quarto,derived,custom:Pelos gatos", text)
        self.assertEqual(csv_.filename, "limpezas.csv")

    def test_ringlog_is_bounded(self):
        ring = maint.RingLog(capacity=3)
        lg = logging.getLogger("ring-teste")
        lg.addHandler(ring)
        lg.setLevel(logging.INFO)
        for i in range(10):
            lg.info("msg %s", i)
        self.assertEqual([r["msg"] for r in ring.tail()], ["msg 7", "msg 8", "msg 9"])


class Cli(Env):
    def test_backup_and_restore_commands(self):
        src = tempfile.TemporaryDirectory()
        self.addCleanup(src.cleanup)
        dst = tempfile.TemporaryDirectory()
        self.addCleanup(dst.cleanup)
        out = Path(src.name) / "b.h50bak"
        # instalação de origem criada pela própria CLI (migração de H50_IP/H50_TOKEN)
        env = {"H50_DATA_DIR": src.name, "H50_TOKEN": TOKEN, "H50_IP": "10.0.0.7", "H50_NAME": "Rex",
               "H50_BACKUP_PASSPHRASE": PW}
        with mock.patch.dict(os.environ, env):
            self.assertEqual(cli(["backup", str(out)]), 0)
        self.assertTrue(out.exists())
        self.assertNotIn(TOKEN.encode(), out.read_bytes())
        with mock.patch.dict(os.environ, {"H50_DATA_DIR": dst.name, "H50_BACKUP_PASSPHRASE": PW}, clear=False):
            os.environ.pop("H50_TOKEN", None)
            self.assertEqual(cli(["restore", str(out)]), 0)
        robots = json.loads((Path(dst.name) / "robots.json").read_text())["robots"]
        self.assertEqual((robots[0]["name"], robots[0]["token"]), ("Rex", TOKEN))
        with mock.patch.dict(os.environ, {"H50_DATA_DIR": dst.name, "H50_BACKUP_PASSPHRASE": "errada-errada"}):
            with self.assertRaises(SystemExit):
                cli(["restore", str(out)])


if __name__ == "__main__":
    unittest.main()
