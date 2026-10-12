# H50 Console: app web local para controlar e monitorar o Xiaomi H50 Pro

> Especificação para desenvolvimento, de 11/10/2026. Base técnica: [xiaomi-h50-pro-hacking.md](xiaomi-h50-pro-hacking.md) e `h50pro.py`.
> Os dados reais vêm do `dump.json` e do `rooms` do robô (`xiaomi.vacuum.ov42gl`, fw `4.5.8_0087`, IP `192.168.1.50`).

---

## 1. Objetivo e escopo

**Objetivo:** um painel no navegador do PC (`http://localhost:8050`) para ver o estado do robô em tempo quase real, comandar limpezas e ajustes e guardar histórico, tudo **na LAN** via MIoT/UDP 54321, sem passar pela nuvem.

| MVP (fase 1) | Depois (fases 2–3) | Fora de escopo |
|---|---|---|
| Estado ao vivo, ações, limpeza por cômodo, ajustes, consumíveis, histórico importado do robô, log de comandos | MQTT/Home Assistant, notificações, `/metrics` para Prometheus/Grafana, edição de agendamentos | Mapa ao vivo (só existe na nuvem), root/firmware, acesso pela internet |

---

## 2. Arquitetura

```
 Navegador (HTMX + JS)
     │  HTTP / SSE  (127.0.0.1:8050)
 ┌───▼──────────────────────────────── FastAPI ───────────────────────────────┐
 │  API REST  ──►  CommandService ──┐                                          │
 │  SSE /stream ◄── EventBus ◄──┐   │                                          │
 │                              │   ▼                                          │
 │  Poller (asyncio) ──────► DeviceGateway  (1 requisição por vez: asyncio.Lock)│
 │      │                       │  usa H50Pro de h50pro.py (python-miio)       │
 │      ▼                       │                                              │
 │  Repository (SQLAlchemy) ──► SQLite (padrão) | PostgreSQL (opcional)        │
 └──────────────────────────────┼──────────────────────────────────────────────┘
                                ▼  UDP 54321 (miIO/MIoT, AES com token)
                         H50 Pro 192.168.1.50
```

**Princípios**
- **Um único dono do socket:** todo acesso ao robô passa pelo `DeviceGateway`, serializado. O robô responde mal a requisições concorrentes e lotes grandes.
- **O poller alimenta tudo.** A UI lê o **cache em memória** e o banco, nunca o robô direto. Ações do usuário entram na fila do gateway com prioridade sobre o poll.
- **Gravar só mudanças** (event-sourcing leve), para o banco ficar pequeno.

---

## 3. Stack

| Camada | Escolha | Motivo |
|---|---|---|
| Linguagem | Python 3.12+ (validado no seu PC com 3.14) | Reaproveita `h50pro.py` e python-miio |
| Protocolo | python-miio, **fixado no commit** `9a00e08` | A versão do PyPI é antiga; fixar dá build reprodutível |
| Web | FastAPI + Uvicorn | Async, OpenAPI automático em `/docs` |
| Tempo real | SSE (`text/event-stream`) | Mais simples que WebSocket, e o fluxo é só servidor→navegador |
| UI | Jinja2 + HTMX + JS puro, **tabelas filtráveis** | Sem build de front-end, interface limpa |
| Banco | SQLAlchemy 2 + Alembic. SQLite em modo WAL (padrão) ou PostgreSQL via `DATABASE_URL` | SQLite basta para um robô; Postgres se quiser Grafana/BI |
| Execução | Docker Compose (recomendado) ou `py -m uvicorn` nativo | Ver §10 |
| Config | `.env` com `H50_IP`, `H50_TOKEN`, `DATABASE_URL`, `POLL_*` | O token nunca vai para o git |

---

## 4. Comportamento do robô que o app precisa respeitar

Observado no aparelho real:

