# Descobertas: o que o H50 Pro faz e os manuais não dizem

Achados de engenharia reversa do `xiaomi.vacuum.ov42gl` (fw `4.5.8_0087`), observados em um aparelho real em
outubro de 2026. Valores de exemplo são fictícios. Detalhes e cronologia: `PLANO-MVP.md`.

## 1. Limites dos canais

| Canal | Limite | Efeito |
|---|---|---|
| LAN (UDP 54321) | resposta ≤ ~1,4 KB (1.392 B passa, ~1.456 B não); os pacotes do robô saem com DF=1 | o `10/3` (histórico, ~2 KB) **nunca** chega; lotes têm de ser montados pelo **tamanho da resposta**, não pela quantidade |
| Nuvem, tempo real (`datasource` 2) | ≤ **40 propriedades** por pedido (~2,8 KB); acima, o robô não responde a tempo (`-704220043`, `-704083036`) | lotes de 40; o que falhar é refeito pelo cache |
| Nuvem, cache (`datasource` 1) | tudo de uma vez (149 de 165 props em ~2 s) | é o único caminho do `10/3` completo |
| Nuvem, geral | só expõe propriedades **registradas na spec** | as propriedades fora da spec (§2) só existem pela LAN |

Respostas do robô trazem o `did` do aparelho, ignorando o enviado: casar por `(siid, piid)`. Só métodos MIoT funcionam
(`get_properties`, `set_properties`, `action`, `miIO.info`). Um timeout dispara novo handshake (~5 s).

## 2. Propriedades fora da spec (só LAN)

| Prop | Conteúdo |
|---|---|
| `23/1` | cômodos com `surface` (tipo de piso): `[{"id","name","surface"}]`; `23/2` e `23/3` = `[]` |
| `21/1–21/8` | serviço sem spec (bool/int/texto vazios); ainda sem significado |
| `2/103–2/106`, `20/4` | valores simples (`''`, `1`, `1`, `''`, `0`); sem significado |

## 3. Estado e comportamento

- **`2/2` status**: 4 limpando, 5 pausado, 6 voltando, 12/14 base trabalhando, 2 carregando. O **12 aparece antes de sair**
  (a base prepara o mop); o **14 + `2/18`** descreve o que a base faz.
- **`2/18` `{"mode","progress"}`**: `1` secando (`2/90` = minutos restantes; `2/88` fica 0), `2` esvaziando o pó, `3` lavando o mop.
- **`2/17`** é o **início** da última limpeza (epoch). Ao fim da limpeza, `2/5` e `2/40` zeram e **~5 s depois** o `2/17` muda;
  `2/6` (0,01 m²) e `2/7` (s) guardam área e tempo dela até a próxima começar.
- **`2/40`** durante a limpeza: `{"rooms":[ids]}` (por cômodo), `{"zones":[[x1,y1,…,x4,y4]]}` (por zona, mm) ou
  `{"user_define":{"id","name","user_data":[[nomes],[valores]]}}` (rotina personalizada; `mode_data` = retângulos).
  `2/5`: 1 casa, 2 zona, 3 cômodos, 7 personalizada.
- **`11/2`** (não perturbe): 4 bytes `[h_ini, m_ini, h_fim, m_fim]` num inteiro (`23:00–06:00` = `0x17000600`).
- **`2/19`** (agenda): `week` bit0 = domingo … bit6 = sábado, bit7 = repetir; `time` = hora×256 + minuto.
- **`2/66`** (falhas): `{"ts","fault":[códigos]}`; `210013` aparece com o filtro/caixa de pó fora.
- O robô **não registra** limpezas muito curtas (pausa de ~5 s) mas registra interrompidas (rotina parada após ~3 min).

## 4. Rótulos do app ≠ nomes da spec

| No app | Propriedade |
|---|---|
| Foco em cantos e bordas (frequência) | **`2/80`** `mop-outer-swing-frequency` (não a `2/68`) |
| Reconhecimento de tapete | **`2/77`** `carpet-discriminate` |
| Frequência de lavagem do mop (sem troca automática de água) | **`2/61`** `-no-tank` (0=5, 1=10, **2=8**, 3=15, 4=20, 5=25 m²) |
| Modo de lavagem / Duração da secagem | `2/30` (0 minuciosa, 1 diária, 2 economia) / `2/31` (1=2 h, 2=3 h, 3=4 h) |
| Atalhos (Configurações gerais / baixo ruído / minuciosa) | `2/83` = 2 / 0 / 1 |

