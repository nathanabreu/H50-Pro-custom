# H50 Console

Painel web **local** para controlar e monitorar aspiradores robô Xiaomi/Mijia da família `ov` (testado no
**Xiaomi Robot Vacuum H50 Pro**, `xiaomi.vacuum.ov42gl`). Replica as telas do app Xiaomi Home e acrescenta
histórico, dashboards, mapa, vários robôs, notificações, backup e um laboratório para explorar o que os manuais não dizem.

- **Sem dependências**: só a biblioteca padrão do Python (3.11+). Nada de `pip install`.
- **Local primeiro**: fala com o robô pela rede local (miIO/MIoT em UDP 54321). A **conta Xiaomi é opcional** e dá o mapa,
  o histórico completo, o token automático e o controle de fora de casa.
- **Instalável no celular** (PWA) e pronto para rodar como serviço (Windows, Linux, Docker).

> Projeto **não oficial** e sem vínculo com a Xiaomi. Use apenas com aparelhos seus. Veja o [Aviso](#aviso).

## Início rápido

```bash
git clone <este-repositorio> && cd h50console
python -m h50console            # http://127.0.0.1:8050
```

1. No console aparece um **código de primeiro acesso**. Abra o painel e crie a senha com ele.
2. Em **Robôs**, conecte a conta Xiaomi (QR code no app Xiaomi Home; serve a contas Google) e toque em **Adicionar**:
   o token e o IP vêm da conta. Sem conta, use o cadastro manual (IP + token).
3. Pronto: **Início** espelha a tela do app (mapa, Estação, Modos, Atalhos, rotinas, agenda).

## O que tem

| Aba | O que faz |
|---|---|
| **Início** | Estado, mapa (toque no cômodo para escolher a área), iniciar/pausar, Estação (pó, lavar e secar o mop), Modos, Atalhos, rotinas, agenda |
| **Robôs** | Conta Xiaomi por QR, **adicionar** (token automático, achar pelo DID, manual), editar, testar, remover; transporte rede local / nuvem / automático |
| **Dashboards** | Área limpa por dia, por cômodo, mapa de calor dia × hora, **cobertura no mapa**, status ao longo do tempo, bateria |
| **Histórico** | Limpezas (o robô só guarda ~20; o app guarda todas), filtros, totais, CSV, **caminho percorrido** (das limpezas feitas com o app aberto) |
| **Consumíveis** | Vida útil, alerta abaixo de 10 %, **previsão de troca**, zerar |
| **Configurações** | Todos os ajustes do robô com os textos do app; **notificações** (ntfy, Telegram, webhook); senha, sessões e **perfil somente leitura** |
| **Diagnóstico** | Estado bruto, falhas, comandos enviados, cômodos e móveis |
| **Manutenção** | Espaço e retenção, otimizar bancos, **acessos ao painel**, **backup criptografado** e restauração, logs, pacote de diagnóstico |
| **Laboratório** | Propriedades ao vivo, **mudanças com anotações**, varredura de piids, ações por risco, objetos da nuvem |

## Acesso de fora de casa

Três jeitos, combináveis (detalhes em [`docs/DEPLOY.md`](docs/DEPLOY.md)): app numa máquina ligada em casa + **Tailscale/VPN**;
túnel **HTTPS**; ou o app rodando em qualquer servidor falando com o robô **pela nuvem Xiaomi**. No transporte `auto` (padrão)
ele usa a rede local e cai para a nuvem sozinho.

## Configuração (tudo opcional)

| Variável | Padrão | Função |
|---|---|---|
| `H50_HOST` / `H50_PORT` | `127.0.0.1` / `8050` | onde o painel escuta (fora de localhost a senha é obrigatória) |
| `H50_DATA_DIR` | `data` | robôs (tokens), bancos, sessão da nuvem, configurações |
| `H50_PASSWORD` | — | senha fixa (Docker); sem ela, a senha é criada no primeiro acesso |
| `H50_TRUST_PROXY` / `H50_COOKIE_SECURE` | `false` | atrás de proxy/túnel confiável / atrás de HTTPS |
| `H50_VIEWER_PASSWORD` | vazio | senha do perfil somente leitura (só consulta; nada de comandos, ajustes, cadastro ou backup). Também pode ser definida em Configurações |
| `H50_METRICS_TOKEN` | vazio | token do coletor Prometheus em `GET /metrics` (cabeçalho `Authorization: Bearer`). Sem ele, `/metrics` só abre com sessão |
| `H50_ALLOWED_HOSTS` | vazio | nomes extras aceitos no Host. Em localhost sem proxy qualquer outro nome é recusado (contra DNS rebinding) |
| `RAW_ENABLED` | `false` | libera escrever propriedades e executar ações no Laboratório |
| `H50_BACKUP_PASSPHRASE` | — | senha do backup para `python -m h50console backup` em agendadores |

`H50_IP`, `H50_TOKEN` e `H50_NAME` só servem para migrar uma instalação de um robô só na primeira vez.

## Arquitetura

```
 navegador/PWA ── HTTP/SSE ─▶ web.py ─▶ auth.py (senha, sessão, CSRF) ─▶ hub.py ─┬─ conta: robôs, nuvem, backup, notificações
                                                                                 └─ /api/r/<id>/…  um contexto por robô:
   robô: store (SQLite) · gateway (1 acesso por vez) · poller · history · notify
   transporte: LAN (UDP) | nuvem Xiaomi | automático (LAN, senão nuvem)
```
Mais em [`docs/ARQUITETURA.md`](docs/ARQUITETURA.md). Achados do protocolo e do aparelho em
[`docs/DESCOBERTAS.md`](docs/DESCOBERTAS.md); fila de trabalho em [`docs/BACKLOG.md`](docs/BACKLOG.md).

## Segurança

- Senha com PBKDF2, sessão por cookie assinado (`HttpOnly`, `SameSite=Strict`), limite de tentativas, proteção CSRF e CSP.
- Tokens e a sessão da nuvem ficam só em `data/` (fora do git); a API nunca os devolve. Backups são **sempre criptografados**.
- **Não abra a porta na internet** sem VPN ou HTTPS. Checklist em [`docs/DEPLOY.md`](docs/DEPLOY.md).
- `tools/check_secrets.py` (hook de pre-commit e CI) impede commitar token, `uid`, `did`, IP ou sessão.

## Desenvolvimento

```bash
python -m unittest                  # testes (os que dependem de dados reais são pulados se faltarem)
python tools/check_secrets.py       # antes de publicar
python -m h50console backup|restore|reset-password|version
python tools/install_hook.py        # hook de pre-commit contra vazamento de segredos (1 vez por clone)
python tools/sync_to.py "<outro-repositório>"   # copia só os arquivos versionados para outro repo, sem commitar
```

## Aviso

Software independente, fornecido como está, sem garantias. Ele envia comandos reais ao robô (inclusive para movimentá-lo)
e algumas ferramentas do Laboratório podem alterar a configuração salva nele: leia os avisos antes de usar. O login na
nuvem usa a **sua** conta e pode contrariar os termos do serviço; é opcional e fica por sua conta e risco. Xiaomi, Mijia e
Xiaomi Home são marcas de seus titulares. A decifragem do mapa usa um método publicado pelo projeto
[devbis/xiaomi-vac](https://github.com/devbis/xiaomi-vac).

## Licença

[MIT](LICENSE).