| # | Comportamento | Implicação no app |
|---|---|---|
| D1 | Lote de 10 propriedades pode **ficar sem resposta** (timeout) | Lotes de **≤ 5**. Se um lote falhar, ler item a item (`get_tolerant`). Possível causa: buffer de 4 KB do python-miio |
| D2 | Resposta traz `did` = **device id** (`<DID>`), ignorando o `did` enviado | Casar resultados por `(siid, piid)` |
| D3 | Só métodos **MIoT** funcionam (`get_properties`, `set_properties`, `action`, `miIO.info`) | Não usar métodos miIO legados |
| D4 | Várias propriedades são **strings JSON** (2/16, 2/19, 2/42, 2/66, 10/3…) | Camada `decoders.py` com parse e validação |
| D5 | `cleaning-progress` (2/89) = **-1** quando não há limpeza | Mostrar "—" |
| D6 | O mapa (10/1, 10/2, 10/5) é só um **nome de objeto na nuvem** (`<UID>/<DID>/0`) | Sem mapa no MVP |
| D7 | O token muda se o robô for re-pareado | Tela de diagnóstico e `.env` fácil de trocar. Erro de checksum = token inválido |
| D8 | Timeout gera **re-handshake** no python-miio (~5 s × tentativas) | `retry_count=1`, backoff exponencial e estado "offline" na UI |

---

## 5. O que monitorar e com que frequência

Frequências: **ativo** = status em limpeza, mapeamento ou base trabalhando; **ocioso** = carregando ou parado.

| Grupo | Propriedades (siid/piid) | Ativo | Ocioso |
|---|---|---|---|
| **Rápido** | 2/2 status, 2/3 fault, 2/96 sweep-mop-status, 2/89 progresso, 2/6 área, 2/7 tempo, 3/1 bateria, 3/2 carga, 2/18 status da base, 2/88 progresso da secagem, 2/90 tempo restante de secagem, 2/97 tanque sujo, 2/98 tanque limpo | 5 s | 30 s |
| **Ajustes** | 2/4 modo, 2/8 passadas, 2/9 sucção, 2/10 água, 2/28–2/36 base (lavagem, secagem, autoesvaziamento), 2/41 água quente, 2/73–2/84 tapete/rota/obstáculo/temperatura, 4/2 volume, 5/1 trava, 11/1–11/2 DND | após cada `set` | 5 min |
| **Consumíveis** | 9/1–2 mop, 12/1–2 escova principal, 13/1–2 escova lateral, 14/1–2 filtro, 18/1 e 18/4 detergente, 19/1–2 saco | – | 30 min |
| **Estrutura** | 2/16 cômodos, 2/42 limpezas personalizadas, 2/19 agendamentos, 10/5 mapas, 10/6 mapa atual, 2/1 firmware da base | – | 1 h + no boot |
| **Histórico** | 10/3 clean-record, 2/17 última limpeza, 2/66 lista de falhas | ao voltar à base | 15 min |

**Status "ativos" (2/2):** 4, 5, 6, 7, 10, 12, 13, 16, 17, 18, 19, 20, 21, 22, 24.

---

## 6. Decodificações (validadas com os seus dados)

| Prop | Exemplo real | Decodificação | Confiança |
|---|---|---|---|
| **10/3** clean-record | `{"total_time":188,"total_area":151780,"total_count":12,"history_list":[{"label":"01620_24450_3_14649_0","stime":1791725784},…]}` | `label` = `<duração s>_<área m²×1000>_<sweep-type>_<?>_<?>`. `stime` = epoch UTC. Totais: `total_time` em **min**, `total_area` em **m²×1000** | **Alta.** O último registro bate com 2/7 = 1620 s, 2/6 = 24,45 m² e 2/17 = 10:36. A soma dos 12 registros bate com os totais (11.280 s = 188 min; 151,78 m²) |
| **2/19** agendamentos | `{"id":[…],"on":[1,1],"week":[190,193],"time":[1566,2078],"clean_conf":[{"mode":7,"cid":1791675441},…]}` | `week`: bit0 = domingo … bit6 = sábado, bit7 = repetir. Então 190 = seg–sex e 193 = sáb+dom. `time` = `hora×256 + min`, hora local: 1566 = **06:30**, 2078 = **08:30**. `mode` 7 = limpeza personalizada `cid` | **Alta.** Houve limpeza tipo 7 no domingo 11/10 às 08:30 |
| **11/2** DND | `385878016` = `0x17000800` | bytes `[h_ini, m_ini, h_fim, m_fim]` = **23:00–08:00** (11/1 = false, desativado) | Alta |
| **2/16** cômodos | `{"rooms":[{"id":3,"name":"Sala de estar"},…],"map_uid":1}` | ids 3 Sala de estar, 4 Quarto de criança, 5 Quarto, 6 Cozinha, 7 Banheiro, 8 Corredor | Confirmado |
| **2/42** limpezas personalizadas | `{"user_labels":[{"id":1791675441,"name":"Sala intenso","mop":[3],"room_ids":[3,8],"en":1,…}]}` | Rotina "Sala intenso" = cômodos 3 e 8, mop nível 3. Como iniciar: ver P3 | Formato: alta. Disparo: **a validar** |
| **2/66** fault-ids | `{"ts":1791736164,"fault":[210013]}` | Lista de falhas ativas, com timestamp | Formato: alta. **210013 = provavelmente filtro/caixa de pó removido** (hipótese, ver P1) |
| **2/18** status da base | `{"mode":0,"progress":0}` | Modo/progresso da base (lavar, secar, esvaziar) | Média. Mapear valores durante a secagem |
| **2/40** config atual | `{"clean_mode":1,"is_ai_cleaning":false,"dirty_cleaning":false}` | – | Média |
| **2/1** firmware | `{"base_version":"1.0-0.0.44"}` | Firmware da base | Alta |
| **2/67** action-result | `{"type":3,"code":0,"index":…}` | Resultado da última ação (`code 0` = ok) | Média. Útil para confirmar comandos |
| **10/1–10/5, 10/13** | `{"obj_name":"<UID>/<DID>/2",…}` | Referências a objetos na nuvem (`uid/did/n`) | – |

