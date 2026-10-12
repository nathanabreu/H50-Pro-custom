import unittest

from h50console import history
from h50console.store import Store

from .fake import FIXTURES

BLOB = FIXTURES / "clean-record-cloud.json"


@unittest.skipUnless(BLOB.exists(), "10/3 real da nuvem ausente (tests/fixtures/clean-record-cloud.json)")
class CloudHistory(unittest.TestCase):
    def setUp(self):
        self.raw = BLOB.read_text(encoding="utf-8")
        self.store = Store(":memory:")

    def test_dedupes_and_is_idempotent(self):
        res = history.import_records(self.store, self.raw)
        # 40 itens = 21 limpezas únicas (pares repetidos + 2 avulsas); o robô conta 22: a lista é limitada a
        # 40 itens e a limpeza mais antiga já saiu dela
        self.assertEqual((res["records"], res["total_count"]), (21, 22))
        self.assertEqual(len(self.store.cleanings()), 21)
        again = history.import_records(self.store, self.raw)
        self.assertEqual((again["added"], again["updated"]), (0, 0))
        self.assertEqual(len(self.store.cleanings()), 21)

    def test_keeps_app_labels_and_rooms_and_fills_unknown_type(self):
        # o app já conhecia a limpeza das 6h30 de 12/10 (rotina 'Sala intenso', tipo desconhecido)
        stime = 1791797400
        self.store.upsert_cleaning(stime, 4680, 61.73, None, "derived", rooms=[3, 8], raw_label="custom:Sala intenso")
        self.store.upsert_cleaning(1791744511, 420, 3.52, 3, "derived", rooms=[8])
        history.import_records(self.store, self.raw)
        rows = {r["stime"]: r for r in self.store.cleanings()}
        r = rows[stime]
        self.assertEqual((r["sweep_type"], r["raw_label"], r["rooms"], r["source"]), (7, "custom:Sala intenso", [3, 8], "robot"))
        r2 = rows[1791744511]
        self.assertEqual((r2["rooms"], r2["area_m2"], r2["source"]), ([8], 3.52, "robot"))


if __name__ == "__main__":
    unittest.main()
