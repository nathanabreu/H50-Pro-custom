import copy
import unittest

from h50console import mapedit, mapdecode
from h50console.mapedit import EditError

from . import synth


class Edit(unittest.TestCase):
    def setUp(self):
        self.m = synth.synthetic_map()
        self.before = copy.deepcopy(self.m)
        xmin, ymin, xmax, ymax = mapedit.bounds(self.m)
        self.cx, self.cy = (xmin + xmax) / 2, (ymin + ymax) / 2

    def test_input_is_never_modified(self):
        mapedit.apply_ops(self.m, [{"op": "add_wall", "x1": self.cx, "y1": self.cy, "x2": self.cx + 1000, "y2": self.cy}])
        self.assertEqual(self.m, self.before)

    def test_walls_add_and_remove(self):
        new = mapedit.apply_ops(self.m, [{"op": "add_wall", "x1": self.cx, "y1": self.cy, "x2": self.cx + 1500, "y2": self.cy}])
        ids = [w["id"] for w in new["fb_walls"]]
        self.assertEqual(len(ids), 3)
        self.assertEqual(len(set(ids)), 3)                                  # id novo, sem repetir
        gone = mapedit.apply_ops(new, [{"op": "remove_wall", "id": ids[-1]}])
        self.assertEqual(len(gone["fb_walls"]), 2)
        self.assertEqual(mapedit.diff(self.m, new), [f"+ parede virtual {ids[-1]}"])

    def test_wall_validation(self):
        bad = [
            {"op": "add_wall", "x1": self.cx, "y1": self.cy, "x2": self.cx + 50, "y2": self.cy},          # curta demais
            {"op": "add_wall", "x1": self.cx, "y1": self.cy, "x2": 10 ** 7, "y2": self.cy},               # fora do mapa
            {"op": "add_wall", "x1": "a", "y1": 0, "x2": 1, "y2": 1},                                     # não numérico
            {"op": "add_wall", "x1": float("nan"), "y1": 0, "x2": 1, "y2": 1},
            {"op": "remove_wall", "id": 999},
            {"op": "voar"},
        ]
        for op in bad:
            with self.assertRaises(EditError, msg=str(op)):
                mapedit.apply_ops(self.m, [op])

    def test_wall_limit(self):
        ops = [{"op": "add_wall", "x1": self.cx, "y1": self.cy + i * 10, "x2": self.cx + 1000, "y2": self.cy + i * 10}
               for i in range(mapedit.MAX_WALLS)]
        with self.assertRaises(EditError):
            mapedit.apply_ops(self.m, ops)                                  # já tem 2: o 19º passa do limite

    def test_furniture_add_move_remove(self):
        new = mapedit.apply_ops(self.m, [{"op": "add_furniture", "type": 1400, "cx": self.cx, "cy": self.cy}])
        f = new["furniture"][-1]
        self.assertEqual((f["type"], len(f["pos"])), (1400, 8))
        self.assertGreaterEqual(f["id"], 1001)                              # não colide com os ids do robô
        xs, ys = f["pos"][0::2], f["pos"][1::2]
        self.assertEqual((max(xs) - min(xs), max(ys) - min(ys)), (1200, 800))   # tamanho padrão da mesa
        moved = mapedit.apply_ops(new, [{"op": "move_furniture", "id": f["id"], "dx": 100, "dy": -50}])
        self.assertEqual(moved["furniture"][-1]["pos"][0], f["pos"][0] + 100)
        self.assertEqual(moved["furniture"][-1]["pos"][1], f["pos"][1] - 50)
        self.assertIn(f"~ móvel {f['id']} movido", mapedit.diff(new, moved))
        removed = mapedit.apply_ops(moved, [{"op": "remove_furniture", "id": f["id"]}])
        self.assertEqual(removed["furniture"], self.before["furniture"])

    def test_rotated_furniture_keeps_its_size(self):
        pos = mapedit.corners(0, 0, 1000, 400, 90)
        xs, ys = pos[0::2], pos[1::2]
        self.assertEqual((max(xs) - min(xs), max(ys) - min(ys)), (400, 1000))

    def test_furniture_validation(self):
        for op in ({"op": "add_furniture", "type": 1220, "cx": 10 ** 7, "cy": 0},
                   {"op": "add_furniture", "type": 1220, "cx": self.cx, "cy": self.cy, "w": 10},
                   {"op": "add_furniture", "cx": self.cx, "cy": self.cy},
                   {"op": "move_furniture", "id": 15964, "dx": 10 ** 7, "dy": 0},
                   {"op": "remove_furniture", "id": 1}):
            with self.assertRaises(EditError, msg=str(op)):
                mapedit.apply_ops(self.m, [op])

    def test_rename_room(self):
        new = mapedit.apply_ops(self.m, [{"op": "rename_room", "id": 3, "name": "Sala grande"}])
        self.assertEqual(next(r for r in new["room_attrs"] if r["id"] == 3)["room_name"], "Sala grande")
        self.assertEqual(mapedit.diff(self.m, new), ['~ cômodo 3: "Sala de estar" → "Sala grande"'])
        for bad in ("", "x" * 21):
            with self.assertRaises(EditError):
                mapedit.apply_ops(self.m, [{"op": "rename_room", "id": 3, "name": bad}])

    def test_error_names_the_failing_operation(self):
        ok = {"op": "add_wall", "x1": self.cx, "y1": self.cy, "x2": self.cx + 1000, "y2": self.cy}
        with self.assertRaisesRegex(EditError, "operação 2"):
            mapedit.apply_ops(self.m, [ok, {"op": "remove_wall", "id": 999}])

    def test_edited_map_still_roundtrips_through_the_cloud_format(self):
        new = mapedit.apply_ops(self.m, [{"op": "add_furniture", "type": 1220, "cx": self.cx, "cy": self.cy}])
        blob = mapdecode.encrypt(new, synth.MODEL, synth.DID)
        back = mapdecode.decrypt(blob, synth.MODEL, synth.DID)
        self.assertEqual(back["furniture"], new["furniture"])
        self.assertEqual(len(mapdecode.for_ui(back)["furniture"]), 3)


if __name__ == "__main__":
    unittest.main()