Variantes de hardware: com `2/62` (troca automática de água instalada) = `false`, o app usa `2/61` em vez de `2/29` + `2/81`.
Nome do aparelho, paredes virtuais, zonas, móveis (posição) e **configurações por cômodo** ficam no mapa, na nuvem.

## 5. Mapa (nuvem)

- `10/1` = `{"index","obj_name":"<uid>/<did>/0"}` (nome do objeto). A URL vem de `/v2/home/get_interim_file_url_pro`.
- Arquivo: `{"version":2,"data":"<base64>"}` = AES-128-CBC + zlib de um JSON. **Chave**: `MD5(AES-CBC(k, IV).encrypt(PKCS7(k + did)))`
  com `k = model[-16:]` e IV `ABCDEF1234123412` (engenharia reversa do plugin do Xiaomi Home pelo projeto *devbis/xiaomi-vac*).
- JSON: `map_data` (grade `largura×altura`, **50 mm/pixel**, pixel = id do cômodo, 1 = parede), `origin_x/y`, base, `position`,
  `room_attrs` (nome, posição do rótulo, sucção/água/passadas por cômodo), `fb_walls` (paredes virtuais),
  `furniture` (`type` 1220 sofá, 1400 cama, 1740 liteira; `pos` = 4 cantos), `paths.points` (tipo 1 limpando, 0 deslocamento).
- `10/13` (backup do mapa) muda quando o mapa é editado no app; `10/5` também muda ao fim de toda limpeza (não serve de aviso).

- **Backup do mapa**: `10/13` lista `backup_map_arr`; o objeto (`<uid>/<did>/8`) baixa e decifra no mesmo formato do mapa atual
  (cômodos, paredes virtuais, móveis, mas sem caminho). A restauração (`ação 10/8 restore-map`) é destrutiva: não implementada.
- **Trajetória** (`10/2`, objeto `…/1`) devolve 404 fora de uma limpeza; o mapa carrega só o caminho da limpeza atual/última (`paths.points`).
  Mapa de tapetes (`10/7`) vem vazio quando não há tapete mapeado.
- **Nuvem, leitura**: `datasource` 2 consulta o robô em tempo real; 1 e 3 devolvem o cache (o robô empurra as mudanças, então costuma estar
  atual; só há exceção em props que ele não notifica). `device_list` traz `token` e `localip` de cada aparelho (e coordenadas/IP público: não repassar).
- **Escrita e ações pela nuvem** (`/miotspec/prop/set`, `/miotspec/action`) funcionam com a mesma sessão (gravar o valor atual e uma ação `get-*` deram `code 0`).

## 6. Histórico do robô

- `10/3` pela nuvem: lista **duplicada** (cada registro aparece 2×) e **limitada a 40 itens (~20 limpezas)**; `total_count`
  conta uma que já saiu da lista. `label` = `<duração s>_<área m²×1000>_<tipo>_<?>_<?>`.
- Por isso o app **guarda o próprio histórico** (derivado do `2/17`+`2/6`+`2/7`): bateu com a nuvem nas 7 limpezas comparadas.

## 7. Conta Xiaomi

- Login por **QR code** (`longPolling/loginUrl`) serve a contas Google/Apple; a sessão (`ssecurity`, `serviceToken`) assina
  chamadas RC4 em `https://<país>.api.io.mi.com/app/…` (contas brasileiras costumam estar em `us`).
- `/home/device_list` devolve **token e IP local** de cada aparelho (base do "token automático"), mas também
  coordenadas e IP público: nunca repassar ao navegador.

## 8. Ainda desconhecido

- Disparo nativo de rotinas por zona (ação `2/37` `start-zone-sweep`, formato do `piid 12`) e de rotinas personalizadas (`2/43` fica 0).
- Escrita das configurações por cômodo (ação `2/13`, `piid 16`); o formato provável é o `room_attrs` do mapa.
- Significado do serviço `21`, dos tipos de móvel além dos três vistos e dos campos 4–5 do `label`.
