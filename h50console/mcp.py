"""Servidor MCP (Model Context Protocol) do H50 Console: deixa um assistente de IA consultar e gerenciar o robô.

    py -m h50console mcp            (JSON-RPC por stdin/stdout; o log vai para stderr)

Só fala com a API HTTP do app que já está rodando (H50_MCP_URL, padrão http://127.0.0.1:8050), com a senha em
H50_MCP_PASSWORD. Assim herda tudo o que o app já garante: o perfil (a senha do visualizador só consulta; a do
administrador também comanda), a fila de prioridade do robô, os bloqueios de segurança e o registro de comandos.
Nunca toca no robô nem na nuvem Xiaomi diretamente e não conhece o token do robô.

Segurança extra: tudo o que move o robô ou muda uma configuração exige `confirm: true` no pedido; sem ele a ferramenta só
descreve o que faria. Só biblioteca padrão.
"""

from __future__ import annotations

import http.cookiejar
import json
import logging
import os
import sys
import urllib.error
import urllib.request

from . import __version__, catalog

log = logging.getLogger(__name__)

PROTOCOL = "2025-06-18"
SUPPORTED = ("2025-06-18", "2025-03-26", "2024-11-05")
MAX_TEXT = 12_000          # limite de texto devolvido por ferramenta (o assistente não precisa de mais)

# ações que o assistente pode pedir (o resto do catálogo fica só na interface)
SAFE_ACTIONS = ("stop", "pause", "home", "locate", "charge", "stop-wash", "stop-dry")
MOVING_ACTIONS = ("start", "resume", "sweep", "mop", "sweep-mop", "sweep-then-mop")
BASE_ACTIONS = ("dust", "wash-mop", "dry", "self-clean-base")
ALLOWED_ACTIONS = SAFE_ACTIONS + MOVING_ACTIONS + BASE_ACTIONS


class ToolError(Exception):
    """Falha esperada de uma ferramenta: o texto vai para o assistente como erro, não como falha do protocolo."""


