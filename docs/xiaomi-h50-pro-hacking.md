# Xiaomi Robot Vacuum H50 Pro: hacking e customização

> Base de conhecimento montada em 11/10/2026 a partir da análise dos repositórios
> [python-miio](https://github.com/rytilahti/python-miio) e [dustcloud](https://github.com/dgiese/dustcloud)
> e de pesquisa na web. Fontes no fim. Onde algo é **inferência** (e não fato documentado), está marcado.

---

## 0. Resumo

| Pergunta | Resposta curta |
|---|---|
| Qual é o modelo técnico? | `xiaomi.vacuum.ov42gl`, a versão global do **Mijia 扫拖机器人 5C (OV42CN)** chinês |
| Dá para rootear / instalar Valetudo? | **Hoje, não.** Não está na lista do Valetudo nem no Dustbuilder. Os irmãos S40 e S40 Pro também não tinham root público até abr/2026 |
| O que dá para fazer sem root? | **Controle local via MIoT** (UDP 54321) com o token do aparelho: python-miio, o script `h50pro.py`, Home Assistant e automações |
| Para que serve o dustcloud? | É **histórico** (Roborock Gen1/Gen2, 2017–2019). Serve para entender o protocolo de nuvem e a técnica de emulação e bloqueio. Não rooteia o H50 Pro |
| Para que serve o python-miio? | É a **referência ativa do protocolo** miIO/MIoT. A integração `genericmiot` fala com qualquer aparelho MIoT a partir da spec |

**Recomendação:** use o controle local com token + Home Assistant e isole o robô numa VLAN de IoT.
Não abra o robô para tentar root (ver §4.3), a menos que aceite perder a garantia e correr risco de brick.

---

## 1. Identificação do aparelho

| Item | Valor |
|---|---|
| Nome comercial | Xiaomi Robot Vacuum H50 Pro |
| Model ID (MIoT) | `xiaomi.vacuum.ov42gl` |
| URN da spec | `urn:miot-spec-v2:device:vacuum:0000A006:xiaomi-ov42gl:2` |
| SKUs vistos | BHR089NEU, BHR089MGB |
| Gêmeo chinês | Mijia 扫拖机器人 5C, `OV42CN` (base `OV42-JZCN`) |
| Irmão sem "Pro" | H50, `xiaomi.vacuum.ov43gb` |
| Conectividade | Wi-Fi 2.4 GHz 802.11b/g/n (sem 5 GHz) + Bluetooth 5.0 (manual do 5C) |
| Navegação | LDS (laser 360°) + luz estruturada 129° para obstáculos |
| Sucção | até 15.000 Pa |
| Mop | 2 discos rotativos (até 180 rpm), braço extensível, sobe 10 mm em tapete |
| Base | autoesvaziamento (saco "até 75 dias"), lavagem do mop, secagem com ar quente, tanque de 4 L |
| Bateria | 5200 mAh nominal (14,4 V) |
| App | Xiaomi Home; Alexa e Google Assistant |
| Datas | miot-spec exibe "2026-02" na ficha; anúncio global noticiado em mai/2026 |
| Fabricante (ODM) | **Não divulgado.** No S40 (`ov81gl`), um pesquisador achou o namespace de CDN `shunzao-ov81gl`, o que aponta para a **Shunzao**. Para o H50 Pro isso é **inferência**: a spec segue o mesmo padrão da família |

### Família "ov" (mesma geração de software, provavelmente mesma plataforma)

| Model ID | Produto |
|---|---|
| `xiaomi.vacuum.ov21gl` / `ov21cn` | Robot Vacuum 5 Pro / Mijia 5 Pro |
| `xiaomi.vacuum.ov31gl` | Robot Vacuum 5 |
| **`xiaomi.vacuum.ov42gl`** | **H50 Pro** |
| `xiaomi.vacuum.ov43gb` | H50 |
| `xiaomi.vacuum.ov51gl` | H40 (firmware visto: 4.5.6_0105) |
| `xiaomi.vacuum.ov71gl` | S40 Pro (firmware visto: 4.5.8_0045) |
| `xiaomi.vacuum.ov81gl` | S40 (firmware visto: 4.5.6_0079, OTA a partir de 0047) |

O que pesquisas na família descobriram (S40, H40, S40 Pro), e que **provavelmente vale para o H50 Pro**:
- A única porta aberta é **UDP 54321** (miIO). Não há TCP, mDNS/SSDP nem SoftAP depois do pareamento.
- `miIO.info` responde com `hw_ver: "Linux"` e expõe estatísticas de memória (`VmRSS`, `MemFree`), então o SO é Linux com o daemon `miio_client` 4.5.x.
- Os **métodos miIO legados** (`status`, `sound_info`, `install_sound`) dão `-9999 "user ack timeout"`. **Só os métodos MIoT funcionam** (`get_properties` / `set_properties` / `action`).
- Há propriedades fora da spec publicada, por exemplo o **siid 21**, não documentado.
- O robô **não confia em CA instalada pelo usuário** (TLS estrito ou pinning), então não dá para injetar URL ou falsificar o CDN sem root.

> **Confirmado no aparelho real (11/10/2026):**
> - `fw_ver 4.5.8_0087`, `miio_client_ver 4.5.8.1`, `miio_ver 0.1.0`, `hw_ver Linux`
> - `miIO.info` expõe `VmPeak`/`VmSize`/`VmRSS`/`MemFree`, mesmo padrão do S40, o que reforça que é a mesma plataforma
> - Controle local MIoT via UDP 54321 **funciona**: `info`, `status` e `locate` (`code 0`)
> - Com o robô carregando: `fault = 210013` e `cleaning-progress = -1` (sem limpeza em andamento). **210013 = provavelmente filtro removido**: os filtros estavam sendo lavados, e o `2/66` registrou a falha às 13:29. Falta confirmar se zera ao recolocar
> - `room-information` (2/16) vem como string JSON: `{"rooms":[{"id":3,"name":"Sala de estar"},…],"map_uid":1}`. No mapa 1:
>   - 3 Sala de estar
>   - 4 Quarto de criança
>   - 5 Quarto
>   - 6 Cozinha
>   - 7 Banheiro
>   - 8 Corredor
> - Nas respostas, o robô devolve o `did` como o **device id** (ignora o `did` enviado). Por isso o script casa os resultados por siid/piid.
> - Pedidos grandes de `get_properties` (lotes de 10) podem **ficar sem resposta**. O `dump` lê em lotes de 5 e, se um lote falhar, lê item a item. Possível causa: o buffer de recepção do python-miio é de 4 KB (`recvfrom(4096)`) e algumas propriedades são strings JSON longas.

---

## 2. Análise: python-miio

### 2.1 O que é e em que estado está
- Biblioteca Python + CLI `miiocli` para os protocolos **miIO** (legado, métodos tipo `get_status`) e **MIoT** (modelo siid/piid/aiid).
- **Ativo:** último commit em 25/07/2026 ("genericmiot: add metadata command").
- A **0.6.0 ainda não saiu**. Para aparelhos MIoT, use a versão do GitHub:
  - `pip install git+https://github.com/rytilahti/python-miio.git`, que exige Git instalado;
  - ou `py -m pip install https://github.com/rytilahti/python-miio/archive/refs/heads/master.zip`, sem Git.
  - Exige **Python ≥ 3.11**.
- Não tem integração dedicada para `xiaomi.vacuum.ov*`. O caminho é `genericmiot` ou `miotdevice` com siid/piid "na mão".

### 2.2 Mapa do código (o que olhar)

| Arquivo | O que faz | Por que importa para o H50 Pro |
|---|---|---|
| `miio/protocol.py` | Framing do pacote e criptografia AES | Entender e depurar o tráfego |
| `miio/miioprotocol.py` | Handshake, envio por UDP, retry, ids | É o transporte de tudo |
| `miio/device.py` | Classe base: `send`, `raw_command`, `info`, `update` (OTA), `configure_wifi` | `send()` é o que o `h50pro.py` usa |
| `miio/miot_device.py` | `get_property_by`, `set_property_by`, `call_action_by` | Controle MIoT cru por siid/piid/aiid |
| `miio/integrations/genericmiot/` | Baixa a spec do miot-spec.org e gera status/settings/actions automaticamente | Suporte "de graça" para o ov42gl |
| `miio/miot_cloud.py` | Baixa e cacheia a spec por modelo | O `genericmiot` precisa de internet na 1ª vez |
| `miio/cloud.py` | Login na conta Xiaomi (lib `micloud`), lista devices + tokens + IP | Uma das formas de pegar o token |
| `miio/push_server/` | Recebe eventos via "cenas locais" | Testado em gateways; no robô é **desconhecido** |
| `miio/devtools/pcapparser.py` | Decifra uma captura `.pcap` usando o token | Engenharia reversa do tráfego app ↔ robô na LAN |
| `miio/devtools/simulators/` | Simuladores miIO/MIoT | Testar scripts sem o robô (usei para validar o `h50pro.py`) |
| `miio/integrations/dreame/vacuum/` | Dreame, incluindo **instalação de voz via HTTP local** (`OneShotServer`) | Precedente de técnica (ver §5.6) |
| `miio/integrations/{roborock,ijai,viomi,roidmi}/` | Integrações dedicadas de outros robôs | Referência de modelagem |

### 2.3 Protocolo miIO em 1 minuto
- **Transporte:** UDP **54321**, um pacote por mensagem.
- **Handshake ("hello"):** 32 bytes com magic `0x2131` e o resto `0xFF`. O aparelho responde com o **DID** e o **timestamp**. O token só volta em claro se o aparelho **não estiver provisionado**; nos atuais vem `ffff…`.
- **Header (32 bytes):** magic `0x2131` | length | unknown (0) | DID | stamp | checksum = `MD5(header + token + dados)`.
- **Payload:** AES-128-CBC, `key = MD5(token)`, `iv = MD5(key + token)`, padding PKCS7.
- **Corpo:** JSON-RPC `{"id", "method", "params"}`. Para MIoT:
  - `get_properties` → `[{"did","siid","piid"}]`
  - `set_properties` → `[{"did","siid","piid","value"}]`
  - `action` → `{"did","siid","aiid","in":[valores]}` (algumas marcas, como Dreame, aceitam `in: [{"piid":x,"value":y}]`)
- **Nuvem:** mesmo framing, outra chave. O robô abre a sessão com `_otc.info`, manda keep-alive a cada ~15 s e push de status a cada ~30 min (detalhes no `cloudprotocol.pdf` do dustcloud).

### 2.4 Comandos úteis
Os comandos `miotdevice` abaixo foram testados contra o simulador MIoT. Os de `cloud` e `genericmiot` precisam de internet (conta Xiaomi / miot-spec.org) e não foram testados aqui.

```bash
pip install git+https://github.com/rytilahti/python-miio.git

# token/IP pela conta (pode falhar com 2FA; alternativa no §5.1)
miiocli cloud list

# info básica (firmware, MAC, Wi-Fi)
miiocli device --ip IP --token TOKEN info

# genérico guiado pela spec (baixa a spec do miot-spec.org)
miiocli genericmiot --ip IP --token TOKEN status
miiocli genericmiot --ip IP --token TOKEN actions        # lista os nomes das ações
miiocli genericmiot --ip IP --token TOKEN call <servico:acao>

# cru por siid/piid/aiid (não depende da spec)
M="miiocli miotdevice --ip IP --token TOKEN --model xiaomi.vacuum.ov42gl"
$M get_property_by 2 2                 # status
$M set_property_by 2 9 4 int           # sucção = Max
$M call_action_by 2 16 '["3,4"]'       # limpar cômodos 3 e 4
$M call_action_by 2 3                  # parar e voltar para a base

# decifrar captura de rede
miiocli devtools parse-pcap captura.pcap TOKEN
```

**Pontos de atenção**
- Na issue #2052 (S40 Pro), `info` reconhecia o aparelho como "Supported by genericmiot", mas o `status` abortava. O crash do `click` relatado ali **já está corrigido no master atual**: conferi no código, `DeviceGroup` agora passa kwargs e preserva `self.commands`.
- Se o `genericmiot status` falhar, use `miotdevice ... get_property_by` ou o `h50pro.py`, que só usam MIoT cru.

---

## 3. Análise: dustcloud

### 3.1 Estado
- O README diz que o repositório está **desatualizado** e que a emulação de nuvem para robôs foi **incorporada ao [Valetudo](https://valetudo.cloud)**. Último commit: ago/2023.
- A documentação técnica (fotos, datasheets, logs UART) foi movida para [dustcloud-documentation](https://github.com/dgiese/dustcloud-documentation). As fichas técnicas atuais ficam em [robotinfo.dev](https://robotinfo.dev).

### 3.2 Componentes

| Pasta | O que é | Lição aproveitável |
|---|---|---|
| `dustcloud/server.py` | Proxy/emulador da nuvem Xiaomi em Python (MySQL + painel PHP). Responde `_otc.info` com o próprio IP e **bloqueia** `miIO.ota`, `miIO.config_router` e `enable_log_upload` vindos da nuvem | Arquitetura "man-in-the-middle" da nuvem: precisa que o robô aceite outro servidor, o que **exige root** |
| `dummycloud/` (C) | Nuvem falsa mínima rodando **no próprio robô**, para operar 100% offline | Só funciona com root |
| `dummycloud/doc/etc_hosts-snippet.txt` | Lista dos hosts de nuvem: `ot.io.mi.com`, `ott.io.mi.com` e variantes regionais (`de.`, `sg.`, `us.`, `ru.`, `in.`…), mais os buckets `*.fds.api.xiaomi.com` | **Útil hoje** como ponto de partida para regras de DNS/firewall no roteador ou no AdGuard/Pi-hole |
| `dummycloud/doc/etc_rc.local-snippet.txt` | iptables NAT redirecionando 80/8053 para o localhost | Mostra as portas da nuvem: TCP 80 e UDP 8053 |
| `devices/xiaomi.vacuum/firmwarebuilder/imagebuilder.sh` | Reempacota firmware `.pkg` de Roborock Gen1/Gen2: injeta chave SSH, desativa OTA, troca `adbd`, inclui Valetudo | Funcionava porque esse firmware **não era assinado**. Não se aplica ao H50 Pro |
| `devices/xiaomi.vacuum/miio_client_os/` | Reimplementação open-source do `miio_client` | Didático para entender o daemon |
| `devices/xiaomi.vacuum/audio_generator/` | Gera pacotes de voz com TTS (gTTS etc.) | Ideia de voz customizada; no H50 Pro é bloqueada sem root (§5.6) |
| `devices/xiaomi.vacuum/scripts/` | `disable_logging.sh`, `setwifi.sh`, `morestorage.sh` | Pós-root em Roborock antigo |
| `cloudprotocol.pdf` | Slides do protocolo de nuvem (34C3, 2017) | **Melhor resumo** de `_otc.info`, keep-alive e push de status |
| `presentations/` | 34C3 e Recon BRX 2018 | Contexto histórico do root sem abrir o robô |

### 3.3 Por que não se aplica diretamente
Os métodos do dustcloud dependem de três coisas que o H50 Pro não oferece:
1. Firmware **sem assinatura**, que dava para reempacotar e mandar via `miIO.ota`.
2. Aceitar **qualquer servidor de nuvem**.
3. Acesso **root/SSH**.

Os robôs atuais têm firmware assinado, TLS estrito e, em vários casos, secure boot.

---

## 4. Root / Valetudo: situação real

### 4.1 Valetudo
- A lista de robôs suportados é **exaustiva**: o que não está lá não é suportado. Os modelos com marca Xiaomi que constam são V1, 1C (só `dreame.vacuum.mc1808`), 1T, P2148, Vacuum-Mop P, Vacuum-Mop 2 Ultra e X10 Plus. **Não há H50/H40/S40/5 Pro.**
- O próprio Valetudo avisa que robôs com marca Xiaomi **são feitos por fabricantes diferentes**. Não dá para presumir compatibilidade de root nem de peças.
- O root depende de falhas que os fabricantes corrigem por OTA, então modelos novos tendem a ficar mais difíceis.

### 4.2 Pesquisa pública sobre a família "ov" (até abr/2026)
- **Nenhum root público**, nenhuma extração de firmware e **SoC não identificado**. Os palpites são classe Allwinner R ou Rockchip RV1106/RK3308, sem confirmação.
- **Pacote de voz** (`siid 15 / aiid 1`): ZIP de MP3 sem criptografia, num CDN `alsgp0.fds.api.xiaomi.com` com escrita restrita. Pela nuvem, o firmware rejeitou (`-704220043`). Com o robô validando TLS, a injeção de URL ficou inviável sem root.
- **Próximos passos sugeridos pelo pesquisador** (todos em aberto): identificar o SoC, achar UART/JTAG/USB, ver se há FEL/maskrom e mapear partições e assinatura.

### 4.3 Se mesmo assim quiser tentar pelo hardware (não recomendado)
- **Riscos:** perda da garantia, **brick irreversível**, bateria Li-ion de 14,4 V.
- **Roteiro genérico** (é como se faz em outros robôs; nada confirmado para este):
  1. Abrir o robô e fotografar a placa principal (SoC, NAND/eMMC, pads de teste).
  2. Procurar UART 3,3 V com um adaptador USB-TTL. Nunca use 5 V.
  3. Identificar o SoC. Allwinner costuma ter modo **FEL** e Rockchip **maskrom**, mas o secure boot pode bloquear os dois.
  4. Dump da flash e análise de partições (binwalk). Verificar se o firmware é assinado.
- **Melhor contribuição de baixo risco:** publicar fotos da placa e o log de boot da UART (só leitura) para a comunidade, por exemplo em [robotinfo.dev](https://robotinfo.dev) ou no canal do Dennis Giese. É assim que os modelos passam a ser suportados.
- Se o objetivo é **Valetudo de verdade**, o caminho realista é um robô da lista suportada (Dreame X40 Ultra, L40 Ultra etc.), conferindo a revisão exata.

---

## 5. O que dá para customizar sem root

### 5.1 Pegar o token e o IP
1. **[Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)** (recomendado). No Windows, baixe o `token_extractor.exe` da última release. Faça login por **QR code** ou senha. Se deixar a região em branco, ele varre todos os servidores. Saída: nome, **IP**, **token** (32 hex), modelo.
2. Ou `miiocli cloud list` (python-miio + `micloud`), que pode falhar com 2FA.

Depois:
- Faça **reserva de DHCP** para o IP do robô.
- O token **muda se o robô for re-pareado** (reset de Wi-Fi, troca de conta).
- O 2FA da Xiaomi tem limite diário (3 a 5 envios). Se travar, espere.

### 5.2 Controle local com o `h50pro.py` (anexo, na mesma pasta)
Script de linha de comando sobre o python-miio, só com MIoT cru (sem depender do miot-spec.org). Validado no simulador MIoT e **no robô real** (`info`, `status`, `locate`) em 11/10/2026, com Python 3.14 no Windows. Use `py` no lugar de `python` se o `python` do PATH estiver quebrado.

Para não precisar repetir o `set` em cada janela, grave as variáveis no seu usuário (valem nas próximas janelas do CMD):
```bat
setx H50_IP 192.168.1.50
setx H50_TOKEN <32 hex>
```
Reserve também o IP do robô no DHCP do roteador.

**Windows (Prompt de Comando / CMD), do zero:**

```bat
:: 1) Python (uma vez; depois feche e reabra o CMD)
winget install -e --id Python.Python.3.12

:: 2) python-miio direto do GitHub (zip, não precisa de Git)
py -m pip install https://github.com/rytilahti/python-miio/archive/refs/heads/master.zip

:: 3) credenciais (valem só nesta janela do CMD; sem aspas, sem espaços)
cd C:\claude_local\xiaomi
set H50_IP=192.168.x.y
set H50_TOKEN=<32 hex>

:: 4) testar
py h50pro.py info
py h50pro.py status
```

No PowerShell, as variáveis ficam `$env:H50_IP="192.168.x.y"; $env:H50_TOKEN="<32 hex>"`. Os exemplos abaixo valem para os dois; troque `python` por `py` se o `python` não for reconhecido.

```powershell
python h50pro.py info            # fw_ver, MAC, RSSI
python h50pro.py status          # estado, modo, sucção, água, bateria, progresso
python h50pro.py consumables     # vida útil de escovas, filtro, mop, saco, detergente
python h50pro.py rooms           # lista id -> nome dos cômodos
python h50pro.py clean-rooms 3,4
python h50pro.py clean-rooms cozinha,banheiro   # também aceita nomes (sem acento, sem espaço após a vírgula)
python h50pro.py suction max     # quiet|standard|strong|max
python h50pro.py water 2         # off|1|2|3
python h50pro.py dust            # esvaziar na base;  wash-mop | dry | stop-dry
python h50pro.py home            # volta para a base;  start | pause | resume | stop | locate
python h50pro.py get 2 97        # qualquer siid/piid
python h50pro.py set 4 2 40      # escrever (volume = 40)
python h50pro.py action 2 16 '["3,4"]'
python h50pro.py action 2 16 '[{"piid":15,"value":"3,4"}]'   # formato alternativo, se o 1º falhar
python h50pro.py dump --json > dump.json   # TODAS as propriedades legíveis
python h50pro.py scan 21 1 40    # procura piids no siid 21 (não documentado)
```

> **Windows PowerShell 5.1** remove as aspas duplas internas ao passar argumentos para programas externos, e `'["3,4"]'` chega como `[3,4]`.
> Use `clean-rooms 3,4` (não usa JSON), escape as aspas (`'[\"3,4\"]'`) ou rode no PowerShell 7.3+ / CMD.

### 5.3 Mapa MIoT essencial (spec v2)

**Estado e modo** (siid 2 = vacuum)

| siid/piid | Nome | Acesso | Valores |
|---|---|---|---|
| 2/2 | status | R | 1 standby, 2 carregando, 4 limpando, 5 pausado, 6 voltando, 7 lavando mop, 9 carga completa, 10 mapeando, 11 atualizando, 15 anormal, 16 aspira + pano, 17 só pano… (24 estados, ver anexo) |
| 2/3 | fault | R | código de erro (0 = ok) |
| 2/4 | sweep-mop-type | RW | 1 aspirar, 2 pano, 3 aspirar + pano, 4 aspirar depois pano |
| 2/8 | clean-times | RW | 1–3 passadas |
| 2/9 | mode (sucção) | RW | 1 quiet, 2 standard, 3 strong, 4 max |
| 2/10 | mop-water-output-level | RW | 0 off, 1–3 |
| 2/16 | room-information | R | string (JSON) com os cômodos |
| 2/73 | carpet-cleaning-method | RW | 0 adaptativo, 1 evitar, 2 ignorar, 3 cruzar |
| 2/74 | sweep-route | RW | 1 rápido, 2 diário, 3 fino |
| 2/75 | obstacle-avoidance-strategy | RW | 0 menos colisão, 1 mais cobertura |
| 2/84 | wash-mop-water-temperature | RW | 0 ambiente, 1 morna, 2 quente, 3 smart |
| 2/89 | cleaning-progress | R | 0–100 % |
| 2/97 | sewage-tank-status | R | 1 = tanque de água suja cheio |
| 2/98 | water-tank-status | R | 1 = tanque de água limpa vazio |

**Bateria, som e ajustes gerais**

| siid/piid | Nome | Acesso | Valores |
|---|---|---|---|
| 3/1, 3/2 | battery-level / charging-state | R | % / 1 carregando, 2 não, 3 não carregável |
| 4/2 | volume | RW | 0–100 |
| 5/1 | child lock | RW | bool |
| 11/1, 11/2 | no-disturb / período | RW | bool / `HH:MM:SS-HH:MM:SS` |

**Consumíveis** (o par `x/1` é a vida em %, o `x/2` são as horas restantes)

| siid | Consumível | Ação de reset |
|---|---|---|
| 9 | mop | 9/1 |
| 12 | escova principal | 12/1 |
| 13 | escova lateral | 13/1 |
| 14 | filtro | 14/1 |
| 18 | detergente (18/1 é o nível) | 18/1 |
| 19 | saco de pó | 19/1 |

**Ações** (siid/aiid)

| siid/aiid | Ação | Entrada |
|---|---|---|
| 2/1 | iniciar | – |
| 2/2 | parar | – |
| 2/3 | parar e voltar | – |
| 2/7 | pausar | – |
| 2/8 | continuar | – |
| 2/16 | limpar cômodos | piid 15 = ids `"3,4"` |
| 2/37 | limpar zona | piid 12 |
| 2/18 | esvaziar pó | – |
| 2/19 | lavar mop | – |
| 2/20 | secar mop | – |
| 2/31 | parar lavagem | – |
| 2/32 | parar secagem | – |
| 2/57 | esvaziar tanque da base | – |
| 2/63 | autolimpeza da base | – |
| 2/26 | controle remoto | 2/39 button-type; provavelmente exige 2/28 enter-remote antes |
| 3/1 | voltar para carregar | – |
| 6/1 | identify (localizar) | – |
| 10/3 | trocar mapa | piid 6 |
| 10/5 | partição automática de cômodos | – |
| 10/8 | restaurar mapa | piid 6 |

**Mapa** (siid 10)

| siid/piid | Nome | Valores |
|---|---|---|
| 10/1 | map-obj-name | nome do objeto do mapa no armazenamento da nuvem; o mapa em si **não vem pela LAN** |
| 10/4 | vacuum-position | posição do robô |
| 10/6 | current-map-id | id do mapa ativo |
| 10/13 | backup-map-list | lista de backups |

### 5.4 Home Assistant: opções

| Integração | Como conecta | Situação para o H50 Pro |
|---|---|---|
| **[Xiaomi Vacuum (letitbe-dull/xiaomi-vac)](https://github.com/letitbe-dull/xiaomi-vac)** (HACS) | Login Mi (descobre IP/token) **ou** IP + token. Controle local MIoT, poll a cada 10 s. Mapa via nuvem | **Lista `ov42gl` e `ov43gb` como suportados**, com cômodos e card Lovelace. Mapas só foram verificados no ijai v17, então no ov42gl são **não testados** |
| **[Xiaomi Miot (al-one/hass-xiaomi-miot)](https://github.com/al-one/hass-xiaomi-miot)** (HACS) | Automático (local quando dá, nuvem no resto), só local, ou só nuvem. Também via host/token | Genérico pela spec. Expõe qualquer siid/piid: `xiaomi_miot.call_action`, `set_miot_property`, `get_properties`. Bom para os ajustes finos |
| **[Xiaomi Home oficial (XiaoMi/ha_xiaomi_home)](https://github.com/XiaoMi/ha_xiaomi_home)** | OAuth na nuvem Xiaomi | Modelos "de exportação" só aparecem com a **região certa**. No S40 Pro foi preciso escolher Europa (issue #1539). Use a mesma região do seu app |
| Xiaomi Miio (core do HA) | Local, por integrações dedicadas | **Não suporta** a família ov (issue #157951 para o S40 Pro) |

Exemplos (hass-xiaomi-miot):

```yaml
# limpar cozinha e sala quando todos saírem
automation:
  - alias: "H50 – limpar ao sair"
    trigger:
      - platform: state
        entity_id: group.familia
        to: not_home
        for: "00:10:00"
    action:
      - service: xiaomi_miot.call_action
        data:
          entity_id: vacuum.xiaomi_ov42gl
          siid: 2
          aiid: 16
          params: ["3,4"]

  - alias: "H50 – tanque sujo cheio"
    trigger:
      - platform: template
        value_template: "{{ state_attr('vacuum.xiaomi_ov42gl', 'vacuum.sewage_tank_status') == 1 }}"
    action:
      - service: notify.mobile_app_celular
        data: { message: "Esvaziar o tanque de água suja do H50 Pro" }
```

> O nome do atributo depende de como a integração expõe a spec. Confira em *Ferramentas de desenvolvedor → Estados*. Se precisar, leia o valor com `xiaomi_miot.get_properties` (`mapping: [{siid: 2, piid: 97}]`).

Outras ideias de automação:
- Sucção Max (2/9 = 4) só em cômodos com tapete.
- DND (11/1) à noite.
- Alerta de consumível abaixo de 10 %.
- "Esvaziar pó" (2/18) depois de cada limpeza.
- Pausar quando a campainha tocar.

### 5.5 Rede e privacidade (perspectiva de infraestrutura)
- **VLAN de IoT** para o robô, com Wi-Fi 2.4 GHz dedicado. Libere **só UDP 54321** do host do Home Assistant até o robô.
- O robô **precisa da nuvem** para o app, a voz (Alexa/Google) e os mapas. Bloqueá-la é experimental:
  - O controle local MIoT costuma continuar funcionando.
  - Com a nuvem bloqueada, você perde app e OTA.
  - Teste antes se o firmware não entra em loop de reconexão.
- Hosts de referência (do dustcloud, podem estar desatualizados):
  - `ot.io.mi.com`, `ott.io.mi.com` e as variantes `<região>.ot(t).io.mi.com`, nas portas TCP 80 e UDP 8053
  - buckets `*.fds.api.xiaomi.com`; na família ov, voz/CDN em `alsgp0.fds.api.xiaomi.com`
- Para medir o que o robô fala com a nuvem, espelhe a porta no switch ou capture no roteador (`tcpdump host <ip-do-robô>`) e veja DNS, destinos e volume.
- **Firmware:**
  - Se um dia surgir root para a família, ele provavelmente vai depender de uma versão específica. Desligar a atualização automática no app (se houver a opção) preserva essa chance.
  - O custo é ficar sem correções.

### 5.6 Experimentos de baixo risco
| Experimento | Como | Expectativa |
|---|---|---|
| Inventário completo de propriedades | `h50pro.py dump --json` com o robô parado e depois limpando; compare os dois | Entender estados reais e strings JSON (cômodos, config de limpeza) |
| Propriedades não documentadas | `h50pro.py scan 21 1 40` (e siids 7, 8, 23–30) | Na família há pelo menos 8 piids no siid 21 |
| Formato dos cômodos e zonas | Ler 2/16 (`room-information`) e 2/40 (`current-cleaning-config`) | Montar limpezas por zona (2/37) e configurações por cômodo (2/13) |
| Tráfego local do app | Capturar UDP 54321 enquanto usa o app na mesma LAN, depois `miiocli devtools parse-pcap captura.pcap TOKEN` | Descobrir parâmetros que o app manda (se o app falar local; muitas vezes vai pela nuvem) |
| Pacote de voz customizado | `action 15 1` com URL HTTP na LAN + MD5 (como o python-miio faz com Dreame) | **Baixa chance**: no S40, via nuvem, o firmware rejeitou (`-704220043`). Risco baixo, mas não zero: teste só com um pacote íntegro (ZIP de MP3 no mesmo formato do original) |

**Não faça:**
- `miIO.ota` / `Device.update()` com firmware arbitrário: é assinado e não há ganho.
- Escrever em `20/6 spec-test` ou chamar `16/1 imu-calibration` sem motivo.
- Escrever em piids que você não entende.

---

## 6. Roteiro sugerido

1. Extrair o token e o IP (Xiaomi-cloud-tokens-extractor) e reservar o IP no DHCP.
2. `python h50pro.py info` e `status`: confirmar o firmware e o acesso local.
3. `dump` e `rooms`: documentar os ids de cômodos e os valores reais. Salvar o resultado neste Project.
4. Instalar o **xiaomi-vac** ou o **hass-xiaomi-miot** no Home Assistant e criar as automações.
5. Mover o robô para a VLAN de IoT e restringir o tráfego.
6. Opcional: `scan` de siids não documentados e captura de tráfego para mapear o restante.
7. Acompanhar o Valetudo/Dustbuilder e o gist da família ov para saber se aparece root.

---

## Anexo A: spec completa (`urn:…:xiaomi-ov42gl:2`)

Acesso: R leitura, W escrita, N notify. Fonte: home.miot-spec.com.

**siid 2 – vacuum (propriedades)**
1 firmware-version R · 2 status R (1 standby, 2 carregando, 3 carga p/ retomar, 4 limpando, 5 pausado, 6 voltando, 7 lavando mop, 8 controle remoto, 9 carga completa, 10 mapeando, 11 atualizando, 12 base limpando, 13 trocando tarefa, 14 base carregando, 15 anormal, 16 aspira+pano, 17 pano, 18 mapeamento pausado, 19 retorno p/ retomar, 20 retorno no meio, 21 retorno do mapeamento, 22 enxágue auxiliar, 23 lavagem auxiliar ok, 24 voltando p/ carregar) · 3 fault R · 4 sweep-mop-type RW · 5 sweep-type RW (1 casa, 2 zona, 3 cômodo, 4 bordas, 5 custom, 6 ponto, 7 custom sweep, 8 agendada, 9 vinculada, 10 mapeamento rápido, 11 AI) · 6 cleaning-area R (0,01 m²) · 7 cleaning-time R · 8 clean-times RW · 9 mode RW · 10 mop-water-output-level RW · 11 mop-status R · 12 zone-ids R · 13 restricted-sweep-areas RW · 14 restricted-walls RW · 15 vacuum-room-ids (parâmetro) · 16 room-information R · 17 last-clean-time R · 18 base-station-working-status R · 19 order-clean R · 20 carpet-boost RW · 21 carpet-avoidance RW · 22 carpet-display RW · 23 sweep-break-switch RW · 24 common-params (parâmetro) · 25 sleep-status R · 26 location-status R · 27 map-complete-dialog RW · 28 enable-mop-wash RW · 29 frequency-mop-wash RW (0 cômodo, 1 área, 2 tempo) · 30 water-output-for-washing-mop RW (0 profunda, 1 diária, 2 econômica) · 31 drying-time RW (1=2 h, 2=3 h, 3=4 h) · 32 auto-dust-arrest RW · 33 dust-arrest-frequency RW · 34 auto-mop-dry RW · 35 auto-water-change RW · 36 use-detergent RW · 37 ai-cleaning RW · 38 exit-remote-dialog RW · 39 button-type (parâmetro) · 40 current-cleaning-config R · 41 hot-water-mop-wash RW · 42 user-define-sweep-cfg R · 43 user-define-sweep-id R · 44 mop-auto-lift RW · 45 sweep-ai-detection RW · 46 dirt-detection RW · 47 object-detection RW · 48 room-detection RW · 49 floor-material-detection RW · 50 defecation-detection RW · 51 liquid-dirt-detection RW · 52 solid-dirt-detection RW · 53 water-check-list R · 54 water-check-status R · 55 edge-swing-tail-sweep RW · 56 sweep-ai-object R · 57 sweep-furniture RW · 58 carpet-object RW · 59 detergent-self-delivery RW · 60 mop-water-output-level-no-tank RW · 61 frequency-mop-wash-no-tank RW · 62 auto-water-change-installed R · 63 cut-hair-config RW · 64 frequency-cut-hair-config RW · 65 vacuum-route (parâmetro) · 66 fault-ids R · 67 action-result R · 68 edge-sweep-frequency RW · 69 ai-managed-cleaning RW · 70 plugin-info-remind RW · 71 detergent-depletion-reminder RW · 72 notice R · 73 carpet-cleaning-method RW · 74 sweep-route RW · 75 obstacle-avoidance-strategy RW · 76 carpet-deep-cleaning RW · 77 carpet-discriminate RW · 78 sweep-carpet-first RW · 79 mop-outer-swing RW · 80 mop-outer-swing-frequency RW · 81 frequency-mop-wash-by-time RW · 82 auto-dust-arrest-power-level RW (0 silencioso, 1 diário, 2 forte) · 83 worry-free-clean-mode RW (0 silencioso, 1 profundo, 2 padrão, 3 mordomo, 4 pet) · 84 wash-mop-water-temperature RW · 85 statistical-clean-area R · 86 statistical-cleaning-times R · 87 statistical-cleaning-duration R · 88 drying-progress R · 89 cleaning-progress R · 90 dry-left-time R · 91 brush-outswing RW · 92 repeat-wash-mop RW · 93 real-scene-capture RW · 94 auto-night-fill-light RW · 95 ai-wake-up RW · 96 sweep-mop-status R · 97 sewage-tank-status R · 98 water-tank-status R · 99 sill RW · 100 base-station-water-tank-status R · 101 host-water-tank-status R · 102 furniture-for-automation R

**siid 2 – ações:** 1 start-sweep · 2 stop-sweeping · 3 stop-and-gocharge · 4 start-only-sweep · 5 start-mop · 6 start-sweep-mop · 7 pause · 8 continue · 9 start-custom-sweep · 10 get-zone-configs(12) · 11 get-room-configs(15) · 12 set-zone(12) · 13 set-room-clean-configs(16) · 14 split-room(24) · 15 merge-rooms(15) · 16 start-vacuum-room-sweep(15) · 17 start-build-map · 18 start-dust-arrest · 19 start-mop-wash · 20 start-dry · 21 start-eject · 22 start-call-clean · 23/24/25 add/modify/delete-order-clean(24) · 26 remote-control(39) · 27 try-listen · 28 enter-remote · 29 exit-remote · 30 get-system-info · 31 stop-mop-wash · 32 stop-dry · 33 continue-build-map · 34 stop-build-map-and-gocharge · 35 pause-build-map · 36 back-mop-wash · 37 start-zone-sweep(12) · 38–41 user-sweep-setting add/del/modify/set · 42 start-user-define-sweep(43) · 43/44 start/stop-cut-hair · 45/46 start/cancel-water-self-check · 47 get-vacuum-route(24) · 48 close-abnormal-card(24) · 49 start-base-station-cleaning · 50 start-sweep-before-mopping · 51 stop-working · 52 skip-cleaning(15) · 53 final-cleaning(15) · 54 temporary-cleaning-room(15) · 55 temporary-cleaning-zone(24) · 56 start-furniture-cleaning(24) · 57 empty-base-station-water-tank · 58 empty-host-water-tank · 59 spot-cleaning · 60 operate-ai-recognize-obj(24) · 61 get-ai-picture-obj(24) · 62 common-object-clean(24) · 63/64 start/stop-self-cleaning-of-the-station
(número entre parênteses = piid de entrada)

**siid 2 – eventos:** 1 build-map-complete · 2 sweep-complete · 3 dust-arrest-complete · 4 mop-wash-complete · 5 dry-complete · 6 eject-complete · 7 call-clean-complete

**Demais serviços**
- **3 battery:** 1 level R · 2 charging-state R · 3 voltage R · ação 1 start-charge · evento 1 low-battery
- **4 alarm:** 1 alarm RW · 2 volume RW
- **5 physical-controls-locked:** 1 locked RW · 2 current-lock R
- **6 identify:** ação 1 identify
- **9 mop:** 1 life-level R · 2 left-time R · ação 1 reset
- **10 vacuum-map:** 1 map-obj-name · 2 trajectory-obj-name · 3 clean-record · 4 vacuum-position · 5 map-management · 6 current-map-id · 7 carpet-obj-name · 8 common-params · 9 map-3d-info · 10 map-switch-method RW (0 manual, 1 auto) · 11 map-upload-stop RW · 12 map-upload-stop-action-result · 13 backup-map-list · 14 restore-map-result · 15 cloud-clean-record
  - ações: 1 clear-map · 2 delete-map(6) · 3 set-map(6) · 4 save-map · 5 auto-room-partition · 6 set-map-name(8) · 7 update-properties-data · 8 restore-map(6)
  - eventos: 1 map-notify · 2 trajectory-notify
- **11 no-disturb:** 1 no-disturb RW · 2 enable-time-period RW · 3 current-no-disturb R
- **12 / 13 brush-cleaner (principal / lateral):** 1 life-level · 2 left-time · ação 1 reset
- **14 filter:** 1 life-level · 2 left-time · ação 1 reset
- **15 voice-management:** 1 target-voice RW · 2 cur-voice R · 3 download-status R · 4 download-progress R · 5 voice-url · 6 common-params
  - ações: 1 download-voice(1,5,6) · 2 get-download-status
- **16 imu:** ação 1 imu-calibration
- **17 ai-small-pictures:** 1 ai-object-id · 2 ai-picture-info R · ação 1 request-ai-picture(1)
- **18 detergent-management:** 1 left-level R · 2 self-delivery RW · 3 self-delivery-level RW (0 pouco, 1 padrão, 2 muito, 3 extra) · 4 left-time R · ação 1 reset · evento 1 low-detergent-level
- **19 dust-bag:** 1 life-level · 2 left-time · ação 1 reset
- **20 custom:** 1 common-params · 2 query-id · 3 updata-difference R · 6 spec-test RW · 13 water-level-remind RW
  - ações: 1 get-history-obj · 2 get-user-define · 3 set-stop-upload-map · 5 get-order-clean · 6 switch-order-clean (todas com entrada 2 query-id)
- **22 self-check:** 1 self-check-items · 2 self-check-results R

---

## Fontes

Repositórios analisados
- [rytilahti/python-miio](https://github.com/rytilahti/python-miio): código clonado em 11/10/2026, commit `9a00e08`
- [dgiese/dustcloud](https://github.com/dgiese/dustcloud): commit `9f4b672` (ago/2023)

Modelo e spec
- [Xiaomi Robot Vacuum H50 Pro: página oficial (UK)](https://www.mi.com/uk/xiaomi-robot-vacuum-h50-pro/)
- [Spec MIoT `xiaomi.vacuum.ov42gl`](https://home.miot-spec.com/spec/xiaomi.vacuum.ov42gl) · [ficha](https://home.miot-spec.com/s/xiaomi.vacuum.ov42gl) · [H50 `ov43gb`](https://home.miot-spec.com/p/xiaomi.vacuum.ov43gb)
- [Guru3D: anúncio do H50 Pro](https://guru3d.com/story/xiaomi-unveils-h50-pro-robot-vacuum-with-15000pa-suction-power/)
- [Manual Mijia 5C (OV42CN)](https://ae01.alicdn.com/kf/Sa25b94dd778240e38786cfa9c40cd575Z.pdf)
- [Mijia 5C OV42CN no JD](https://item.jd.com/100204620735.html)

Família ov, root e Valetudo
- [Recon dossier Xiaomi/Shunzao (ov81gl/b108gl/ov71gl)](https://gist.github.com/breakneck-git/98b8c7abf4f74cddd9303271674e48b9)
- [Valetudo: Supported Robots](https://valetudo.cloud/pages/general/supported-robots.html) · [Rooting essentials](https://valetudo.cloud/pages/general/rooting-essentials.html)
- [Dustbuilder](https://dustbuilder.dontvacuum.me/) · [dontvacuum.me](https://dontvacuum.me/) · [Palestra DEF CON 31 (Giese)](https://dontvacuum.me/talks/DEFCON31/DEFCON31-vacuum-robots-final.pdf)
- [Dreame & Roborock 2025–2026 rooting tracker](https://www.privacysmarthome.com/guides/dreame-roborock-2025-2026-valetudo-rooting-tracker/)
- [python-miio issue #2052 (S40 Pro)](https://github.com/rytilahti/python-miio/issues/2052)
- [ha_xiaomi_home issue #1539 (S40 Pro / região)](https://github.com/XiaoMi/ha_xiaomi_home/issues/1539)
- [HA core issue #157951](https://github.com/home-assistant/core/issues/157951)
- [xiaomi-vac issue #39 (H40 ov51gl)](https://github.com/letitbe-dull/xiaomi-vac/issues/39)

Integrações e ferramentas
- [letitbe-dull/xiaomi-vac](https://github.com/letitbe-dull/xiaomi-vac)
- [al-one/hass-xiaomi-miot](https://github.com/al-one/hass-xiaomi-miot)
- [XiaoMi/ha_xiaomi_home](https://github.com/XiaoMi/ha_xiaomi_home)
- [cpmarexel2f/ha-xiaomi-vacuum](https://github.com/cpmarexel2f/ha-xiaomi-vacuum) (X20 Max, S20+, S40 Pro)
- [PiotrMachowski/Xiaomi-cloud-tokens-extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor)
- [Xiaomi Cloud Map Extractor](https://github.com/PiotrMachowski/Home-Assistant-custom-components-Xiaomi-Cloud-Map-Extractor) (suporte à família ov não confirmado)
