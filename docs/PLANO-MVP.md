# H50 Console: plano do MVP sem dependências

> 11/10/2026. Base: [h50-console-spec.md](h50-console-spec.md). Objetivo: o MVP inteiro com a **biblioteca padrão do Python 3.12+**, sem `pip install`.

## 1. Por que dá para não ter dependências

O protocolo miIO (ver [xiaomi-h50-pro-hacking.md](xiaomi-h50-pro-hacking.md) §2.3) é pequeno:

| Peça | Biblioteca padrão |
|---|---|
| Handshake de 32 bytes (`0x2131` + `0xFF…`), que devolve DID e stamp | `socket`, `struct` |
| Header com checksum `MD5(header + token + dados)` | `hashlib` |
| Payload AES-128-CBC, `key = MD5(token)`, `iv = MD5(key + token)`, PKCS7 | **AES em Python puro** (`aes.py`) |

Ganhos de ter o próprio transporte:
- **D1/P6:** buffer de recepção de 64 KB (o python-miio usa 4 KB).
- **D8:** guarda o DID e o stamp e só refaz o handshake depois de uma falha.
- O app descarta respostas atrasadas cujo `id` não bate com o da requisição.

O python-miio continua só como **ferramenta de desenvolvimento**, para comparar resultados nos testes.

## 2. O que muda em relação à spec

| Na spec | No MVP |
|---|---|
| python-miio | `miio.py` próprio |
| FastAPI + Uvicorn | `http.server.ThreadingHTTPServer` + roteador simples |
| SSE via asyncio | Uma thread por cliente + `queue.Queue` |
| `asyncio.Lock` | `threading.Lock` (um único dono do socket) |
| SQLAlchemy + Alembic | `sqlite3` em WAL + `PRAGMA user_version` |
| Jinja2 + HTMX | HTML estático + JS puro (`fetch`, `EventSource`) |
| python-dotenv | Leitor de `.env` próprio |
| pytest | `unittest` |
| Docker / Postgres | Fase 2 |

## 3. Estrutura

```
h50console/
├─ __main__.py   # py -m h50console
├─ aes.py        # AES-128-CBC puro + PKCS7
├─ miio.py       # MiioClient: handshake, pacote, send() com retry
├─ device.py     # H50: get/set/action, get_tolerant, casar por (siid, piid)
├─ catalog.py    # enums, ações, grupos de polling, status ativos
├─ decoders.py   # 2/16, 2/42, 2/19, 11/2, 2/66, 10/3
├─ gateway.py    # lock, latência, online/offline, prioridade de comandos
├─ poller.py     # thread, intervalos adaptativos, backoff
├─ store.py      # sqlite3
├─ web.py        # /api/* + SSE + estáticos
└─ static/       # index.html, app.js, table.js, style.css
tests/           # unittest + fixtures/dump.json
```

## 4. Etapas

| # | Entrega | Pronto quando |
|---|---|---|
| 0 | `aes.py` + `miio.py` | Passam nos vetores FIPS-197 e cifram igual ao python-miio; `miIO.info` e `get 2/2` funcionam no robô; testar lote de 10 com buffer de 64 KB |
| 1 | `device.py`, `catalog.py`, `decoders.py` | Testes com o `dump.json`: 10/3 = 188 min, 151,78 m², 12 limpezas; 2/19 = 06:30 seg–sex; 11/2 = 23:00–08:00 |
| 2 | `store.py` | Schema criado e migrado via `user_version`; só grava mudanças |
| 3 | `gateway.py` + `poller.py` | Testes com `FakeDevice`: sem chamadas concorrentes; offline detectado em ≤ 60 s |
| 4 | `web.py` (API do §8 da spec) | Todas as rotas respondem; SSE emite `state` a cada mudança |
| 5 | UI: Painel, Cômodos, Ajustes, Consumíveis, Comandos | Tabelas filtráveis; confirmação antes de sair da base; bloqueio com 2/2 ∈ {7, 11, 12, 14} |
| 6 | Checklist manual no robô | `info` → `locate` → volume → limpar o banheiro → `home` |

**Aceite do MVP:** os critérios do §14 da spec, com `py -m h50console` no lugar do `docker compose up`.

