"""Importa as mudanças gravadas pelo `probe watch` (monitor.jsonl) para o prop_change do app.

Só importa o que é ANTERIOR à primeira mudança já registrada pelo app (não duplica).
    py tools/import_monitor.py data/monitor.jsonl data/h50.db
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from h50console.store import Store  # noqa: E402


def main(src: str, db: str) -> int:
    store = Store(db)
    first = store._query("SELECT MIN(ts) AS ts FROM prop_change")[0]["ts"]
    cutoff = datetime.fromisoformat(first) if first else datetime.max.replace(tzinfo=timezone.utc)
    last: dict[str, object] = {}
    n = 0
    for line in Path(src).read_text(encoding="utf-8").splitlines():
        e = json.loads(line)
        if e["kind"] != "change":
            continue
        ts = datetime.fromisoformat(e["ts"]).astimezone(timezone.utc)
        if ts >= cutoff:
            break
        changes = {}
        for k, (_old, new) in e["changes"].items():
            if isinstance(new, str) and new.startswith("<"):
                continue  # "<timeout>" etc.
            if k in last and last[k] == new:
                continue  # reinício do monitor relê tudo
            changes[k] = (last.get(k), new)
            last[k] = new
        store.save_changes(changes, ts)
        n += len(changes)
    print(f"{n} mudanças importadas (anteriores a {first})")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:3]))
