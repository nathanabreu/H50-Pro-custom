"""Leitura de teste do P7 (rodar no terminal NORMAL, não no de administrador, enquanto a captura roda).

    py tools\\p7_read.py            # usa H50_IP/H50_TOKEN do ambiente e, se o IP mudou, acha o robô pelo DID

Lê duas coisas: 2/2 (pequena, de controle) e 10/3 (o histórico, que não chega) e grava o resultado
em data\\p7-py.txt para eu comparar com a captura.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from h50console.miio import MiioClient  # noqa: E402
from h50console.probe import read_one  # noqa: E402
from h50console.store import Store  # noqa: E402

token = os.environ.get("H50_TOKEN")
if not token:
    sys.exit("H50_TOKEN não encontrado no ambiente deste terminal.")
store = Store("data/h50.db")
ip = os.environ.get("H50_IP") or store.get_setting("robot_ip")
did = store.get_setting("robot_did")
if not ip:
    sys.exit("Defina H50_IP (ou rode o app uma vez para ele gravar o IP do robô).")
client = MiioClient(ip, token, 6, expected_did=did)

lines = []
for key, (s, p) in (("2/2 ", (2, 2)), ("10/3", (10, 3))):
    t0 = time.perf_counter()
    r = read_one(client, s, p)
    lines.append(f"{key} {r} em {int((time.perf_counter() - t0) * 1000)} ms")
lines.insert(0, f"robô {client.ip} (did {did})")   # IP real, depois da descoberta pelo DID
Path("data").mkdir(exist_ok=True)
Path("data/p7-py.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))
