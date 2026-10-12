import os
import unittest

from h50console import aes, miio

TOKEN = bytes.fromhex("000102030405060708090a0b0c0d0e0f")


class FIPS197(unittest.TestCase):
    def test_vectors(self):
        cases = [
            ("000102030405060708090a0b0c0d0e0f", "00112233445566778899aabbccddeeff",
             "69c4e0d86a7b0430d8cdb78070b4c55a"),  # FIPS-197 C.1
            ("2b7e151628aed2a6abf7158809cf4f3c", "3243f6a8885a308d313198a2e0370734",
             "3925841d02dc09fbdc118597196a0b32"),  # FIPS-197 apêndice B
        ]
        for key, pt, ct in cases:
            rk = aes.expand_key(bytes.fromhex(key))
            self.assertEqual(bytes(aes.encrypt_block(bytes.fromhex(pt), rk)).hex(), ct)
            self.assertEqual(bytes(aes.decrypt_block(bytes.fromhex(ct), rk)).hex(), pt)

    def test_cbc_roundtrip(self):
        key, iv = os.urandom(16), os.urandom(16)
        for n in (0, 1, 15, 16, 17, 1000):
            data = os.urandom(n)
            self.assertEqual(aes.cbc_decrypt(aes.cbc_encrypt(data, key, iv), key, iv), data)

    def test_bad_padding(self):
        key, iv = bytes(range(16)), bytes(16)
        ct = aes.cbc_encrypt(b"abc", key, iv)
        with self.assertRaises(ValueError):
            aes.cbc_decrypt(ct, bytes(16), iv)


class AgainstCryptography(unittest.TestCase):
    """Só roda se `cryptography` estiver instalado (dependência de dev, não do app)."""

    def test_same_ciphertext(self):
        try:
            from cryptography.hazmat.primitives import padding
            from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        except ImportError:
            self.skipTest("cryptography não instalado")
        for n in (0, 5, 16, 333, 4000):
            key, iv, data = os.urandom(16), os.urandom(16), os.urandom(n)
            p = padding.PKCS7(128).padder()
            enc = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
            ref = enc.update(p.update(data) + p.finalize()) + enc.finalize()
            self.assertEqual(aes.cbc_encrypt(data, key, iv), ref)


class AgainstPythonMiio(unittest.TestCase):
    """Compara o pacote montado com o do python-miio (dependência de dev, não do app)."""

    def test_packet_roundtrip_with_miio(self):
        try:
            from miio.protocol import Message
        except ImportError:
            self.skipTest("python-miio não instalado")
        import datetime
        payload = {"id": 42, "method": "get_properties",
                   "params": [{"did": "2-2", "siid": 2, "piid": 2}]}
        did, stamp = bytes.fromhex("46fb9b4a"), 1791736164
        ours = miio.build_packet(payload, TOKEN, did, stamp)
        ref = Message.build({"data": {"value": payload},
                             "header": {"value": {"length": 0, "unknown": 0, "device_id": did,
                                                  "ts": datetime.datetime.fromtimestamp(stamp, datetime.UTC)}},
                             "checksum": 0}, token=TOKEN)
        self.assertEqual(ours, ref)
        # e o parse do python-miio entende o nosso pacote, e vice-versa
        self.assertEqual(Message.parse(ours, token=TOKEN).data.value, payload)
        self.assertEqual(miio.parse_packet(ref, TOKEN), (did, stamp, payload))

    def test_wrong_token(self):
        pkt = miio.build_packet({"id": 1, "method": "x", "params": []}, TOKEN, b"\0\0\0\1", 1)
        with self.assertRaises(miio.MiioTokenError):
            miio.parse_packet(pkt, bytes(16))


if __name__ == "__main__":
    unittest.main()