## 5. Resultados da etapa 0 (11/10/2026)

- `aes.py` + `miio.py`: passam nos vetores FIPS-197 e geram pacotes **idênticos byte a byte** ao python-miio (`py -m unittest tests.test_aes`).
- No robô: handshake 60 ms, `miIO.info` 18 ms, `get 2/2` cerca de 25–80 ms.
- **D1/P6 resolvido:** a causa **não** é o buffer de 4 KB. O robô não entrega resposta UDP **maior que cerca de 1.400 bytes** (passou com 1.392 B e falhou com cerca de 1.456 B). Provavelmente é o limite do MTU / fragmentação IP. O lote de 10 funciona; o que falha é a soma do tamanho das respostas.
- **Novo problema P7:** o **10/3 (clean-record) sozinho já não responde.** Depois da limpeza de 11/10 (2/17 = 1791743955) o JSON passou do limite. A importação do histórico pela LAN fica **bloqueada** até isso ser resolvido.
  - Investigar com Wireshark se os fragmentos IP chegam ao PC (e o firewall do Windows descarta) ou se o robô nem envia.
  - Se o robô não envia, o fallback é montar o histórico pelo próprio app (2/17 + 2/6 + 2/7 + 2/5 ao fim de cada limpeza).
- **Implicação para o `device.py`:** montar os lotes pelo **tamanho estimado da resposta** (orçamento de cerca de 1.200 B), não pela quantidade. As props JSON grandes (2/16, 2/19, 2/42, 2/66, 10/3) vão sozinhas.

## 5.1 Resultados da etapa 1 (11/10/2026)

- **`catalog.py`:** carrega a spec oficial de `h50console/spec/ov42gl-2.json` e aplica por cima: props fora da spec, enums em português com os rótulos do app, ordem das opções (2/61), variantes de hardware (2/62), `SETTINGS` agrupados, grupos de polling e `SIZE_HINT`/`OVERSIZED`.
- **`device.py`:** `get` em lotes pelo **tamanho estimado** (orçamento de 1.150 B, aprendido com as respostas), com fallback item a item; erro só se nada responder. `set` valida contra a spec (enum/faixa/tipo). `action` mapeia os parâmetros pelos piids de entrada da spec. Atalhos `run`, `clean_rooms` e `reset_consumable`.
- **`decoders.py`:** 2/16, 23/1, 2/42, 2/19, 11/2 (+ `encode_dnd`), 2/66, 2/18, 2/40, 2/67, 10/3, área e progresso.
- **Testes:** 24 OK (`py -m unittest`). O `FakeClient` imita o limite de cerca de 1,4 KB e o `did` trocado (D2). Fixtures reais em `tests/fixtures/` (fora do git).
- **No robô:** 166 props em **12–13 requisições, 0,6–1,1 s**. Só o 10/3 fica de fora (`oversized`, P7).

## 5.2 Resultados das etapas 2 e 3 (11/10/2026)

- **`store.py`:** SQLite em WAL com migração via `user_version`. Tabelas da spec §7, mais `cleaning_record.source` (`robot` | `derived`), `rooms` (JSON), `room.surface` e `app_setting` (ex.: nome "Rex"). Um registro `robot` nunca é sobrescrito por um `derived`. Retenção de 90 dias para as props rápidas.
- **`gateway.py`:** único dono do socket, com `PriorityLock` (comandos passam na frente do poll) e `StateCache` com diff. Todo comando vai para o `command_log`. O `set` relê a prop. Bloqueia sair da base com status 7/11/12/14. Publica `online`/`offline`/`state`/`command`.
- **`poller.py`:** grupos de `catalog.POLL_GROUPS`, intervalo de 5 s quando ativo e 30 s quando ocioso, backoff de 10→300 s quando offline, e cerca de 1 s após um comando. Efeitos: `prop_change`, falhas, cômodos, consumíveis (diário) e **histórico derivado**.
- **Histórico derivado (P7):** ao fim da base (14 → 2), o 2/5 e o 2/40 são zerados, e **cerca de 5 s depois** o 2/17 vira o **início** da limpeza que terminou. O 2/6 e o 2/7 continuam com os valores dela. O poller memoriza o tipo e os cômodos **durante** a sessão. Validado reproduzindo o `monitor.jsonl`: Corredor 15:48:31, 420 s, 3,52 m², [8]; Quarto 16:01:23, 1.200 s, 13,06 m², [5].
- **Testes:** 37 OK. Teste ao vivo de 40 s: online, 81 mudanças, cômodos com piso e consumíveis gravados.

