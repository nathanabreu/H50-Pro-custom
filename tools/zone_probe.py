"""SONDA de disparo de limpeza por zona (ação 2/37 start-zone-sweep). ESTA FERRAMENTA MOVE O ROBÔ.

Objetivo: descobrir o formato do parâmetro (piid 12) que a ação 2/37 aceita. Em 11/10/2026 vimos que uma limpeza por zona
aparece em `2/40` como {"zones": [[x1,y1,x2,y2,x3,y3,x4,y4], ...]} (retângulos, em mm), mas o formato de ENTRADA da ação
não é conhecido.

Como usar (robô parado na base, você por perto, caminho livre, de preferência com bateria carregada):
    py tools/zone_probe.py                  # só mostra o que faria (não envia nada)
    py tools/zone_probe.py --yes            # tenta os formatos, um por vez

Para cada formato: envia a ação, espera alguns segundos e lê 2/2 (status) e 2/40. Se o robô SAIR para limpar uma zona, manda
parar e voltar à base na hora, registra qual formato funcionou e encerra. Se nenhum funcionar, nada foi movido.
A zona de teste é um quadrado de 1 m x 1 m perto da base (coordenadas do mapa salvo em data/map/latest.json).
Credenciais: H50_IP e H50_TOKEN no ambiente (ou o IP/token do primeiro robô de data/robots.json).
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from h50console import catalog  # noqa: E402
from h50console.device import H50  # noqa: E402
from h50console.miio import MiioClient  # noqa: E402


def client() -> H50:
    ip, token, did = os.environ.get("H50_IP"), os.environ.get("H50_TOKEN"), None
    try:                                   # o DID permite achar o robô mesmo que o IP tenha mudado
        robot = json.loads(Path("data/robots.json").read_text(encoding="utf-8"))["robots"][0]
        ip, token, did = ip or robot["ip"], token or robot["token"], robot.get("did")
    except (OSError, ValueError, KeyError, IndexError):
        try:                               # instalação ainda sem robots.json: o DID está no banco antigo
            import sqlite3
            row = sqlite3.connect("data/h50.db").execute("SELECT value FROM app_setting WHERE key='robot_did'").fetchone()
            did = json.loads(row[0]) if row else None
        except (sqlite3.Error, ValueError):
            pass
    if not (ip and token):
        sys.exit("Sem IP/token: defina H50_IP e H50_TOKEN ou cadastre o robô no app.")
    return H50(MiioClient(ip, token, 5, expected_did=int(did) if did else None))


def test_zone() -> list[int]:
    """Quadrado de 1 m perto da base, a partir do mapa salvo (mm; 4 cantos)."""
    m = json.loads(Path("data/map/latest.json").read_text(encoding="utf-8"))
    bx, by = (m["pile"] or [0, 0])[:2]
    x1, y1, x2, y2 = bx + 400, by - 500, bx + 1400, by + 500
    return [x1, y1, x1, y2, x2, y2, x2, y1]


def candidates(z: list[int]) -> list[tuple[str, str]]:
    rect = [z[0], z[1], z[4], z[5]]
    return [
        ("lista de zonas com 8 números (formato do 2/40)", json.dumps([z])),
        ("objeto {zones: [...]}", json.dumps({"zones": [z]})),
        ("lista com 4 números + passadas (estilo antigo)", json.dumps([rect + [1]])),
        ("objeto com número de passadas", json.dumps({"zones": [z], "clean_times": 1})),
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="envia de verdade (o robô vai se mover)")
    args = ap.parse_args()
    dev = client()
    st = dev.values(["2/2", "3/1"])
    print(f"status {catalog.label('2/2', st.get('2/2'))}, bateria {st.get('3/1')} %")
    if args.yes and st.get("2/2") not in (1, 2, 9):
        sys.exit("O robô não está parado na base. Pare-o primeiro.")
    zone = test_zone()
    print("zona de teste (mm):", zone)
    for label, payload in candidates(zone):
        print()
        print(f"- {label}")
        print(f"  piid 12 = {payload}")
        if not args.yes:
            continue
        print("  resposta:", dev.action("2/37", [payload]))
        time.sleep(6)
        now = dev.values(["2/2", "2/40", "2/5"])
        print("  depois: status", now.get("2/2"), "| 2/5 =", now.get("2/5"), "|", str(now.get("2/40"))[:120])
        if now.get("2/2") in (4, 16, 17) and "zones" in str(now.get("2/40")):
            print("  FUNCIONOU: o robô saiu para limpar a zona. Parando e voltando à base...")
            print("  parar:", dev.run("home"))
            print()
            print(f"Formato aceito: {label}")
            print("Anote em docs/DESCOBERTAS.md.")
            return 0
    print()
    print("Nenhum formato iniciou a limpeza." if args.yes else "(Simulação: nada foi enviado. Use --yes para testar.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
