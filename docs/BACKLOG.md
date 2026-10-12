# Backlog

Prioridade de cima para baixo dentro de cada bloco. `[ ]` pendente · `[~]` em andamento · `[x]` feito.

## Pedidos do usuário (fila)

- [ ] **Histórico: ver o caminho que o robô percorreu em cada limpeza.**
  - O que já se sabe: o arquivo do mapa (nuvem) traz `paths.points` com a trajetória (`[{x, y, type}]`, tipo 1 = limpando,
    0 = deslocamento), mas **só da limpeza atual ou da última**. O objeto de trajetória (`10/2`) devolveu 404 fora de uma limpeza.
  - Consequência: limpezas **passadas não têm caminho recuperável**; só vale daqui para a frente.
  - Desenho: ao detectar o fim de uma limpeza (evento `cleaning`), baixar o mapa e gravar o `paths.points` em uma tabela
    `cleaning_path (stime, points, map_ref)` (compactado com zlib; ~1 KB por limpeza); durante a limpeza, guardar também
    o caminho parcial a cada nova versão do mapa (o `10/1` muda a cada ~1 min), para não perder se o app cair.
  - Tela: no Histórico, linha expansível ou botão "Ver caminho" que desenha o mapa (o do momento) com a trajetória
    daquela limpeza; sobrepor várias limpezas num mapa de calor de cobertura por cômodo.
  - Entra no backup e no CSV/JSON de exportação.

## Em andamento

- [x] Laboratório (propriedades, mudanças com anotações, varredura, ações por risco, objetos da nuvem)
- [x] Notificações (ntfy / Telegram / webhook)
- [x] PWA (instalar no celular) e deploy (Docker, systemd, tarefa do Windows); Docker e systemd sem teste em máquina real
- [x] README e `.env.example` atualizados para frota, senha e backup

## Precisa de teste supervisionado no robô (move o robô ou altera a configuração salva)

- [ ] Disparo de rotinas por **zona** (ação `2/37 start-zone-sweep`, formato do `piid 12`) e desenhar uma zona no mapa. **Sonda pronta**: `py tools/zone_probe.py` (simula) e `--yes` (move o robô, com você por perto)
- [ ] **Ajustes por cômodo** (sucção, água, passadas): a leitura já aparece na seleção de Área; escrita pela ação `2/13`
  (`piid 16`, provavelmente o `room_attrs` inteiro). Risco: sobrescrever nomes de cômodos; testar com backup do mapa.
- [ ] **Agenda editável** (ações `2/23–2/25`)
- [ ] Rotinas personalizadas sem cômodos (disparo nativo; `2/43` fica 0)

## Pesquisa

- [ ] Significado do serviço `21` (21/1–21/8) e das props `2/103–2/106`, `20/4`
- [ ] Tipos de móvel além de 1220 (sofá), 1400 (cama), 1740 (liteira); campos 4–5 do `label` do histórico
- [ ] Mapa de tapetes (`10/7`, vazio no momento) e objeto de trajetória (`10/2`) durante uma limpeza
- [ ] Outros modelos da família `ov` (S40, 5C): carregar a spec do modelo sob demanda (miot-spec.org)

## Ideias

- [ ] Perfil só leitura (visualizador) além do administrador
- [ ] Métricas Prometheus (`/metrics`) e integração MQTT / Home Assistant
- [ ] Web Push no celular (opcional, exige a biblioteca `cryptography`; alternativa sem dependência: ntfy)
- [ ] Fixtures **sintéticas** para o CI público (sem planta da casa nem identificadores)
- [ ] Imagem Docker publicada (GHCR) e `pip install h50console`
- [x] Licença: MIT
- [ ] Publicação a partir de histórico limpo (ver `docs/ARQUITETURA.md` §6) e fixtures sintéticas