**Tipos de limpeza (3º campo do label = 2/5 sweep-type):** 1 casa toda · 2 zona · 3 cômodos · 7 personalizada · 10 mapeamento rápido.

---

## 7. Banco de dados

DDL compatível com SQLite e PostgreSQL. No Postgres, use `TIMESTAMPTZ` e `JSONB`.

```sql
-- mudança de qualquer propriedade (só grava quando o valor muda)
CREATE TABLE prop_change (
  id         INTEGER PRIMARY KEY,        -- BIGSERIAL no Postgres
  ts         TIMESTAMP NOT NULL,
  prop       TEXT NOT NULL,              -- '2/2'
  old_value  TEXT,
  new_value  TEXT NOT NULL
);
CREATE INDEX ix_prop_change_prop_ts ON prop_change (prop, ts);

-- histórico de limpezas importado do 10/3 (idempotente por stime)
CREATE TABLE cleaning_record (
  stime       TIMESTAMP PRIMARY KEY,     -- início (UTC)
  duration_s  INTEGER NOT NULL,
  area_m2     NUMERIC(8,3) NOT NULL,
  sweep_type  INTEGER NOT NULL,          -- 1 casa, 2 zona, 3 cômodos, 7 personalizada, 10 mapeamento
  raw_label   TEXT NOT NULL,
  imported_at TIMESTAMP NOT NULL
);

-- foto diária dos consumíveis (curva de desgaste)
CREATE TABLE consumable_snapshot (
  day      DATE NOT NULL,
  item     TEXT NOT NULL,                -- mop | main_brush | side_brush | filter | dust_bag | detergent
  pct      INTEGER,
  hours    INTEGER,
  PRIMARY KEY (day, item)
);

-- auditoria de tudo que o app mandou ao robô
CREATE TABLE command_log (
  id          INTEGER PRIMARY KEY,
  ts          TIMESTAMP NOT NULL,
  source      TEXT NOT NULL,             -- ui | api | scheduler
  command     TEXT NOT NULL,             -- action:2/16 | set:2/9 | get
  params      TEXT,                      -- JSON
  result_code TEXT,
  latency_ms  INTEGER
);

-- falhas (de 2/3 e 2/66)
CREATE TABLE fault_event (
  id      INTEGER PRIMARY KEY,
  ts      TIMESTAMP NOT NULL,
  code    INTEGER NOT NULL,
  cleared TIMESTAMP
);

-- cadastros
CREATE TABLE room (map_uid INTEGER, id INTEGER, name TEXT, PRIMARY KEY (map_uid, id));
```

**Retenção:**
- `prop_change` dos grupos rápidos: 90 dias (job diário).
- `cleaning_record` e `command_log`: sem expiração.

---

## 8. API