## 5.3 Resultados das etapas 4 e 5 (11/10/2026)

- **Rodar:** `py -m h50console` → http://127.0.0.1:8050. Configuração via ambiente ou `.env` (ver `.env.example`). `RAW_ENABLED=true` liga o Explorador.
- **`web.py`:** `http.server` com threads. Rotas do §8 da spec, com chaves de prop na URL usando hífen (`/api/settings/2-31`). SSE em `/api/stream` (eventos `state`, `online`, `offline`, `command`, `cleaning`, `fault`, `map`). Erros: 400 validação, 403 fora do catálogo/raw desligado, 409 bloqueado, 503 robô sem resposta. Estáticos protegidos contra path traversal.
- **Rotina personalizada (P3):** por enquanto, executa limpando os cômodos da rotina. Rotina sem cômodos ("Pelos gatos") devolve 409.
- **Mapa editado:** quando o 10/13 (backup do mapa) muda, aparece um aviso na UI. As paredes virtuais e as zonas **não** chegam pela LAN (2/13 e 2/14 continuam vazios).
- **UI** (`static/`, JS puro): Painel (ações + Estado com destaque das mudanças), Cômodos (seleção + rotinas), Ajustes (controles inline, agrupados, com variantes), Consumíveis (alerta < 10 %, zerar), Histórico (filtros + totais), Agenda, Eventos e Explorador. Todas as tabelas têm filtro por coluna e ordenação. Tema claro/escuro. O nome do robô é editável (salvo localmente).
- **Histórico:** um valor desconhecido nunca apaga um conhecido (reiniciar o app não estraga o último registro).
- **Testes:** 46 OK, incluindo HTTP de ponta a ponta e SSE.

## 5.4 Dashboards e mapa (11/10/2026, pós-MVP)

- **Dashboards** (aba própria, `dash.py` + `static/charts.js`, SVG puro): filtro de período (24 h, 7, 30 e 90 dias). **Limpezas:** indicadores, área por dia, ranking por cômodo/rotina/zonas, tipo e mapa de calor dia × hora. **Bateria e status:** indicadores, faixa de status no tempo (6 grupos) e bateria em degraus. Paleta validada com o script da skill dataviz nos dois temas (worst CVD ΔE 9,1 claro / 8,4 escuro). Tooltip, legenda e "Ver dados" (tabela) em cada gráfico. O eixo de tempo começa onde há dados. Captura headless: `msedge --headless=new --screenshot … "http://127.0.0.1:8050/?static#dashboards"` (`?static` desliga o SSE).
- **Histórico imune a reinício:** se o app não acompanhou a sessão, o tipo, os cômodos, a rotina e as **zonas** são reconstruídos pela primeira mudança do 2/5 e do 2/40 após o início, no `prop_change`.
- **`tools/import_monitor.py`:** importa o `monitor.jsonl` para o banco (684 mudanças de 11/10, 15:52–16:34).
- **Nuvem (experimental, `cloud.py`):** login por **QR code**, para contas Google/Apple sem senha Xiaomi. O QR vem pronto da Xiaomi (`longPolling/loginUrl`) e é escaneado no Xiaomi Home; long polling até confirmar. Também tem login por senha via CLI. Guarda só a sessão em `data/cloud-session.json`. Mapa: `find_device` acha o servidor, `get_interim_file_url_pro` (fallback para a versão sem `_pro`) com o `obj_name` do 10/1, e o download vai para `data/map/`. **Decodificação: pendente até ver o primeiro arquivo real.** Aba **Mapa** na UI: gerar QR, status, baixar o mapa e sair.
- **Novos achados:** limpeza **por zonas** (11/10 16:47, só pano): 2/5 = 2, `2/40 = {"zones": [[x1,y1,…,x4,y4], …], "clean_mode": 2}`, no mesmo formato de retângulo das rotinas. Status **12 antes de sair** = base preparando o mop.

