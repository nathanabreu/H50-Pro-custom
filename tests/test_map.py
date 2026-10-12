import unittest

from h50console import mapdecode

from .fake import FIXTURES

BLOB = FIXTURES / "map-v2.bin"


@unittest.skipUnless(BLOB.exists(), "mapa real ausente (tests/fixtures/map-v2.bin)")
class MapDecode(unittest.TestCase):
    @staticmethod
    def did() -> str:
        import json
        dump = json.loads((FIXTURES / "dump-full.json").read_text(encoding="utf-8"))["props"]
        return json.loads(dump["10/1"]["value"])["obj_name"].split("/")[1]   # "uid/did/n"

    def test_decrypt_real_map(self):
        m = mapdecode.decrypt(BLOB.read_bytes(), "xiaomi.vacuum.ov42gl", self.did())
        self.assertEqual((m["width"], m["height"], m["resolution"]), (252, 274, 50))
        g = mapdecode.grid(m)
        self.assertEqual(set(g) - {0, 1}, {3, 4, 5, 6, 7, 8})          # pixels = ids dos cômodos
        ui = mapdecode.for_ui(m)
        self.assertEqual(len(ui["walls"]), 2)                           # paredes virtuais do Banheiro
        self.assertEqual({f["type"] for f in ui["furniture"]}, {1220, 1400})
        self.assertIn("Banheiro", [r["name"] for r in ui["rooms"]])

    def test_wrong_did_fails(self):
        with self.assertRaises(ValueError):
            mapdecode.decrypt(BLOB.read_bytes(), "xiaomi.vacuum.ov42gl", "1")


if __name__ == "__main__":
    unittest.main()