| Método | Rota | Função |
|---|---|---|
| GET | `/api/health` | App + último contato com o robô + latência |
| GET | `/api/state` | Estado normalizado (cache), incluindo `online` |
| GET | `/api/stream` | **SSE**: evento `state` a cada mudança e `offline`/`online` |
| GET | `/api/rooms` | Cômodos do mapa atual |
| POST | `/api/clean/rooms` | `{"ids":[6,7]}` → ação 2/16 com `"6,7"` |
| POST | `/api/clean/custom/{cid}` | Rotina personalizada (forma de disparo em P3; fallback: cômodos da rotina) |
| POST | `/api/actions/{name}` | `start, pause, resume, stop, home, dust, wash-mop, dry, stop-dry, locate, self-clean-base` |
| GET / PUT | `/api/settings` / `/api/settings/{key}` | Lê o catálogo de ajustes / grava `{"value":…}` e relê a propriedade |
| GET / POST | `/api/consumables` / `/api/consumables/{item}/reset` | Vida útil e reset |
| GET | `/api/history?from=&to=&type=` | `cleaning_record` + totais |
| GET | `/api/schedules` | 2/19 decodificado (**somente leitura** no MVP) |
| GET | `/api/commands`, `/api/faults` | Logs |
| POST | `/api/raw/{get\|set\|action}` | Explorador (só com `RAW_ENABLED=true`) |
| GET | `/metrics` | Fase 2: Prometheus (`h50_battery_pct`, `h50_status`, `h50_consumable_pct{item}`…) |

**Regras dos comandos**
- Toda ação grava em `command_log` e força um poll rápido logo depois.
- Ações que **tiram o robô da base** (start, clean/rooms, spot) pedem confirmação na UI.
- Bloqueio: não iniciar limpeza se 2/2 ∈ {7 lavando mop, 11 atualizando, 12/14 base trabalhando}. A UI mostra o motivo.

---

## 9. Interface (tabelas filtráveis, pouco texto)

| Tela | Conteúdo |
|---|---|
| **Painel** | Barra de ações (Iniciar · Pausar · Base · Esvaziar pó · Lavar mop · Secar · Localizar) + tabela **Estado** (`propriedade · valor · atualizado`), com filtro por texto e destaque de linha quando o valor muda. Indicador online/offline e latência |
| **Cômodos** | Tabela `☐ · id · nome · última limpeza`, com botão "Limpar selecionados". Abaixo, tabela das rotinas personalizadas (2/42) com botão "Executar" |
| **Ajustes** | Tabela `ajuste · valor atual · opções` com select/toggle inline. As opções vêm do catálogo de enums da spec |
| **Consumíveis** | Tabela `item · % · horas restantes · reset`, com linha em alerta abaixo de 10 % |
| **Histórico** | Tabela filtrável `início · tipo · duração · área`, com filtro de período e tipo e linha de totais |
| **Agenda** | Tabela `ativo · dias · hora · rotina`, decodificada de 2/19 |
| **Eventos** | Abas: Falhas (`fault_event`) e Comandos (`command_log`) |
| **Explorador** | `siid/piid` → get/set e `siid/aiid` → action com JSON livre (modo dev) |

Filtro de tabela: um `<input>` por coluna, filtrando no cliente (JS puro), com ordenação por clique no cabeçalho. Sem cards e sem gráficos no MVP.

---

## 10. Execução em container

**Estrutura do repositório**
```
h50-console/
├─ app/
│  ├─ main.py            # FastAPI, rotas, startup/shutdown
│  ├─ gateway.py         # DeviceGateway (lock, retry, backoff, métricas de latência)
│  ├─ h50pro.py          # cópia do script (classe H50Pro + tabelas de enum)
│  ├─ catalog.py         # propriedades/ações/enums da spec ov42gl (do anexo do .md)
│  ├─ decoders.py        # 10/3, 2/19, 11/2, 2/16, 2/42, 2/66…
│  ├─ poller.py          # grupos e frequências do §5, detecção de ativo/ocioso
│  ├─ repo.py            # SQLAlchemy models + queries
│  ├─ events.py          # EventBus para SSE
│  └─ templates/ static/ # Jinja2 + HTMX + table.js
├─ migrations/           # Alembic
├─ tests/fixtures/dump.json   # o dump real (não publicar: contém uid/did)
├─ Dockerfile  docker-compose.yml  .env.example  .gitignore
```

**Dockerfile**
```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ app/
ENV PYTHONUNBUFFERED=1
EXPOSE 8050
HEALTHCHECK --interval=30s CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8050/api/health')"
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8050"]
```

**requirements.txt** (python-miio fixado por commit)
```
python-miio @ https://github.com/rytilahti/python-miio/archive/9a00e0888ef85f8d8d84888cabd9e46d1b0a18df.zip
fastapi
uvicorn[standard]
sqlalchemy>=2
alembic
jinja2
python-dotenv
psycopg[binary]      # só se usar Postgres
```

