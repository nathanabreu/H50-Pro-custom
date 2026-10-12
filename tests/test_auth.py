import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path

from h50console.auth import MAX_FAILS, MIN_PASSWORD, Auth, AuthError, hash_password, verify_password
from h50console.fleet import Fleet
from h50console.hub import Hub
from h50console.web import make_server

FAST = 1000                      # iterações baixas só nos testes
PW = "senha-forte-123"


class FakeClock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


class AuthUnit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = FakeClock()
        self.auth = Auth(self.tmp.name, iters=FAST, clock=self.clock)

    def test_hash_roundtrip(self):
        rec = hash_password("abc12345", iters=FAST)
        self.assertTrue(verify_password("abc12345", rec))
        self.assertFalse(verify_password("abc12346", rec))
        self.assertNotEqual(hash_password("abc12345", iters=FAST)["salt"], rec["salt"])

    def test_first_access_needs_the_console_code(self):
        a = self.auth
        self.assertTrue(a.status(False)["setup_required"])
        with self.assertRaises(AuthError) as cm:
            a.setup("ERRADO", PW, "1.1.1.1")
        self.assertEqual(cm.exception.status, 403)
        with self.assertRaises(AuthError) as cm:
            a.setup(a.setup_code, "curta", "1.1.1.1")
        self.assertEqual(cm.exception.status, 400)
        token = a.setup(a.setup_code.lower(), PW, "1.1.1.1")          # o código aceita minúsculas
        self.assertTrue(a.valid_token(token))
        self.assertIsNone(a.setup_code)
        with self.assertRaises(AuthError) as cm:
            a.setup("QUALQUER", PW, "1.1.1.1")
        self.assertEqual(cm.exception.status, 409)                    # só uma vez

    def test_login_and_rate_limit(self):
        a = self.auth
        a.setup(a.setup_code, PW)
        with self.assertRaises(AuthError) as cm:
            a.login("errada", "9.9.9.9")
        self.assertEqual(cm.exception.status, 401)
        for _ in range(MAX_FAILS - 1):
            with self.assertRaises(AuthError):
                a.login("errada", "9.9.9.9")
        with self.assertRaises(AuthError) as cm:
            a.login(PW, "9.9.9.9")                                    # mesmo certa: bloqueado
        self.assertEqual(cm.exception.status, 429)
        self.assertGreater(cm.exception.retry_after, 0)
        self.assertTrue(a.valid_token(a.login(PW, "8.8.8.8")))        # outro IP não é afetado
        self.clock.t += 31
        self.assertTrue(a.valid_token(a.login(PW, "9.9.9.9")))        # passou a espera

    def test_activity_log_records_logins_and_failures(self):
        a = self.auth
        a.setup(a.setup_code, PW, "1.1.1.1")
        with self.assertRaises(AuthError):
            a.login("errada", "2.2.2.2")
        a.login(PW, "1.1.1.1")
        evs = [(e["event"], e["ip"], e["ok"]) for e in a.activity]       # mais recente primeiro
        self.assertEqual(evs[0], ("login", "1.1.1.1", True))
        self.assertEqual(evs[1], ("senha ou código incorreto", "2.2.2.2", False))
        self.assertEqual(evs[2][0], "senha criada")

    def test_tracked_ips_are_capped(self):
        from h50console import auth as auth_mod
        a = self.auth
        a.setup(a.setup_code, PW)
        for i in range(auth_mod.MAX_TRACKED_IPS + 50):
            with self.assertRaises(AuthError):
                a.login("errada", f"10.{i // 256}.{i % 256}.1")
        self.assertLessEqual(len(a._fails), auth_mod.MAX_TRACKED_IPS)

    def test_change_password_is_rate_limited(self):
        a = self.auth
        a.setup(a.setup_code, PW)
        for _ in range(MAX_FAILS):
            with self.assertRaises(AuthError):
                a.change_password("errada", "outra-senha-123", "3.3.3.3")
        with self.assertRaises(AuthError) as cm:
            a.change_password(PW, "outra-senha-123", "3.3.3.3")
        self.assertEqual(cm.exception.status, 429)

    def test_tokens_expire_tamper_and_revoke(self):
        a = self.auth
        token = a.setup(a.setup_code, PW)
        self.assertTrue(a.valid_token(token))
        self.assertFalse(a.valid_token(token[:-2] + "00"))
        self.assertFalse(a.valid_token(None))
        self.assertFalse(a.valid_token("v1.9999999999.abc.deadbeef"))
        self.clock.t += 31 * 86400
        self.assertFalse(a.valid_token(token))                        # 30 dias
        self.clock.t -= 31 * 86400
        fresh = a.revoke_all()
        self.assertFalse(a.valid_token(token))                        # sair de todos
        self.assertTrue(a.valid_token(fresh))

    def test_change_password_invalidates_old_sessions(self):
        a = self.auth
        old = a.setup(a.setup_code, PW)
        with self.assertRaises(AuthError):
            a.change_password("errada", "outra-senha-1")
        new = a.change_password(PW, "outra-senha-1")
        self.assertFalse(a.valid_token(old))
        self.assertTrue(a.valid_token(new))
        a.login("outra-senha-1")
        with self.assertRaises(AuthError):
            a.login(PW)

    def test_reset_password_forces_a_new_first_access(self):
        a = self.auth
        token = a.setup(a.setup_code, PW)
        a.reset_password()
        self.assertFalse(a.configured)
        self.assertTrue(a.setup_code)                                  # código novo disponível na hora
        self.assertFalse(a.valid_token(token))                         # sessões antigas caem
        b = Auth(self.tmp.name, iters=FAST, clock=self.clock)          # e continua assim depois de reiniciar
        self.assertTrue(b.status(False)["setup_required"])
        self.assertTrue(b.valid_token(b.setup(b.setup_code, "senha-nova-123")))
        with self.assertRaises(AuthError):
            b.login(PW)                                                 # a senha antiga não vale mais

    def test_persists_across_restarts(self):
        a = self.auth
        token = a.setup(a.setup_code, PW)
        b = Auth(self.tmp.name, iters=FAST, clock=self.clock)
        self.assertTrue(b.configured)
        self.assertIsNone(b.setup_code)
        self.assertTrue(b.valid_token(token))                         # a chave de assinatura também persiste
        self.assertTrue(b.valid_token(b.login(PW)))

    def test_env_password_wins_and_cannot_be_changed(self):
        a = Auth(self.tmp.name, env_password="da-env-12345", iters=FAST, clock=self.clock)
        self.assertTrue(a.configured)
        self.assertIsNone(a.setup_code)
        self.assertTrue(a.valid_token(a.login("da-env-12345")))
        with self.assertRaises(AuthError):
            a.login("outra")
        with self.assertRaises(AuthError) as cm:
            a.change_password("da-env-12345", "nova-senha-1")
        self.assertEqual(cm.exception.status, 409)

    def test_viewer_role_is_separate_and_revocable(self):
        a = self.auth
        a.setup(a.setup_code, PW)
        a.set_viewer_password("somente-leitura-1")
        v = a.login("somente-leitura-1")
        self.assertEqual((a.role_of(v), a.role_of(a.login(PW))), ("viewer", "admin"))
        with self.assertRaises(AuthError):
            a.set_viewer_password(PW)                                 # não pode repetir a do administrador
        forged = v.replace("v2.", "v1.").replace(".viewer", "")      # tentar passar o token do visualizador por admin
        self.assertIsNone(a.role_of(forged))
        a.set_viewer_password("outra-senha-leitura")                 # trocar a senha derruba as sessões do visualizador
        self.assertIsNone(a.role_of(v))
        admin = a.login(PW)
        a.set_viewer_password("")                                     # desligar o perfil
        self.assertIsNone(a.role_of(a.make_token("viewer")))
        self.assertEqual(a.role_of(admin), "admin")
        with self.assertRaises(AuthError):
            a.login("outra-senha-leitura")

    def test_viewer_env_password(self):
        a = Auth(self.tmp.name, env_password="admin-env-1234", viewer_password="viewer-env-1234", iters=FAST, clock=self.clock)
        self.assertEqual(a.role_of(a.login("viewer-env-1234")), "viewer")
        with self.assertRaises(AuthError):
            a.set_viewer_password("x" * 10)

    def test_min_password_constant(self):
        self.assertGreaterEqual(MIN_PASSWORD, 8)