## 5.5 Mapa funcionando (11/10/2026)

- **Login por QR ok** (conta Google): userId <UID>, servidor **us**.
- **Download:** `get_interim_file_url_pro` com o `obj_name` do 10/1 devolve `{"version":2,"data":"<base64>"}` (cerca de 4,7 KB).
- **Decifragem** (`mapdecode.py`, só stdlib + `aes.py`): chave = MD5(AES-CBC(model[-16:], model[-16:] + did)), IV `ABCDEF1234123412`, depois zlib → JSON. Algoritmo do projeto devbis/xiaomi-vac (engenharia reversa do plugin do Xiaomi Home), confirmado com o mapa real.
- **Conteúdo:** grade 252×274 a 50 mm/px (pixel = id do cômodo, 1 = parede), base, posição, `room_attrs` (nome, posição do rótulo, ajustes por cômodo), **`fb_walls` (paredes virtuais)**, **`furniture` (posição dos móveis; 1220 = sofá confirmado pela posição)**, `paths` (tipo 1 = limpando, 0 = deslocamento) e `map_3d_info` (contornos).
- **UI:** aba Mapa em canvas (cômodos por cor, paredes, base, robô, paredes virtuais em vermelho, móveis, nomes e trajetória; tooltip com cômodo e coordenadas em m). Atualiza sozinha quando o 10/1 muda durante a limpeza (no máximo 1 download a cada 20 s). Teste de regressão com o blob real (`tests/test_map.py`).

## 5.6 Interface no formato do app Xiaomi Home (11–12/10/2026)

- **Abas:** Início · Dashboards · Histórico · Consumíveis · Configurações · Diagnóstico. O antigo Painel, a aba Mapa, Cômodos, Agenda, Eventos e o Explorador foram absorvidos pelo Início e pelo Diagnóstico.
- **Início:** chips de estado (status; progresso, área e tempo durante a limpeza; base "Secando · faltam X" / "Lavando o mop" / "Esvaziando o pó"; bateria e carga; tanques), mapa (clique no cômodo = seleção da Área), **Estação ›** e **Iniciar limpeza** (vira Pausar/Continuar/Parar; com o robô em limpeza aparece também Voltar à base/Encerrar), **Área / Modos / Atalhos** com o valor atual, **Limpeza personalizada** (▶) e **Limpeza programada**. Sem nuvem, os cômodos aparecem como botões e o QR de login fica no lugar do mapa.
- **Menus que sobem de baixo** (`<dialog>`): **Modos** (Modo, Sucção, Saída de água, Caminho, Tempos; grava só o que mudou ao confirmar; sucção desativada em "Esfregando", água desativada em "Aspirando"), **Atalhos** (2/83: Configurações gerais / baixo ruído / minuciosa), **Estação** (Função: Aspirar pó, Limpar o esfregão ↔ Encerrar lavagem, Secar ↔ Encerrar secagem; Configurações: coleta de pó, limpeza do esfregão, secagem), **Área**, **Limpeza programada** e confirmações. `?static&sheet=modos|atalhos|estacao|area[&tab=config]` abre o menu direto (capturas headless).
- **Textos do app** no catálogo: 2/4, 2/8, 2/9, 2/10, 2/33, 2/74 e 2/83, com a ordem do app (2/4: 1, 3, 4, 2; 2/83: 2, 0, 1).
- **P2 resolvido:** 2/18 `mode` 1 = secando (2/90 = minutos restantes; 2/88 fica 0), 2 = esvaziando o pó, 3 = lavando o mop (0→94 % em cerca de 4,5 min). Status 12 antes de sair = base preparando o mop.
- **Bloqueio de início** (`catalog.start_block_reason`): status 14 só bloqueia se a base estiver lavando ou esvaziando; **secando não bloqueia** (como o app). 7/11/12 continuam bloqueando.
- **IP dinâmico:** em 12/10 o DHCP deu o 192.168.1.50 ao PC e o robô foi para o **192.168.1.50**. O `MiioClient` agora, se o handshake falhar, faz **descoberta miIO pelo DID** (broadcast na sub-rede /24, porque no Windows com placas virtuais o 255.255.255.255 sai pela placa errada), troca de IP e o app grava `robot_ip`/`robot_did` no banco. **Recomendado:** reservar o IP do robô no roteador.
- **Capturas no celular:** o Edge headless no Windows tem largura mínima de cerca de 500 px; para validar 400 px, renderizar a página num iframe (`data/shots/mobile.html`).