**docker-compose.yml**
```yaml
services:
  h50:
    build: .
    env_file: .env
    ports: ["127.0.0.1:8050:8050"]   # só localhost
    volumes: ["./data:/data"]        # SQLite: DATABASE_URL=sqlite:////data/h50.db
    restart: unless-stopped

  db:                                # opcional: docker compose --profile pg up -d
    image: postgres:17
    profiles: ["pg"]
    environment:
      POSTGRES_DB: h50
      POSTGRES_USER: h50
      POSTGRES_PASSWORD: ${PG_PASSWORD}
    volumes: ["pgdata:/var/lib/postgresql/data"]
    ports: ["127.0.0.1:5432:5432"]
volumes:
  pgdata:
```

**Rede no Docker Desktop (Windows):**
- A rede bridge padrão funciona: o UDP de saída para `192.168.1.50:54321` volta pelo NAT. Não precisa de `network_mode: host`.
- Se o PC estiver em VPN corporativa, o tráfego para a LAN pode ser desviado. Teste com o `h50pro.py info` dentro do container: `docker compose exec h50 python app/h50pro.py info`.

**Sem Docker:** `py -m pip install -r requirements.txt` e depois `py -m uvicorn app.main:app --port 8050`.

**.env.example**
```
H50_IP=192.168.1.50
H50_TOKEN=
DATABASE_URL=sqlite:////data/h50.db
POLL_FAST_ACTIVE=5
POLL_FAST_IDLE=30
RAW_ENABLED=false
```

---

## 11. Núcleo de código (referência)

```python
# gateway.py
import asyncio, time
from miio.exceptions import DeviceException
from .h50pro import H50Pro

class DeviceGateway:
    def __init__(self, ip: str, token: str, timeout: int = 5):
        self.vac = H50Pro(ip, token, timeout=timeout)
        self._lock = asyncio.Lock()
        self.online = False
        self.last_latency_ms: int | None = None

    async def call(self, fn, *args, **kw):
        """Serializa TODO acesso ao robô; roda o python-miio (síncrono) numa thread."""
        async with self._lock:
            t0 = time.perf_counter()
            try:
                res = await asyncio.to_thread(fn, *args, **kw)
                self.online = True
                return res
            except DeviceException:
                self.online = False
                raise
            finally:
                self.last_latency_ms = int((time.perf_counter() - t0) * 1000)
```

```python
# poller.py: laço rápido com intervalo adaptativo e backoff
ACTIVE = {4, 5, 6, 7, 10, 12, 13, 16, 17, 18, 19, 20, 21, 22, 24}

async def fast_loop(gw, repo, bus, cfg):
    fails = 0
    while True:
        try:
            rows = await gw.call(gw.vac.get_tolerant, FAST_PROPS, progress=False)
            state = normalize(rows)                 # {'2/2': 2, '3/1': 95, …}
            changes = cache.diff_and_update(state)  # só o que mudou
            await repo.save_changes(changes)
            await bus.publish("state", cache.snapshot())
            if cache.just_returned_to_base():       # ex.: 4 -> 6 -> 2
                await import_history(gw, repo)      # lê 10/3 e grava sem duplicar
            interval = cfg.fast_active if state.get("2/2") in ACTIVE else cfg.fast_idle
            fails = 0
        except DeviceException:
            fails += 1
            await bus.publish("offline", {"fails": fails})
            interval = min(300, 10 * 2 ** fails)
        await asyncio.sleep(interval)
```

```python
# decoders.py: exemplos validados
def clean_record(raw: str) -> list[dict]:
    data = json.loads(raw)
    out = []
    for h in data["history_list"]:
        dur, area, stype, *_ = h["label"].split("_")
        out.append({"stime": h["stime"], "duration_s": int(dur),
                    "area_m2": int(area) / 1000, "sweep_type": int(stype), "raw_label": h["label"]})
    return out

def schedules(raw: str) -> list[dict]:
    d = json.loads(raw)
    days = ["dom", "seg", "ter", "qua", "qui", "sex", "sáb"]
    return [{"id": i, "on": bool(on),
             "days": [days[b] for b in range(7) if w >> b & 1], "repeat": bool(w >> 7 & 1),
             "time": f"{t >> 8:02d}:{t & 0xFF:02d}", "conf": conf}
            for i, on, w, t, conf in zip(d["id"], d["on"], d["week"], d["time"], d["clean_conf"])]

def dnd_period(v: int) -> str:
    return f"{v >> 24 & 0xFF:02d}:{v >> 16 & 0xFF:02d}–{v >> 8 & 0xFF:02d}:{v & 0xFF:02d}"
```