class Server:
    """Servidor real com autenticação ligada, frota vazia, falando por http.client (sem seguir redirecionamentos)."""

    def __init__(self, test: unittest.TestCase, trust_proxy: bool = False):
        self.tmp = tempfile.TemporaryDirectory()
        test.addCleanup(self.tmp.cleanup)
        self.auth = Auth(self.tmp.name, iters=FAST)
        fleet = Fleet(self.tmp.name, None, start_threads=False)
        test.addCleanup(fleet.stop_all)
        self.srv = make_server(Hub(fleet, None), "127.0.0.1", 0, auth=self.auth, trust_proxy=trust_proxy)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        test.addCleanup(self.srv.server_close)
        test.addCleanup(self.srv.shutdown)

    def req(self, method, path, body=None, cookie=None, headers=None):
        h = {"Host": f"127.0.0.1:{self.port}", **(headers or {})}
        if cookie:
            h["Cookie"] = cookie
        data = None
        if body is not None:
            data = json.dumps(body)
            h["Content-Type"] = "application/json"
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = raw
        return r.status, payload, r

    def login_cookie(self):
        st, _, r = self.req("POST", "/api/auth/setup", {"code": self.auth.setup_code, "password": PW}, headers={"X-H50": "1"})
        assert st == 200, st
        return r.getheader("Set-Cookie").split(";")[0]