## 5.7 Configurações que não atualizavam na tela (12/10/2026)

- **Causa 1:** o grupo `settings` era lido a cada 5 min; uma mudança feita no app oficial demorava até 5 min. **Agora 30 s** (cerca de 45 props, 3 lotes, < 200 ms). Rotinas, agenda, móveis e mapa (JSON maiores) foram para o grupo `edits`, lido a cada 60 s.
- **Causa 2:** depois de um `set` feito pelo nosso app, o robô às vezes devolve o **valor antigo** na releitura imediata; o cache ficava velho. Agora, se o set foi aceito (code 0) e a releitura não confere, vale o valor gravado, e o poller relê os ajustes cerca de 2 s depois do comando para confirmar (teste `test_set_with_stale_reread_keeps_written_value`).
- **Causa 3:** a aba Configurações não se atualizava com o SSE. Agora se atualiza quando chega mudança de um ajuste (se nenhum campo estiver em edição).
- **Desempenho da UI:** o evento `state` aplica as mudanças direto no estado local; só rebusca `/api/state` quando muda status/base ou a cada 15 s (antes era a cada evento, a cada 5 s durante a limpeza).

**Próximo:** adicionar/escolher robôs (registro em `data/robots.json`, banco por robô, descoberta na LAN + token pela nuvem Xiaomi, troca do robô ativo sem reiniciar). Parear um robô novo no Wi-Fi continua sendo pelo app Xiaomi Home.

## 5.8 P7 resolvido: histórico do robô pela nuvem (12/10/2026)

- **Captura (`pktmon`, Wi-Fi):** o PC envia o pedido do 10/3 (128 B, igual ao do 2/2); o robô **não envia nenhum pacote em resposta** (nem fragmentos), mas responde ao handshake 6 s depois (10 ms). Não é firewall nem fragmentação perdida: a resposta não é enviada.
- **Causa:** o 10/3 hoje tem ~2 KB (2,25 KB escapado no pacote); o robô não envia UDP acima de ~1,4 KB (limite medido no primeiro dia: 1.392 B passa, ~1.456 B não; os pacotes dele saem com DF=1). **Sem solução pela LAN.**
- **Nuvem:** `/miotspec/prop/get` (siid 10, piid 3) devolve o valor completo. A lista vem **com cada registro duplicado** e é **limitada a 40 itens (~20 limpezas)**; o `total_count` (22) conta uma que já saiu da lista.
- **Validação:** das 7 limpezas que o app reconstruiu sozinho, as 7 batem com a nuvem (duração, área e tipo). A nuvem acrescentou as limpezas de 10/10 e o tipo da agendada das 6h30 (tipo 7).
- **Implementação:** `history.py` (importa sem duplicar; o registro do robô passa a valer, mas não apaga `custom:<rotina>`/`zones:<n>`/cômodos do app), `CloudService.clean_record`, `POST /api/cloud/history`, thread que sincroniza na partida, após cada limpeza (60 s depois) e a cada hora, botão "Sincronizar com a nuvem" no Histórico (fonte "robô (nuvem)").
- **Ferramentas:** `tools/p7-capture.ps1` (administrador, só liga/desliga a captura) + `tools/p7_read.py` (terminal normal); `tools/pcap_frag.py` lê quadros 802.11 (o `pktmon` no Wi-Fi marca o link como Ethernet, mas grava o quadro Wi-Fi). No PowerShell elevado, o `py` pode escolher o Python da Store (bloqueado) ou outra conta do Windows.

## 6. Monitorias de 11/10/2026 (`py -m h50console.probe …`)

Artefatos em `data/` (contêm uid/did: **não publicar**):
- `dump-full.json`: as 157 props da spec, item a item, com o tamanho de cada uma.
- `scan.json`: varredura do que existe fora da spec.
- `calls.json`: ações de consulta.
- `monitor.jsonl`: mudanças ao longo do tempo.
- `spec-ov42gl-2.json`: spec oficial (a v2 é a mais recente no miot-spec.org).

