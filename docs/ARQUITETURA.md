# Arquitetura do sistema completo

Meta: um aplicativo que cobre o ciclo inteiro de uso de um ou mais robôs Xiaomi — instalar, entrar, conectar à
nuvem, achar/adicionar robôs (token automático, independente de IP), controlar de dentro e **de fora de casa**,
manter histórico, fazer manutenção e backup, e explorar **funcionalidades que não estão nos manuais**.
Continua sem dependências externas (biblioteca padrão do Python).

## 1. Requisitos (do uso real)

| # | Requisito | Onde fica |
|---|---|---|
| R1 | Login inicial (primeiro acesso cria a senha) e sessão segura | `auth.py`, tela `/login` e `/setup` |
| R2 | Conexão com a nuvem Xiaomi (QR code; serve a contas Google/Apple) e re-login quando expirar | `cloud.py`, aba Robôs |
| R3 | Token automático (vem da lista de dispositivos da conta) | `cloud.devices()` |
| R4 | Achar o robô **independente do IP** (DID por broadcast miIO; IP da nuvem como pista) | `miio.discover`, `fleet` |
| R5 | Vários robôs; adicionar, editar (nome, IP, token, transporte), remover, testar | `fleet.py`, aba Robôs |
| R6 | Controle de dentro **e de fora** de casa | transporte `auto` (LAN → nuvem), túnel/VPN, auth |
| R7 | Manter histórico (limpezas, mudanças, consumíveis), com retenção configurável e exportação | `store.py`, `history.py`, aba Manutenção |
| R8 | Manutenção: espaço, otimizar banco, retenção, logs, pacote de diagnóstico | aba Manutenção |
| R9 | Backup e restauração **criptografados** (contêm tokens) | `backup.py` |
| R10 | Funcionalidades fora dos manuais: explorar propriedades, observar mudanças, varrer piids, executar ações | aba Laboratório |
| R11 | Notificações (limpeza concluída, falha, tanque, consumível, robô offline) | `notify.py` (ntfy/Telegram/webhook) |
| R12 | Instalar como app no celular (PWA) e rodar como serviço (Docker, systemd, Windows) | `static/manifest`, `deploy/` |

## 2. Camadas

```
navegador/PWA ── HTTPS (proxy/túnel) ─▶ web.py ─▶ auth.py (sessão, CSRF, limite de tentativas)
                                           │
                                           ▼
                         Fleet (robots.json) ── Robot[n] ──────────────────────────────┐
                                                  │ store (SQLite por robô)             │
                                                  │ gateway ─▶ transporte               │
                                                  │ poller / history / notify           │
                                                  └─────────────────────────────────────┘
transporte = LanClient (UDP 54321)  |  CloudClient (api.io.mi.com, RC4)  |  AutoClient (LAN, senão nuvem)
nuvem compartilhada: 1 sessão Xiaomi por instalação (CloudService): QR, lista de dispositivos, mapa, histórico
```

- **Um app, vários robôs.** Cada robô tem contexto próprio (cliente, gateway, poller, banco, barramento de eventos,
  pasta de mapa). A nuvem (conta) é compartilhada. A API é `/api/r/<id>/…`; a UI escolhe o robô ativo.
- **Transporte plugável.** O `Gateway`/`H50` só chamam `send(método, parâmetros)`; o resultado tem o mesmo formato nos
  três transportes. Na nuvem os limites do UDP (≈1,4 KB) não existem: o histórico `10/3` é lido normalmente.
  Na nuvem o poller relaxa os intervalos (×3) para respeitar a API.
- **Segredos.** `robots.json` (tokens) e a sessão da nuvem ficam em `data/` (arquivos 0600 quando o SO permite), fora do git.
  Backups são criptografados (PBKDF2 → AES-128-CBC + HMAC-SHA256, encrypt-then-MAC).

## 3. Layout de dados (`H50_DATA_DIR`, padrão `data/`)

```
app.json              senha (PBKDF2), preferências, notificações
secret.key            chave de assinatura das sessões
robots.json           [{id, name, model, did, ip, token, transport}]
cloud-session.json    sessão Xiaomi (sem senha)
robots/<id>/h50.db    banco do robô (mudanças, limpezas, comandos, falhas, cômodos)
robots/<id>/map/      último mapa e backups
backups/              arquivos .h50bak gerados
```
Instalações antigas (`data/h50.db`) são migradas na primeira partida (o robô vira o `main`, o banco é reaproveitado).

## 4. Acesso de fora de casa

| Opção | Como | Quando usar |
|---|---|---|
| **A. Servidor em casa + VPN** (recomendado) | App num mini-PC/Raspberry/NAS ligado 24 h; acesso por Tailscale (ou WireGuard) | máxima privacidade; nada exposto à internet |
| **B. Servidor em casa + túnel HTTPS** | Cloudflare Tunnel ou proxy reverso (Caddy) com HTTPS; senha do app obrigatória | acesso por URL sem instalar VPN no celular |
| **C. Servidor em qualquer lugar + transporte nuvem** | App numa VPS/Docker remoto; fala com o robô **pela nuvem Xiaomi** (como o app oficial) | quando não há máquina sempre ligada em casa; depende da conta Xiaomi |
| **D. Híbrido** | `transporte: auto` — LAN quando está em casa, nuvem quando não | padrão sugerido |

Regras de segurança: nunca expor a porta sem senha e HTTPS; `H50_HOST` fora de loopback **exige** senha (o app recusa
subir sem ela); cookie `HttpOnly`+`SameSite=Strict` (+`Secure` atrás de HTTPS); POST/PUT/DELETE exigem o cabeçalho
`X-H50`; limite de tentativas de login por IP; `H50_TRUST_PROXY` só quando há proxy confiável.

## 5. Funcionalidades fora dos manuais (Laboratório)

Já descobertas e documentadas em `docs/DESCOBERTAS.md`. A aba oferece as ferramentas para continuar descobrindo:

1. **Propriedades**: todas as conhecidas (spec + extras) com valor ao vivo, tipo, acesso, opções; edita as graváveis.
2. **Mudanças**: fluxo ao vivo de `prop_change` com **anotações** ("mudei X no app às 16:03") para ligar ação → propriedade.
3. **Varredura**: lê faixas de piids fora da spec (somente leitura) e marca o que é novo.
4. **Ações**: executa siid/aiid com parâmetros; sinaliza as que movem o robô.
5. **Nuvem**: lê objetos extras do mapa (trajetória, tapetes), backups de mapa e propriedades que só a nuvem tem.

## 6. Publicação

- Histórico do git **não** pode conter segredos: `tools/check_secrets.py` (hook + CI) confere token, uid, did, IP, sessão.
- Antes de tornar público: escolher a licença; publicar a partir de histórico limpo (`git checkout --orphan`) e conferir o
  e-mail dos commits (use o `noreply` do GitHub); fixtures públicas **sintéticas** (sem planta da casa).
- Distribuição: `pip install`, imagem Docker (GHCR) e `deploy/` (systemd, tarefa agendada do Windows).

## 7. Ordem de implementação

1. Transportes (LAN, nuvem, auto) · 2. Frota e dados por robô · 3. Autenticação e primeiro acesso ·
4. Nuvem + robôs (adicionar com token automático, editar) · 5. Manutenção e backup · 6. Laboratório ·
7. Notificações · 8. Deploy e PWA · 9. Zonas e ajustes por cômodo (com teste supervisionado).
