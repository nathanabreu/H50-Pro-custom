"""Gera os ícones do app (PNG 192 e 512) sem dependências: um robô aspirador visto de cima.

    py tools/make_icons.py        # grava h50console/static/icon-192.png e icon-512.png

Só os PNGs são gerados; o icon.svg é escrito à mão. O desenho cabe na "zona segura" de 80 % (ícone maskable).
"""

import struct
import sys
import zlib
from pathlib import Path

BG = (47, 111, 222)       # azul do app
FG = (255, 255, 255)
SAMPLES = 3               # superamostragem para suavizar as bordas


def inside_rounded_square(x, y, r=0.22):
    dx, dy = max(abs(x - 0.5) - (0.5 - r), 0), max(abs(y - 0.5) - (0.5 - r), 0)
    return dx * dx + dy * dy <= r * r


def color_at(x, y):
    if not inside_rounded_square(x, y):
        return None
    d2 = (x - 0.5) ** 2 + (y - 0.52) ** 2
    if d2 <= 0.065 ** 2 and abs(x - 0.5) < 0.065 and y < 0.44:       # sensor frontal (laser) em azul sobre o disco
        return BG
    if (x - 0.5) ** 2 + (y - 0.40) ** 2 <= 0.055 ** 2:
        return BG
    if d2 <= 0.30 ** 2:
        if 0.36 ** 2 > d2 > 0.23 ** 2 and y > 0.62:                    # faixa do para-choque (traseira), sutil
            return (226, 233, 247)
        return FG
    return BG


def render(size):
    rows = []
    for j in range(size):
        row = bytearray([0])                                            # filtro PNG "nenhum"
        for i in range(size):
            acc = [0, 0, 0, 0]
            for sj in range(SAMPLES):
                for si in range(SAMPLES):
                    c = color_at((i + (si + 0.5) / SAMPLES) / size, (j + (sj + 0.5) / SAMPLES) / size)
                    if c:
                        acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]; acc[3] += 255
            n = SAMPLES * SAMPLES
            a = acc[3] // n
            if a:
                cnt = acc[3] // 255
                row += bytes([acc[0] // cnt, acc[1] // cnt, acc[2] // cnt, a])
            else:
                row += bytes([0, 0, 0, 0])
        rows.append(bytes(row))
    return rows


def png(size):
    raw = b"".join(render(size))

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


if __name__ == "__main__":
    out = Path(__file__).resolve().parent.parent / "h50console" / "static"
    for s in (192, 512):
        (out / f"icon-{s}.png").write_bytes(png(s))
        print(f"icon-{s}.png ok")
    sys.exit(0)
