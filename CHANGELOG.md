# Changelog

## 0.1.0 (em desenvolvimento)

- Transporte miIO/MIoT próprio (AES em Python puro) e leitura em lotes que respeitam o limite de ~1,4 KB do robô.
- Transportes: rede local, nuvem Xiaomi e automático (rede local, com a nuvem de reserva).
- Vários robôs: cadastro com token automático pela conta, achar o robô pelo DID sem depender do IP, editar, testar, remover.
- Painel no formato do app Xiaomi Home, mapa decifrado localmente, dashboards, histórico completo, consumíveis.
- Autenticação (primeiro acesso por código no console, sessão, CSRF, CSP), PWA.
- Manutenção: retenção, otimização, backup/restauração criptografados e CLI, logs, pacote de diagnóstico, CSV.
- Laboratório: propriedades, mudanças com anotações, varredura, ações por risco, objetos da nuvem.
- Notificações: ntfy, Telegram e webhook.
- Implantação: Docker, systemd, tarefa agendada do Windows, exemplo de Caddy.
- Histórico: caminho percorrido em cada limpeza (gravado durante a limpeza; botão "Ver caminho").
- Segurança: limite de tamanho do corpo JSON, `Content-Length` inválido recusado, validação do cabeçalho Host em localhost
  (contra DNS rebinding; `H50_ALLOWED_HOSTS`), cabeçalhos COOP/CORP/Permissions-Policy/HSTS, limite de tentativas também na troca
  de senha, teto da tabela de IPs e registro de acessos (aba Manutenção).
- Perfil somente leitura: segunda senha (Configurações ou `H50_VIEWER_PASSWORD`) que só consulta; o servidor recusa comandos, ajustes, cadastro, backup, manutenção e Laboratório.
- Dashboards: mapa de calor de cobertura (em quantas limpezas o robô passou por cada trecho). Consumíveis: previsão de troca pelo ritmo de desgaste.
- Métricas Prometheus em `GET /metrics` (`H50_METRICS_TOKEN` ou sessão).
- Acessibilidade: foco visível, link "pular para o conteúdo", `aria-live` nos avisos, rótulo no mapa, respeita "reduzir movimento".
- Servidor: limite de 32 conexões de eventos (SSE) simultâneas; recusas antecipadas descartam o corpo pendente (evita resposta perdida).
- Notificações: aviso de robô parado/pausado fora da base por 30 min (ou limpando há mais de 3 h). Sessão da nuvem gravada com permissão 0600.