| Achado | Detalhe | Impacto |
|---|---|---|
| Spec legível | 156 de 157 props respondem; a maior tem 329 B (2/42). Só o **10/3** dá timeout (P7) | Catálogo do app = spec oficial + extras abaixo |
| **Props fora da spec** | **23/1** = cômodos com `surface` (tipo de piso). 23/2 e 23/3 = `[]`. **siid 21** (1–8: bool/int/str vazios). 2/103–2/106 (2/104 = 1, 2/105 = 1) | 23/1 dá o tipo de piso por cômodo. O siid 21 fica para observar com o `watch` |
| Ações `get-*` (2/10, 2/11, 2/30, 2/47, 20/1, 20/2, 20/5) | Devolvem `out: []` e não mudam nenhuma prop | O resultado vai para a nuvem. Não servem para buscar a config por cômodo nem o histórico |
| 15/2 get-download-status | Voz `pt`, status 4, 100 % | Tela de voz (só leitura) |
| **2/40** durante a limpeza | `{"rooms":[8],"clean_mode":3,…}` | Mostra **quais cômodos** estão em limpeza agora |
| 2/7 tempo de limpeza | Muda de 60 em 60 s; 2/6 e 2/89 mudam a cada cerca de 5 s | Interpolar o tempo na UI |
| 10/1 `index` | Muda a cada cerca de 60 s durante a limpeza (upload do mapa para a nuvem) | Sinal de "mapa atualizado" |
| 10/4 posição, 10/7, 10/9 | Vazios pela LAN | **Mapa, posição e trajetória: só pela nuvem** (confirmado) |
| 2/42 | Nova rotina "Pelos gatos" (`room_ids: []`, mop 1) | O `watch` pega edições feitas no app |
| Texto em Latin-1 | O transporte aceita UTF-8 e Latin-1 | `miio.decrypt` corrigido |

**P7: como investigar.** Rodar `tools\p7-capture.ps1` num PowerShell como administrador (usa o `pktmon`, nativo do Windows) e ver se os fragmentos IP chegam ao PC.

### 6.1 Mapeamento "ajuste do app → propriedade" (observado com `watch --all`, 11/10/2026)

O app reflete na LAN em cerca de 10 s. **Rótulos do app ≠ nomes da spec:** a réplica usa os rótulos do app.

| Ajuste no app | Prop | Valores | Observação |
|---|---|---|---|
| Não perturbe (liga/desliga) | 11/1 | bool | 11/3 = DND ativo agora |
| Não perturbe: horário | 11/2 | `[h_ini, m_ini, h_fim, m_fim]` em 4 bytes | 23:00–08:00 = `0x17000800`; 23:00–06:00 = `0x17000600` |
| **Foco em cantos e bordas** (frequência) | **2/80** mop-outer-swing-frequency | 1 = a cada 7 limpezas, 2 = toda limpeza | **Não** é a 2/68. O 2/79 é provavelmente o liga/desliga (a confirmar) |
| Volume da voz | 4/2 | 0–100 | "Ouvir" = ação 2/27 `try-listen` (não muda props) |
| Nome do aparelho | — | — | Só na nuvem. A réplica guarda o próprio nome no banco local |
| Frequência de retorno para lavar o mop | **2/61** (`-no-tank`) | 0 = 5, 1 = 10, **2 = 8**, 3 = 15, 4 = 20, 5 = 25 m² | Vale quando **2/62 = false** (sem troca automática de água). Senão, 2/29 + 2/81. A UI ordena por área |
| Modo de lavagem do mop | 2/30 | 0 = minuciosa, 1 = diária, 2 = economia | |
| Duração da secagem | 2/31 | 1 = 2 h, 2 = 3 h, 3 = 4 h | |
| Reconhecimento de tapete | **2/77** carpet-discriminate | bool | |

### 6.2 Estados observados

| Sequência | Significado |
|---|---|
| 2/2: 4 → 6 → **14** (2/18 `mode` **2**, cerca de 17 s, saco de pó −2 %) → 2 | Volta para a base e **esvazia o pó**. **P2:** `mode 2` = esvaziamento |
| 2/26 `true` no início da limpeza, `false` cerca de 1 min depois | Localização no mapa |
| 2/17 | **Início** da última limpeza (não o fim) |
| 2/40 `rooms` | Cômodos da limpeza em andamento. Some quando ela termina |

