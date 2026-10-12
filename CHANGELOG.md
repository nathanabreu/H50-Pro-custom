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
