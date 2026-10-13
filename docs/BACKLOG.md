# Backlog

Prioridade de cima para baixo dentro de cada bloco. `[ ]` pendente · `[~]` em andamento · `[x]` feito.

## Pedidos do usuário (fila)

- [x] **Histórico: ver o caminho que o robô percorreu em cada limpeza.** Feito em `h50console/paths.py`: durante a limpeza
  baixa o mapa (no máximo a cada 45 s) e guarda os pontos; ao fim (60 s depois) grava o caminho final sob o início oficial (2/17).
  Tabela `cleaning_path` (migração v3), `GET /api/history/path?stime=`, botão "Ver caminho" no Histórico. Só vale para
  limpezas **futuras**, feitas com o app aberto e a conta da nuvem conectada (o robô não guarda caminhos antigos).
  - [x] Mapa de calor de cobertura juntando várias limpezas (Dashboards → Cobertura).

- [x] **Servidor MCP: conectar e gerenciar o robô a partir de um assistente de IA (Claude etc.).** Feito em `h50console/mcp.py` (`python -m h50console mcp`, stdio, só biblioteca padrão): 7 ferramentas de leitura e 3 de comando, tudo via API HTTP do app; comandos exigem `confirm: true`. Falta: token de API próprio (hoje usa a senha do painel), transporte HTTP/SSE para uso remoto, `openapi.json`. Desenho original abaixo.
  - Ideia: expor o H50 Console como servidor MCP (Model Context Protocol), para o usuário pedir em linguagem natural
    "como está o robô?", "limpe a cozinha", "o que mudou nos ajustes?", "quando troco a escova?".
  - Desenho provável: processo `py -m h50console mcp` (stdio) que fala com a API HTTP do app já em execução (mesma senha/cookie ou
    um token de API próprio), sem tocar direto no robô nem na nuvem: assim reaproveita fila de prioridade, bloqueios de segurança
    (`start_block_reason`), registro de comandos e o perfil somente leitura.
  - Ferramentas (mínimo, só biblioteca padrão com JSON-RPC sobre stdio): `robots_list`, `robot_state`, `consumables`,
    `history`/`history_path`, `settings_get`; e, só com perfil de administrador, `clean_rooms`, `clean_custom`, `action`
    (parar/voltar à base/pausar), `setting_set`. Ações que movem o robô pedem confirmação explícita no próprio pedido.
  - Segurança: token de API separado (revogável, escopo leitura ou administração), nunca expor token do robô nem sessão da nuvem;
    registrar no log de acessos; limitar a localhost por padrão; transporte HTTP (SSE) opcional para uso remoto atrás do túnel.
  - Também vale um `GET /api/openapi.json` simples para outras integrações.

- [ ] **Edição do mapa pelo app: móveis, paredes/barreiras virtuais, zonas proibidas e afins.**
  - **Estruturado (rascunho, sem gravar no robô)**: `h50console/mapedit.py` (operações validadas: parede virtual, móvel,
    renomear cômodo; sempre devolve cópia e lista as mudanças), `POST /api/map/edit/preview`, `POST /api/map/backup` (+ `GET /api/map/backups`,
    guarda os 20 últimos), `POST /api/map/edit/save` (responde 501) e o editor "Editar mapa (rascunho)" no Início (desenhar parede em
    2 toques, colocar móvel, apagar, desfazer). Tipo 1400 é **mesa** (confirmado pelo dono), não cama.
  - **Falta** (precisa do robô): descobrir como gravar (ação `2/13`? objeto na nuvem?), zonas proibidas/de limpeza e tapetes
    (formato desconhecido), juntar/dividir cômodos, mover/girar móvel com o dedo, restaurar um backup no robô.
  - Hoje o app só LÊ (móveis em `2/102` e no mapa `furniture`; paredes em `fb_walls`; cômodos em `room_attrs`).
    A edição acontece no app oficial, e o aviso de mapa editado chega por `10/13`.
  - Escopo desejado: adicionar, mover, redimensionar e remover **móveis** (sofá, cama, liteira e outros tipos);
    desenhar e apagar **paredes virtuais** e **zonas proibidas** (sem aspirar / sem passar pano / sem subir em tapete);
    **zonas de limpeza**; renomear, juntar e dividir **cômodos**; marcar **tapetes**; ajustes por cômodo (sucção, água, passadas).
  - Tela: editor sobre o canvas do mapa (selecionar, arrastar, girar, desenhar com cliques; desfazer; "salvar no robô").
  - Pesquisa/risco: descobrir o formato de escrita (provável: ação `2/13` com o `room_attrs` inteiro, ou objeto do mapa na nuvem).
    Um erro pode **apagar nomes de cômodos ou o mapa**. Obrigatório: backup do mapa (`10/13`) antes de qualquer escrita, pré-visualização
    do que muda, botão de restaurar o último backup e testes supervisionados com o robô na base.
  - Só para administrador (o perfil somente leitura nunca edita); registrar cada edição no log de comandos.

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
- [ ] Tipos de móvel além de 1220 (sofá), 1400 (mesa), 1740 (liteira) (o editor aceita qualquer número de tipo); campos 4–5 do `label` do histórico
- [ ] Mapa de tapetes (`10/7`, vazio no momento) e objeto de trajetória (`10/2`) durante uma limpeza
- [ ] Outros modelos da família `ov` (S40, 5C): carregar a spec do modelo sob demanda (miot-spec.org)

## Ideias

- [x] Perfil só leitura (visualizador) além do administrador
- [x] Métricas Prometheus (`/metrics`)
- [ ] Integração MQTT / Home Assistant
- [ ] Web Push no celular (opcional, exige a biblioteca `cryptography`; alternativa sem dependência: ntfy)
- [x] Fixtures **sintéticas** para o CI público (sem planta da casa nem identificadores)
- [ ] Imagem Docker publicada (GHCR) e `pip install h50console`
- [x] Licença: MIT
- [ ] Publicação a partir de histórico limpo (ver `docs/ARQUITETURA.md` §6) e fixtures sintéticas