| **2/40 durante uma rotina** (16:37, "Pelos gatos") | `user_define` com id, nome e `user_data` = `[[mode, mop, fan, water, clean_count, more, ai, clean_path, mode_data], [2, 1, 2, 2, 1, 0, 0, 3, [[retângulo em mm], …]]]`. O 2/5 fica 7 e o **2/43 fica 0** |
| **2/102 móveis** (sofá, cama e liteira adicionados) | `{"id", "type": 1220/1400/1740, "rid": 3 ou 248}`. Sem posição. O 248 parece significar "fora dos cômodos" |
| **Móveis: tipos** | **1740 = liteira** (confirmado: sumiu do 2/102 ao ser removida). 1220 = sofá (fora da borda, rid 248) e 1400 = cama (dentro da Sala, rid 3), inferidos pela posição | `catalog.FURNITURE_TYPES` |
| **Limpeza interrompida** (rotina parada no app após cerca de 3 min) | 2/5 e 2/40 zeram na hora da parada; ao fim da base, o 2/17 vira o início (16:37:43). **O robô registra limpezas interrompidas**; a pausa de 5 s às 15:59 não foi registrada | O histórico guarda o nome da rotina (`raw_label = custom:<nome>`) |
| Paredes virtuais | **Não** aparecem no 2/13 nem no 2/14; só muda o 10/13 (backup do mapa) |

**P3, pista nova:** a "Pelos gatos" é por **zonas**, não por cômodos. As coordenadas chegam no 2/40 quando ela roda. A próxima tentativa é a ação 2/37 `start-zone-sweep` com esses retângulos (o formato do 2/12 ainda é desconhecido). **Move o robô: testar só com autorização.**

**Ainda a observar:** 2/18 durante a lavagem e a secagem do mop (precisa de uma limpeza com pano), 2/79, siid 21.

## 7. Réplica do app Xiaomi Home: o que dá pela LAN

| Tela do app | LAN | Fonte |
|---|---|---|
| Estado, bateria, progresso, área, tempo, falhas | ✅ | 2/2, 2/3, 2/66, 2/89, 2/6, 2/7, 3/1 |
| Iniciar, pausar, base, esvaziar, lavar, secar, localizar | ✅ | ações 2/x, 3/1, 6/1 |
| Limpar cômodos | ✅ | ação 2/16 |
| Cômodos em limpeza agora | ✅ | 2/40 |
| Rotinas personalizadas | Leitura ✅, execução a validar (P3) | 2/42, ação 2/42(43) |
| Agendamentos | Leitura ✅, edição a validar | 2/19, ações 2/23–25 |
| Ajustes (sucção, água, passadas, rota, tapete, base, DND, volume, trava, IA) | ✅ | cerca de 60 props RW do siid 2 + 4, 5, 11, 18 |
| Consumíveis e reset | ✅ | 9, 12, 13, 14, 18, 19 |
| Tipo de piso por cômodo | ✅ (fora da spec) | 23/1 |
| Voz | Leitura ✅ | 15/1–4 |
| Histórico de limpezas | ⚠️ 10/3 bloqueado (P7). Fallback: montar pelo app | 2/17 + 2/6 + 2/7 + 2/5 ao fim de cada limpeza |
| Estatística total | ⚠️ 2/85–87 = 0 | Calcular no app |
| Config por cômodo (sucção/água por cômodo) | ❌ `get-room-configs` não devolve nada | Escrita via 2/13 a investigar |
| **Mapa, posição, trajetória, zonas e paredes virtuais desenhadas** | ❌ só nuvem | Opcional: módulo de nuvem (fora do "100 % local") |

## 8. Decisões

- A importação do histórico (10/3) entra na etapa 1, porque o decoder já foi validado. A tela de Histórico é opcional na etapa 5.
- Agenda só de leitura. Explorador `raw` só com `RAW_ENABLED=true`.
- Fallback, se o AES puro der problema: `cryptography`, a única dependência aceitável.
- Servidor só em `127.0.0.1`; token mascarado nos logs.
