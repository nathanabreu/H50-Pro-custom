"""AES-128-CBC com padding PKCS7 em Python puro (sem dependências).

É o que o protocolo miIO precisa: key = MD5(token), iv = MD5(key + token).
Os pacotes têm poucos KB e saem a cada segundos, então a velocidade não importa.
Validado contra os vetores do FIPS-197 e contra o python-miio (tests/test_aes.py).
"""

from __future__ import annotations


def _build_tables():
    # S-box gerada a partir do inverso multiplicativo em GF(2^8) + transformação afim
    sbox = [0] * 256
    p = q = 1
    while True:
        # p *= 3
        p = p ^ ((p << 1) & 0xFF) ^ (0x1B if p & 0x80 else 0)
        # q /= 3
        q ^= q << 1
        q ^= q << 2
        q ^= q << 4
        q &= 0xFF
        if q & 0x80:
            q ^= 0x09
        x = q ^ _rotl8(q, 1) ^ _rotl8(q, 2) ^ _rotl8(q, 3) ^ _rotl8(q, 4)
        sbox[p] = (x ^ 0x63) & 0xFF
        if p == 1:
            break
    sbox[0] = 0x63
    inv = [0] * 256
    for i, v in enumerate(sbox):
        inv[v] = i
    return sbox, inv


def _rotl8(x: int, s: int) -> int:
    return ((x << s) | (x >> (8 - s))) & 0xFF


def _xtime(a: int) -> int:
    a <<= 1
    return (a ^ 0x1B) & 0xFF if a & 0x100 else a


def _mul(a: int, b: int) -> int:
    r = 0
    while b:
        if b & 1:
            r ^= a
        a = _xtime(a)
        b >>= 1
    return r


SBOX, INV_SBOX = _build_tables()
MUL2 = [_mul(i, 2) for i in range(256)]
MUL3 = [_mul(i, 3) for i in range(256)]
MUL9 = [_mul(i, 9) for i in range(256)]
MUL11 = [_mul(i, 11) for i in range(256)]
MUL13 = [_mul(i, 13) for i in range(256)]
MUL14 = [_mul(i, 14) for i in range(256)]
RCON = [0x01, 0x02, 0x04, 0x08, 0x10, 0x20, 0x40, 0x80, 0x1B, 0x36]

# estado em ordem de coluna: índice = 4*coluna + linha; ShiftRows como permutação
_SHIFT = [0, 5, 10, 15, 4, 9, 14, 3, 8, 13, 2, 7, 12, 1, 6, 11]
_INV_SHIFT = [_SHIFT.index(i) for i in range(16)]


def expand_key(key: bytes) -> list[list[int]]:
    """Gera as 11 round keys (16 bytes cada) do AES-128."""
    if len(key) != 16:
        raise ValueError("AES-128 precisa de chave de 16 bytes")
    w = list(key)
    for i in range(4, 44):
        t = w[(i - 1) * 4 : i * 4]
        if i % 4 == 0:
            t = [SBOX[t[1]] ^ RCON[i // 4 - 1], SBOX[t[2]], SBOX[t[3]], SBOX[t[0]]]
        w.extend(w[(i - 4) * 4 + j] ^ t[j] for j in range(4))
    return [w[r * 16 : (r + 1) * 16] for r in range(11)]


def encrypt_block(block: bytes | list[int], rk: list[list[int]]) -> list[int]:
    s = [b ^ k for b, k in zip(block, rk[0])]
    for r in range(1, 10):
        s = [SBOX[s[_SHIFT[i]]] for i in range(16)]
        m = []
        for c in range(0, 16, 4):
            a0, a1, a2, a3 = s[c : c + 4]
            m += [
                MUL2[a0] ^ MUL3[a1] ^ a2 ^ a3,
                a0 ^ MUL2[a1] ^ MUL3[a2] ^ a3,
                a0 ^ a1 ^ MUL2[a2] ^ MUL3[a3],
                MUL3[a0] ^ a1 ^ a2 ^ MUL2[a3],
            ]
        s = [x ^ k for x, k in zip(m, rk[r])]
    return [SBOX[s[_SHIFT[i]]] ^ rk[10][i] for i in range(16)]


def decrypt_block(block: bytes | list[int], rk: list[list[int]]) -> list[int]:
    s = [b ^ k for b, k in zip(block, rk[10])]
    for r in range(9, 0, -1):
        s = [INV_SBOX[s[_INV_SHIFT[i]]] ^ rk[r][i] for i in range(16)]
        m = []
        for c in range(0, 16, 4):
            a0, a1, a2, a3 = s[c : c + 4]
            m += [
                MUL14[a0] ^ MUL11[a1] ^ MUL13[a2] ^ MUL9[a3],
                MUL9[a0] ^ MUL14[a1] ^ MUL11[a2] ^ MUL13[a3],
                MUL13[a0] ^ MUL9[a1] ^ MUL14[a2] ^ MUL11[a3],
                MUL11[a0] ^ MUL13[a1] ^ MUL9[a2] ^ MUL14[a3],
            ]
        s = m
    return [INV_SBOX[s[_INV_SHIFT[i]]] ^ rk[0][i] for i in range(16)]


def cbc_encrypt(plain: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC com PKCS7."""
    rk = expand_key(key)
    pad = 16 - len(plain) % 16
    data = plain + bytes([pad]) * pad
    prev = list(iv)
    out = bytearray()
    for i in range(0, len(data), 16):
        prev = encrypt_block([a ^ b for a, b in zip(data[i : i + 16], prev)], rk)
        out += bytes(prev)
    return bytes(out)


def cbc_decrypt(cipher: bytes, key: bytes, iv: bytes) -> bytes:
    """AES-128-CBC; remove o PKCS7 e lança ValueError se o padding for inválido."""
    if not cipher or len(cipher) % 16:
        raise ValueError("tamanho do ciphertext não é múltiplo de 16")
    rk = expand_key(key)
    prev = iv
    out = bytearray()
    for i in range(0, len(cipher), 16):
        blk = cipher[i : i + 16]
        out += bytes(a ^ b for a, b in zip(decrypt_block(blk, rk), prev))
        prev = blk
    pad = out[-1]
    if not 1 <= pad <= 16 or out[-pad:] != bytes([pad]) * pad:
        raise ValueError("padding PKCS7 inválido (token errado?)")
    return bytes(out[:-pad])