# -- cliente da API ------------------------------------------------------------------------------------------------
class Api:
    def __init__(self, base: str, password: str, timeout: float = 20.0):
        self.base = base.rstrip("/")
        self.password = password
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.logged = False

    def _send(self, method: str, path: str, body=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json", "X-H50": "1", "User-Agent": "h50console-mcp"})
        try:
            with self.opener.open(req, timeout=self.timeout) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as ex:
            try:
                msg = json.loads(ex.read()).get("error", "")
            except (ValueError, OSError):
                msg = ""
            finally:
                ex.close()
            raise ApiHttpError(ex.code, msg or ex.reason) from None
        except (urllib.error.URLError, OSError) as ex:
            raise ToolError(f"não consegui falar com o H50 Console em {self.base}: {getattr(ex, 'reason', ex)}") from None

    def login(self) -> None:
        if not self.password:
            raise ToolError("defina H50_MCP_PASSWORD (a senha do painel, ou a do perfil somente leitura)")
        self._send("POST", "/api/auth/login", {"password": self.password})
        self.logged = True

    def call(self, method: str, path: str, body=None):
        if not self.logged:
            self.login()
        try:
            return self._send(method, path, body)
        except ApiHttpError as ex:
            if ex.status != 401:
                raise
            self.login()                              # sessão vencida ou revogada: entra de novo uma vez
            return self._send(method, path, body)


class ApiHttpError(ToolError):
    def __init__(self, status: int, message: str):
        super().__init__(f"{status}: {message}")
        self.status = status


# -- ferramentas ----------------------------------------------------------------------------------------------------
ROBOT_ARG = {"robot": {"type": "string", "description": "id ou nome do robô (omita se houver só um)"}}


def _schema(props: dict | None = None, required: list | None = None, robot: bool = True) -> dict:
    p = dict(ROBOT_ARG) if robot else {}
    p.update(props or {})
    return {"type": "object", "properties": p, "required": required or [], "additionalProperties": False}


CONFIRM = {"confirm": {"type": "boolean", "description": "true para executar de verdade; sem isso só descreve o que faria"}}

TOOLS = [
    {"name": "robots_list", "description": "Lista os robôs cadastrados com estado, bateria e se estão online.",
     "inputSchema": _schema(robot=False), "annotations": {"readOnlyHint": True}},
    {"name": "robot_status", "description": "Estado atual do robô: status, bateria, se está limpando, falhas e por que não pode iniciar (se for o caso).",
     "inputSchema": _schema(), "annotations": {"readOnlyHint": True}},
    {"name": "consumables", "description": "Vida útil dos consumíveis (escovas, filtro, mop, saco, detergente) e previsão de troca.",
     "inputSchema": _schema(), "annotations": {"readOnlyHint": True}},
    {"name": "cleaning_history", "description": "Últimas limpezas (início, duração, área, tipo, cômodos).",
     "inputSchema": _schema({"limit": {"type": "integer", "minimum": 1, "maximum": 50, "description": "quantas (padrão 10)"}}),
     "annotations": {"readOnlyHint": True}},
    {"name": "rooms", "description": "Cômodos do mapa e quando foram limpos pela última vez.",
     "inputSchema": _schema(), "annotations": {"readOnlyHint": True}},
    {"name": "settings", "description": "Ajustes do robô com os valores atuais (sucção, água, volume, não perturbe etc.).",
     "inputSchema": _schema(), "annotations": {"readOnlyHint": True}},
    {"name": "faults", "description": "Falhas registradas pelo robô.", "inputSchema": _schema(), "annotations": {"readOnlyHint": True}},
    {"name": "clean_rooms",
     "description": "Limpa os cômodos indicados (nomes ou ids). O robô SAI da base: exige confirm=true. Só no perfil de administrador.",
     "inputSchema": _schema({"rooms": {"type": "array", "items": {"type": ["string", "integer"]}, "minItems": 1}, **CONFIRM}, ["rooms"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "robot_action",
     "description": "Executa uma ação: " + ", ".join(ALLOWED_ACTIONS) + ". As que movem o robô ou mexem na base exigem confirm=true. "
                    "Só no perfil de administrador.",
     "inputSchema": _schema({"action": {"type": "string", "enum": list(ALLOWED_ACTIONS)}, **CONFIRM}, ["action"]),
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "set_setting",
     "description": "Altera um ajuste do robô (use `settings` para ver as chaves, ex.: 2/9) — exige confirm=true. Só no perfil de administrador.",
     "inputSchema": _schema({"key": {"type": "string", "description": "chave do ajuste, como 4/2"}, "value": {"description": "novo valor"}, **CONFIRM},
                            ["key", "value"]),
     "annotations": {"readOnlyHint": False, "idempotentHint": True}},
]


class Tools:
    def __init__(self, api: Api):
        self.api = api
        self._robots: list[dict] | None = None

    # -- resolução do robô ------------------------------------------------------------------------------------------
    def robots(self, fresh: bool = False) -> list[dict]:
        if self._robots is None or fresh:
            self._robots = self.api.call("GET", "/api/robots") or []
        return self._robots

    def prefix(self, ref) -> str:
        robots = self.robots()
        if not robots:
            raise ToolError("nenhum robô cadastrado no H50 Console")
        if ref in (None, ""):
            if len(robots) > 1:
                names = ", ".join(f"{r['name']} ({r['id']})" for r in robots)
                raise ToolError(f"há {len(robots)} robôs; informe `robot`: {names}")
            return f"/api/r/{robots[0]['id']}"
        key = str(ref).strip().casefold()
        for r in robots:
            if key in (str(r["id"]).casefold(), str(r["name"]).casefold()):
                return f"/api/r/{r['id']}"
        raise ToolError(f"robô '{ref}' não encontrado; use robots_list")

    # -- leitura ---------------------------------------------------------------------------------------------------------
    def robots_list(self, args):
        rows = self.robots(fresh=True)
        return [{k: r.get(k) for k in ("id", "name", "model", "online", "via", "status_label", "battery", "active")} for r in rows]

    def robot_status(self, args):
        p = self.prefix(args.get("robot"))
        st = self.api.call("GET", p + "/state")
        keep = ("2/6", "2/7", "2/2", "3/1")
        return {"status": st["status_label"], "battery_percent": st["battery"], "active": st["active"],
                "cannot_start_because": st["block_start"], "online": st["health"].get("online"), "via": st["health"].get("via"),
                "details": {r["label"]: r["value"] for r in st["rows"] if r["value"] not in (None, "")} if st.get("rows") else {},
                "faults": self.api.call("GET", p + "/faults")[:3]}

    def consumables(self, args):
        rows = self.api.call("GET", self.prefix(args.get("robot")) + "/consumables")
        out = []
        for r in rows:
            f = r.get("forecast")
            out.append({"item": r["name"], "life_percent": r["pct"], "hours_left": r["hours"], "needs_attention": r["alert"],
                        "estimated_replacement": f"em ~{f['days_left']} dia(s), por volta de {f['date']}" if f else "sem dados suficientes"})
        return out

    def cleaning_history(self, args):
        limit = max(1, min(50, int(args.get("limit") or 10)))
        d = self.api.call("GET", self.prefix(args.get("robot")) + "/history")
        rows = [{"start": r["start"], "type": r.get("type_label"), "minutes": round((r["duration_s"] or 0) / 60),
                 "area_m2": r["area_m2"], "rooms": r["room_names"] or r.get("routine"), "has_path": r.get("has_path")}
                for r in d["records"][:limit]]
        return {"totals_in_history": d["totals"], "latest": rows}

    def rooms(self, args):
        return self.api.call("GET", self.prefix(args.get("robot")) + "/rooms")

    def settings(self, args):
        rows = self.api.call("GET", self.prefix(args.get("robot")) + "/settings")
        return [{"key": r["key"], "name": r["label"], "group": r["group"], "value": r.get("display", r["value"]),
                 "options": [o[1] if isinstance(o, list) else o for o in r.get("options", [])] or None, "range": r.get("range")}
                for r in rows]

    def faults(self, args):
        return self.api.call("GET", self.prefix(args.get("robot")) + "/faults")

    # -- comandos (exigem confirm) -----------------------------------------------------------------------------------
    @staticmethod
    def _need_confirm(args, what: str):
        if args.get("confirm") is True:
            return None
        return {"executed": False, "would_do": what,
                "next_step": "Se for isso mesmo, chame a ferramenta de novo com confirm=true (confirme antes com o usuário)."}

    def clean_rooms(self, args):
        p = self.prefix(args.get("robot"))
        wanted = args.get("rooms") or []
        known = self.api.call("GET", p + "/rooms")
        ids, names = [], []
        for w in wanted:
            hit = next((r for r in known if str(r["id"]) == str(w) or r["name"].casefold() == str(w).strip().casefold()), None)
            if hit is None:
                raise ToolError(f"cômodo '{w}' não existe; opções: {', '.join(r['name'] for r in known)}")
            ids.append(hit["id"])
            names.append(hit["name"])
        pending = self._need_confirm(args, f"iniciar a limpeza dos cômodos: {', '.join(names)} (o robô sai da base)")
        if pending:
            return pending
        return {"executed": True, "rooms": names, "result": self.api.call("POST", p + "/clean/rooms", {"ids": ids})}

    def robot_action(self, args):
        p = self.prefix(args.get("robot"))
        action = args.get("action")
        if action not in ALLOWED_ACTIONS:
            raise ToolError(f"ação não permitida: {action!r}")
        if action in MOVING_ACTIONS or action in BASE_ACTIONS:
            pending = self._need_confirm(args, f"executar '{action}'" + (" (o robô sai da base)" if action in catalog.LEAVES_BASE else ""))
            if pending:
                return pending
        return {"executed": True, "action": action, "result": self.api.call("POST", f"{p}/actions/{action}", {})}

    def set_setting(self, args):
        p = self.prefix(args.get("robot"))
        key = str(args.get("key", "")).strip()
        if "value" not in args:
            raise ToolError("informe `value`")
        pending = self._need_confirm(args, f"alterar o ajuste {key} para {json.dumps(args['value'], ensure_ascii=False)}")
        if pending:
            return pending
        res = self.api.call("PUT", f"{p}/settings/{key.replace('/', '-')}", {"value": args["value"]})
        return {"executed": True, "key": key, "result": res}

    def call(self, name: str, args: dict):
        fn = {t["name"]: getattr(self, t["name"]) for t in TOOLS}.get(name)
        if fn is None:
            raise ToolError(f"ferramenta desconhecida: {name}")
        try:
            return fn(args or {})
        except ApiHttpError as ex:
            if ex.status == 403:
                raise ToolError("recusado: esta senha é do perfil somente leitura (só consulta). Use a senha de administrador para comandos.") from None
            raise


# -- protocolo JSON-RPC -------------------------------------------------------------------------------------------------
class Server:
    def __init__(self, tools: Tools):
        self.tools = tools

    def _result(self, mid, result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def _error(self, mid, code: int, message: str):
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}

    def handle(self, msg: dict) -> dict | None:
        """Uma mensagem JSON-RPC -> resposta (ou None para notificações)."""
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._error(msg.get("id") if isinstance(msg, dict) else None, -32600, "requisição inválida")
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if "id" not in msg:                         # notificação (ex.: notifications/initialized): sem resposta
            return None
        if method == "initialize":
            asked = params.get("protocolVersion")
            return self._result(mid, {"protocolVersion": asked if asked in SUPPORTED else PROTOCOL,
                                      "capabilities": {"tools": {"listChanged": False}},
                                      "serverInfo": {"name": "h50console", "version": __version__},
                                      "instructions": "Consulta e gerencia aspiradores Xiaomi pelo H50 Console. Comandos que movem o "
                                                      "robô ou mudam ajustes exigem confirm=true: confirme com o usuário antes."})
        if method == "ping":
            return self._result(mid, {})
        if method == "tools/list":
            return self._result(mid, {"tools": TOOLS})
        if method == "tools/call":
            name = params.get("name")
            if name not in {t["name"] for t in TOOLS}:
                return self._error(mid, -32602, f"ferramenta desconhecida: {name}")
            try:
                out = self.tools.call(name, params.get("arguments") or {})
                text, bad = json.dumps(out, ensure_ascii=False, indent=1, default=str), False
            except ToolError as ex:
                text, bad = str(ex), True
            except Exception as ex:  # noqa: BLE001 - nunca derruba o servidor por uma ferramenta
                log.exception("erro na ferramenta %s", name)
                text, bad = f"erro interno: {type(ex).__name__}", True
            if len(text) > MAX_TEXT:
                text = text[:MAX_TEXT] + "\n… (cortado)"
            return self._result(mid, {"content": [{"type": "text", "text": text}], "isError": bad})
        return self._error(mid, -32601, f"método não suportado: {method}")

    def serve(self, stdin=None, stdout=None) -> None:
        stdin, stdout = stdin or sys.stdin, stdout or sys.stdout
        for line in stdin:
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                reply = self._error(None, -32700, "JSON inválido")
            else:
                reply = [r for r in (self.handle(m) for m in msg) if r] if isinstance(msg, list) else self.handle(msg)
            if reply:
                stdout.write(json.dumps(reply, ensure_ascii=False) + "\n")
                stdout.flush()


def main() -> int:
    base = os.environ.get("H50_MCP_URL", "http://127.0.0.1:8050")
    password = os.environ.get("H50_MCP_PASSWORD", "")
    if not password:
        print("Defina H50_MCP_PASSWORD (senha do painel ou do perfil somente leitura). "
              "H50_MCP_URL aponta para o painel (padrão http://127.0.0.1:8050).", file=sys.stderr)
        return 2
    log.info("MCP do H50 Console falando com %s", base)
    Server(Tools(Api(base, password))).serve()
    return 0