---

## 12. Testes

| Nível | Como |
|---|---|
| Unitário | `decoders.py` contra `tests/fixtures/dump.json` (o dump real). Os totais de 10/3 têm de bater (188 min, 151,78 m², 12 limpezas) |
| Gateway | `FakeDevice` com o mesmo `send()` do python-miio: devolve valores do dump e simula timeout em lote e falha de item. Foi assim que o `h50pro.py` foi validado |
| Integração | Simulador MIoT do python-miio (`miiocli devtools miot-simulator`). Tem bugs com `value-range`, então prefira o FakeDevice |
| Manual no robô | Checklist: `info` → `status` → `locate` → ajuste reversível (volume) → `clean-rooms banheiro` → `home`. **Não** mandar ação enquanto 2/2 = 7/12/14 (base trabalhando, como na secagem) |

---

## 13. Segurança

- Bind em **127.0.0.1**. Se for expor na LAN, coloque um proxy com autenticação (Caddy/Traefik + basic auth) e um IP fixo de origem.
- `H50_TOKEN` só no `.env` (no `.gitignore`). Logs **mascaram** o token.
- Explorador `raw` desligado por padrão: escrever em piid desconhecido pode mudar o comportamento do robô.
- O app nunca chama a nuvem Xiaomi.

---

## 14. Roadmap

| Fase | Entregas | Critério de aceite |
|---|---|---|
| **1 – MVP** | Gateway + poller + Painel + Cômodos + Ajustes + Consumíveis + log de comandos (SQLite) | Status na UI em ≤ 5 s com o robô ativo e ≤ 30 s ocioso; offline detectado em ≤ 60 s sem travar a UI; nenhuma chamada concorrente ao robô; `docker compose up -d` sobe limpo |
| **2 – Histórico e observabilidade** | Importação do 10/3, telas Histórico/Agenda/Eventos, `/metrics`, Postgres opcional, Grafana | 10/3 importado sem duplicar; painel Grafana com bateria, status e consumíveis |
| **3 – Integrações** | MQTT com discovery do Home Assistant, notificações (ntfy/Telegram: tanque cheio 2/97, tanque vazio 2/98, consumível < 10 %, falha nova), edição de agendamentos (ações 2/23–25) | Entidades aparecem no HA sozinhas; notificação em ≤ 1 min do evento |
| **Opcional** | Mapa via nuvem (login Xiaomi e download do `obj_name`, como fazem o xiaomi-vac e o Map Extractor) | Fica fora do "100 % local" |

---

## 15. Pendências a investigar

| # | Item | Como descobrir |
|---|---|---|
| P1 | Confirmar `fault 210013` = **filtro (ou caixa de pó) fora do robô**. Em 11/10 os filtros estavam sendo lavados e o `2/66` registrou a falha às 13:29:24 | Recolocar os filtros e rodar `py h50pro.py get 2 3` e `get 2 66`. Se o 2/3 voltar a 0 e a lista `fault` esvaziar, está confirmado. Depois, montar a tabela `fault_code → descrição` em `catalog.py` registrando cada código novo com o que estava acontecendo |
| P2 | Valores de 2/18 (status da base) durante secagem, lavagem e esvaziamento | Pollar 2/18, 2/88 e 2/90 a cada 5 s durante a secagem atual e registrar |
| P3 | Como disparar a rotina personalizada e editar agendamentos (2/23–25, `common-params` JSON) | A ação 2/42 recebe piid 43 (**uint16**), mas o `cid` 1791675441 não cabe nisso. Testar 2/43 (id atual) durante uma rotina, 2/9 `start-custom-sweep` e, se nada servir, usar `clean/rooms` com os `room_ids` da rotina (3,8). Para agendamentos, observar 2/19 antes e depois de editar no app |
| P4 | Campos 4 e 5 do label do 10/3 (`14649`, `0`) | Comparar registros de mapas ou resultados diferentes (limpeza interrompida?) |
| P5 | Quantos registros o 10/3 guarda (12 hoje) | Acompanhar se o mais antigo sai. Define a frequência mínima de importação |
| P6 | Causa exata do timeout em lote de 10 | `h50pro.py --debug` com lote de 10 e ver se é o tamanho da resposta (> 4 KB) |