class AuthHttp(unittest.TestCase):
    def test_everything_needs_a_session_except_the_login_page(self):
        s = Server(self)
        st, body, _ = s.req("GET", "/api/robots")
        self.assertEqual((st, body["login"]), (401, True))
        st, _, r = s.req("GET", "/")
        self.assertEqual((st, r.getheader("Location")), (302, "/login.html?next=%2F"))
        self.assertEqual(s.req("GET", "/app.js")[0], 302)
        self.assertEqual(s.req("GET", "/api/r/x/stream")[0], 401)
        self.assertEqual(s.req("GET", "/login.html")[0], 200)
        self.assertEqual(s.req("GET", "/login.js")[0], 200)

    def test_pwa_files_are_public_and_have_the_right_types(self):
        s = Server(self)
        for path, ctype in (("/manifest.webmanifest", "application/manifest+json"), ("/sw.js", "javascript"),
                            ("/icon-192.png", "image/png"), ("/icon-512.png", "image/png"), ("/icon.svg", "image/svg+xml")):
            st, _, r = s.req("GET", path)
            self.assertEqual(st, 200, path)
            self.assertIn(ctype, r.getheader("Content-Type"), path)
        manifest = s.req("GET", "/manifest.webmanifest")[1]                # a resposta já vem como JSON
        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue(all(i["src"].startswith("/icon") for i in manifest["icons"]))
        self.assertEqual(s.req("GET", "/app.js")[0], 302)            # o resto do app continua atrás do login
        self.assertEqual(s.req("GET", "/api/state")[0], 401)

    def test_security_headers(self):
        s = Server(self)
        _, _, r = s.req("GET", "/login.html")
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("X-Content-Type-Options"), "nosniff")
        self.assertEqual(r.getheader("X-Frame-Options"), "DENY")

    def test_setup_then_session_cookie_works(self):
        s = Server(self)
        _, st, _ = s.req("GET", "/api/auth/status")
        self.assertTrue(st["setup_required"])
        bad, _, _ = s.req("POST", "/api/auth/setup", {"code": "ERRADO", "password": PW}, headers={"X-H50": "1"})
        self.assertEqual(bad, 403)
        cookie = s.login_cookie()
        self.assertEqual(s.req("GET", "/api/robots", cookie=cookie)[0], 200)
        self.assertEqual(s.req("GET", "/", cookie=cookie)[0], 200)
        _, st, _ = s.req("GET", "/api/auth/status", cookie=cookie)
        self.assertEqual((st["authenticated"], st["setup_required"]), (True, False))
        _, _, r = s.req("GET", "/login.html")
        self.assertNotIn("Set-Cookie", dict(r.getheaders()))

    def test_activity_endpoint_needs_login(self):
        s = Server(self)
        self.assertEqual(s.req("GET", "/api/auth/activity")[0], 401)
        cookie = s.login_cookie()
        st, d, _ = s.req("GET", "/api/auth/activity", cookie=cookie)
        self.assertEqual(st, 200)
        self.assertEqual(d["events"][0]["event"], "senha criada")

    def test_viewer_can_read_but_not_change(self):
        s = Server(self)
        admin = s.login_cookie()
        st, _, _ = s.req("POST", "/api/auth/viewer", {"password": "somente-leitura-1"}, cookie=admin, headers={"X-H50": "1"})
        self.assertEqual(st, 200)
        _, _, r = s.req("POST", "/api/auth/login", {"password": "somente-leitura-1"}, headers={"X-H50": "1"})
        viewer = r.getheader("Set-Cookie").split(";")[0]
        _, status, _ = s.req("GET", "/api/auth/status", cookie=viewer)
        self.assertEqual((status["role"], status["authenticated"]), ("viewer", True))
        self.assertEqual(s.req("GET", "/api/robots", cookie=viewer)[0], 200)
        self.assertEqual(s.req("GET", "/", cookie=viewer)[0], 200)
        for method, path in (("POST", "/api/robots"), ("PUT", "/api/r/x/settings/2-9"), ("POST", "/api/backup/create"),
                             ("GET", "/api/maintenance/status"), ("GET", "/api/backup/x"), ("GET", "/api/auth/activity"),
                             ("GET", "/api/r/x/lab/props"), ("GET", "/api/notify"), ("GET", "/api/cloud/devices")):
            self.assertEqual(s.req(method, path, {} if method != "GET" else None, cookie=viewer, headers={"X-H50": "1"})[0], 403,
                             f"{method} {path}")
        for path in ("/api/auth/password", "/api/auth/revoke", "/api/auth/viewer"):
            self.assertEqual(s.req("POST", path, {"password": "x" * 9, "current": "a", "new": "b" * 9},
                                   cookie=viewer, headers={"X-H50": "1"})[0], 403, path)
        self.assertEqual(s.req("GET", "/api/maintenance/status", cookie=admin)[0], 200)   # o administrador segue igual
        # mapa e status da nuvem: permitidos (o módulo de nuvem está desligado nos testes, então 404/503, nunca 403)
        self.assertNotEqual(s.req("POST", "/api/r/x/cloud/map", {}, cookie=viewer, headers={"X-H50": "1"})[0], 403)
        self.assertNotEqual(s.req("GET", "/api/cloud/status", cookie=viewer)[0], 403)         # rota da conta (o app usa esta)
        self.assertEqual(s.req("POST", "/api/r/x/cloud/qr", {}, cookie=viewer, headers={"X-H50": "1"})[0], 403)

    def test_metrics_needs_session_or_token(self):
        s = Server(self)
        self.assertEqual(s.req("GET", "/metrics")[0], 401)
        cookie = s.login_cookie()
        self.assertEqual(s.req("GET", "/metrics", cookie=cookie)[0], 200)
        s2 = Server(self)
        s2.srv.RequestHandlerClass  # servidor sem token configurado: Bearer qualquer não vale
        self.assertEqual(s2.req("GET", "/metrics", headers={"Authorization": "Bearer abc"})[0], 401)

    def test_cookie_flags(self):
        s = Server(self)
        _, _, r = s.req("POST", "/api/auth/setup", {"code": s.auth.setup_code, "password": PW}, headers={"X-H50": "1"})
        c = r.getheader("Set-Cookie")
        self.assertIn("HttpOnly", c)
        self.assertIn("SameSite=Strict", c)

    def test_csrf_protection(self):
        s = Server(self)
        cookie = s.login_cookie()
        no_header = s.req("POST", "/api/robots", {"ip": "1.1.1.1"}, cookie=cookie)[0]
        self.assertEqual(no_header, 403)
        wrong_origin = s.req("POST", "/api/robots", {"ip": "1.1.1.1"}, cookie=cookie,
                             headers={"X-H50": "1", "Origin": "http://evil.example"})[0]
        self.assertEqual(wrong_origin, 403)
        ok = s.req("POST", "/api/robots", {"ip": "1.1.1.1"}, cookie=cookie,
                   headers={"X-H50": "1", "Origin": f"http://127.0.0.1:{s.port}"})[0]
        self.assertNotEqual(ok, 403)                                  # passa do CSRF (depois falha por regra de negócio)
        self.assertEqual(s.req("POST", "/api/auth/login", {"password": PW}, headers={})[0], 403)

    def test_login_rate_limit_over_http(self):
        s = Server(self)
        s.login_cookie()
        codes = [s.req("POST", "/api/auth/login", {"password": "errada"}, headers={"X-H50": "1"})[0] for _ in range(MAX_FAILS + 1)]
        self.assertEqual(codes[:MAX_FAILS], [401] * MAX_FAILS)
        self.assertEqual(codes[-1], 429)
        st, body, r = s.req("POST", "/api/auth/login", {"password": PW}, headers={"X-H50": "1"})
        self.assertEqual(st, 429)
        self.assertTrue(r.getheader("Retry-After"))

    def test_forwarded_for_is_ignored_unless_proxy_is_trusted(self):
        s = Server(self)                                              # trust_proxy desligado
        s.login_cookie()
        for i in range(MAX_FAILS):
            s.req("POST", "/api/auth/login", {"password": "x"}, headers={"X-H50": "1", "X-Forwarded-For": f"10.0.0.{i}"})
        st, _, _ = s.req("POST", "/api/auth/login", {"password": PW}, headers={"X-H50": "1", "X-Forwarded-For": "10.9.9.9"})
        self.assertEqual(st, 429)                                     # trocar o cabeçalho não escapa do limite

    def test_logout_clears_cookie_and_password_change_revokes(self):
        s = Server(self)
        cookie = s.login_cookie()
        _, _, r = s.req("POST", "/api/auth/logout", {}, cookie=cookie, headers={"X-H50": "1"})
        self.assertIn("Max-Age=0", r.getheader("Set-Cookie"))
        st, _, r = s.req("POST", "/api/auth/password", {"current": PW, "new": "outra-senha-1"}, cookie=cookie, headers={"X-H50": "1"})
        self.assertEqual(st, 200)
        self.assertEqual(s.req("GET", "/api/robots", cookie=cookie)[0], 401)           # a antiga caiu
        self.assertEqual(s.req("GET", "/api/robots", cookie=r.getheader("Set-Cookie").split(";")[0])[0], 200)
        self.assertEqual(s.req("POST", "/api/auth/password", {"current": "x", "new": "y"}, headers={"X-H50": "1"})[0], 401)


if __name__ == "__main__":
    unittest.main()
