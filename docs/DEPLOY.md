# Colocar no ar

O H50 Console é um servidor web pequeno (Python, sem dependências). Esta página mostra como deixá-lo rodando sempre,
como acessar **de fora de casa** com segurança e como instalar no celular.

## 1. Onde rodar e como acessar de fora

| Opção | Como | Prós e contras |
|---|---|---|
| **A. Máquina ligada em casa + VPN** (recomendado) | App num mini-PC, Raspberry Pi ou NAS; acesso por **Tailscale** (ou WireGuard) | Nada exposto à internet; fala com o robô pela rede local (rápido, com todos os recursos). Exige uma máquina ligada 24 h |
| **B. Máquina em casa + túnel HTTPS** | Cloudflare Tunnel ou Caddy/nginx com HTTPS na frente do app | Acesso por URL, sem instalar VPN no celular. Exige configurar o túnel e **manter a senha forte** |
| **C. Servidor fora de casa (VPS, Docker remoto)** | O app fala com o robô **pela nuvem Xiaomi** (transporte `cloud`), como o app oficial faz | Não precisa de máquina em casa. Depende da conta Xiaomi; mais lento; **sem** as propriedades fora da spec (só existem pela rede local) |
| **D. Híbrido** | Transporte `auto`: rede local quando está em casa, nuvem quando não | Padrão: o app troca sozinho e volta para a rede local quando ela responde |

O transporte de cada robô se escolhe na aba **Robôs → Editar** (Automático, Só rede local, Só nuvem).

## 2. Antes de expor: checklist

- [ ] Crie a senha no primeiro acesso (o código aparece no console/`docker logs`/`journalctl`) ou defina `H50_PASSWORD`.
- [ ] **Nunca** abra a porta 8050 do roteador para a internet. Use VPN ou um túnel com HTTPS.
- [ ] Atrás de HTTPS: `H50_COOKIE_SECURE=true`. Atrás de proxy/túnel confiável: `H50_TRUST_PROXY=true` (senão o limite de tentativas
  de login enxerga o IP do proxy). Com `H50_TRUST_PROXY=true` o app **confia** em `X-Forwarded-For`: só ligue se o app não for
  alcançável sem passar pelo proxy.
- [ ] Reserve o IP do robô no roteador (o app o reencontra pelo DID se mudar, mas é mais simples).
- [ ] Faça um backup (aba **Manutenção**) e guarde a senha dele. O backup contém tokens e a sessão da conta Xiaomi.
- [ ] O app recusa subir em `0.0.0.0` com `H50_AUTH=off`; mantenha assim.

## 3. Windows (o seu PC)

```powershell
cd C:\caminho\do\h50console
powershell -ExecutionPolicy Bypass -File deploy\windows\install-task.ps1          # instala e inicia
powershell -ExecutionPolicy Bypass -File deploy\windows\install-task.ps1 -Remove  # remove
```
Cria uma tarefa agendada que sobe o app ao entrar no Windows, sem janela. Os dados ficam em `data\`. Para ver o código de
primeiro acesso, rode uma vez `py -m h50console` no terminal. O PC precisa estar ligado e acordado.

## 4. Linux / Raspberry Pi (systemd)

```bash
sudo useradd --system --home /var/lib/h50console --shell /usr/sbin/nologin h50
sudo git clone <repositório> /opt/h50console
sudo cp /opt/h50console/deploy/h50console.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now h50console
journalctl -u h50console -f            # mostra o código de primeiro acesso
```
Variáveis opcionais em `/etc/h50console.env` (`H50_PASSWORD=…`, `H50_TRUST_PROXY=true`, …). Dados em `/var/lib/h50console`.

## 5. Docker

```bash
cp .env.example .env                    # opcional: H50_PASSWORD
docker compose -f deploy/docker-compose.yml up -d --build
docker logs h50console                  # código de primeiro acesso
```
No **Linux** o compose usa `network_mode: host` (necessário para achar o robô por broadcast UDP). No **Docker Desktop**
(Windows/macOS) o modo host não alcança a sua rede: use o bloco `ports:` e informe o IP do robô (ou use o transporte pela nuvem).
> Os arquivos de `deploy/` para Docker e systemd ainda **não foram testados em máquina real**; trate o primeiro uso como teste.

## 6. Acesso de fora

### Tailscale (recomendado)
1. Instale o Tailscale na máquina do app e no celular (mesma conta).
2. Acesse `http://<nome-da-máquina>:8050` pelo celular, de qualquer rede.
3. Para HTTPS (necessário para instalar o app no celular) use, em versões recentes do Tailscale, `tailscale serve --bg 8050` e acesse
   o endereço `https://<máquina>.<rede>.ts.net` que ele mostra. Com HTTPS, defina `H50_COOKIE_SECURE=true`.

### Cloudflare Tunnel
Crie um túnel apontando para `http://127.0.0.1:8050`, defina `H50_TRUST_PROXY=true` e `H50_COOKIE_SECURE=true`. Proteja também com
o Cloudflare Access se puder (segunda camada). O painel já exige senha, mas ela é a única barreira que você controla.

### Caddy (HTTPS no seu domínio)
Use `deploy/Caddyfile.example`. O `flush_interval -1` impede que o proxy segure o fluxo de eventos (SSE).

## 7. Instalar no celular (PWA)

Abra o painel no navegador do celular e use "Adicionar à tela inicial". Para o navegador oferecer a instalação o endereço precisa
ser **HTTPS** (ou `localhost`): por isso o item 3 do Tailscale ou um túnel. O app abre mesmo sem rede mostrando a última tela;
os dados do robô vêm sempre da rede.

## 8. Rodar fora de casa pela nuvem Xiaomi (opção C)

1. Num servidor qualquer: suba o app (Docker/systemd) e crie a senha.
2. Em **Robôs**, conecte a conta Xiaomi por QR e **adicione o robô pela conta** (o token vem sozinho).
3. Em **Editar**, escolha o transporte **Só nuvem**. O app passa a ler e comandar pela mesma API do app oficial.

Limites medidos: a nuvem responde até 40 propriedades por pedido em tempo real e leva ~1–2,5 s por consulta; o poller relaxa
os intervalos (×3). Propriedades que não estão na spec oficial (aba Laboratório) só existem pela rede local.

## 9. Backup agendado e atualização

```bash
# backup criptografado sem abrir o painel (cron / agendador de tarefas)
H50_BACKUP_PASSPHRASE='uma-senha-longa' python -m h50console backup /caminho/h50-$(date +%F).h50bak
python -m h50console restore arquivo.h50bak       # restaurar (com o app parado)
```
Atualizar: `git pull` e reiniciar (`systemctl restart h50console`, `docker compose up -d --build`, ou reiniciar a tarefa). O banco
se atualiza sozinho para o esquema novo e nunca perde dados.

## 10. Problemas comuns

| Sintoma | Causa e solução |
|---|---|
| "Recusado: H50_AUTH=off só é permitido em localhost" | Proteção: ligue a senha ou use `H50_HOST=127.0.0.1` |
| Não sei o código de primeiro acesso | Ele é gerado a cada partida enquanto não há senha: veja o console/log |
| Esqueci a senha | Com o app **parado**: `python -m h50console reset-password`; no próximo início aparece um código novo |
| Em aba anônima/outro navegador pede a senha | É o esperado: a sessão é um cookie do navegador. A tela "Criar senha" só aparece se **não** houver senha |
| O robô aparece "sem resposta" | O IP mudou? Em **Robôs → Achar pelo DID**. Fora da rede, use o transporte Automático/Nuvem |
| Eventos em tempo real não atualizam atrás do proxy | O proxy está segurando o SSE: desative buffering (`flush_interval -1` no Caddy; `proxy_buffering off` no nginx) |
| "muitas tentativas" no login | Limite de proteção (espera crescente até 15 min por IP) |
