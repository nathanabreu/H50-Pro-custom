# Roteiro de testes antes de publicar

Ordem pensada para **achar problemas cedo e com pouco risco**: primeiro o que só lê, depois o que escreve configuração, por fim o
que move o robô. Marque cada item e anote o que fugir do esperado (a mensagem da tela ou a linha do log ajuda muito).

## 0. Preparação (2 min)
- [ ] Feche qualquer H50 Console que esteja rodando.
- [ ] Copie a pasta `data\` para **`data-antes`** (nome que o `.gitignore` já ignora; qualquer `data-*` serve). É o seu seguro: tem tokens, banco e a sessão da nuvem. **Nunca** commite essa pasta.
- [ ] Abra um terminal na pasta do projeto: `cd C:\claude_local\xiaomi`.

## 1. Subir e primeiro acesso (5 min)
`py -m h50console`
- [ ] O log mostra "robôs: H50 Pro (auto)" e **PRIMEIRO ACESSO … código XXXX-XXXX**.
- [ ] Abra http://127.0.0.1:8050 → vai para a tela de **criar senha**. Use o código e crie a senha (mín. 8).
- [ ] Entrou no painel. Em **Robôs** o robô aparece "ativo", **via rede local**, IP certo. Renomeie para "Rex" (clique no nome).
- [ ] Feche e abra de novo o app: pede a **senha** (e não o código).
- [ ] A pasta `data\` ganhou `robots.json`, `app.json`, `secret.key`. O banco antigo foi reaproveitado (Histórico tem as limpezas).

## 2. Só leitura (10 min)
- [ ] **Início**: chips de status/bateria batem com o app oficial; mapa aparece com cômodos, paredes virtuais e móveis.
- [ ] **Dashboards**, **Histórico**, **Consumíveis**: carregam, sem erros na tela.
- [ ] **Robôs → Testar**: rede local e nuvem "ok". **Achar pelo DID**: confirma o IP.
- [ ] **Laboratório → Nuvem**: lista mapa atual, backup do mapa (botão **Ver** desenha), trajetória 404 (esperado fora de limpeza).
- [ ] **Manutenção**: espaço, linhas por robô, log do app com mensagens.

## 3. Mudanças que **não** movem o robô (10 min)
- [ ] No **app oficial**, mude um ajuste (ex.: volume). No nosso, em **Configurações**, o valor muda em até ~30 s sem recarregar.
- [ ] No **nosso** app, mude esse ajuste de volta. O app oficial mostra a mudança.
- [ ] **Laboratório → Mudanças**: escreva "mudei X no app oficial", faça uma mudança lá e veja a propriedade aparecer depois da anotação.
- [ ] **Início → Modos**: troque a sucção, confirme, e confira no app oficial. Volte ao valor original.

## 4. Transporte pela nuvem (5 min)
- [ ] **Robôs → Editar → "Só nuvem"**: Início passa a mostrar **via nuvem**, atualizando mais devagar. Volte para **Automático**.
- [ ] (Opcional) Desligue o Wi-Fi do PC por 1 min: com **Automático**, o estado deve continuar vindo (via nuvem) e voltar à rede local depois.

## 5. Notificações (5 min)
- [ ] Instale o app **ntfy** no celular, inscreva-se num tópico difícil de adivinhar.
- [ ] **Configurações → Notificações → Adicionar canal** (ntfy, endereço `https://ntfy.sh/SEU-TOPICO`) → **Testar**: chega no celular.

## 6. Backup e restauração **numa cópia** (10 min)
- [ ] **Manutenção → Baixar backup** (senha de 8+ caracteres). Abra o arquivo no Bloco de Notas: tem de parecer lixo (cifrado).
- [ ] Restaure sem mexer nos dados reais:
  ```
  set H50_DATA_DIR=data-teste
  set H50_BACKUP_PASSPHRASE=a-senha-do-backup
  py -m h50console restore C:\caminho\do\arquivo.h50bak
  py -m h50console            (abre com os dados restaurados; pede a senha do backup)
  ```
- [ ] Senha errada no `restore` dá "senha incorreta ou arquivo corrompido" e não grava nada.

## 7. Acesso de outro aparelho e celular (15 min)
- [ ] Pare o app e suba com `set H50_HOST=0.0.0.0` → `py -m h50console`. No celular (mesmo Wi-Fi): `http://IP-DO-PC:8050` pede a senha.
- [ ] Errar a senha 5 vezes bloqueia por um tempo ("muitas tentativas").
- [ ] Para **instalar como app** o endereço precisa de HTTPS: use Tailscale (`docs/DEPLOY.md` §6) e "Adicionar à tela inicial".
- [ ] Se o Windows pedir permissão de firewall, permita **só em rede privada**.

## 8. Limpeza de verdade, supervisionada (15 min)
- [ ] **Início**: escolha **um cômodo pequeno** na Área → **Iniciar limpeza** (pede confirmação). O robô sai.
- [ ] O mapa mostra o robô e a **trajetória** se atualizando; os chips mostram progresso, área e tempo.
- [ ] Ao terminar: aparece no **Histórico** (fonte "app", depois "robô (nuvem)") e chega a notificação **Limpeza concluída**.
- [ ] Pausar, continuar e **Voltar à base** funcionam; com a base lavando o mop, **Iniciar** fica bloqueado com o motivo.

## 9. Por último: limpeza por zona (só com você ao lado)
- [ ] Robô carregado na base, caminho livre. `py tools\zone_probe.py` (só simula) e depois `py tools\zone_probe.py --yes`.
- [ ] Se algum formato funcionar, a sonda manda o robô voltar e diz qual foi. Me passe a saída.

## 10. Novidades para conferir (sem mexer no robô)
- [ ] **Perfil somente leitura**: Configurações → Perfil somente leitura → definir senha. Numa aba anônima entre com essa senha:
  só aparecem Início, Dashboards, Histórico, Consumíveis e Configurações (sem Estação/Iniciar/Área); tentar mudar algo não é possível.
  Entre de volta como administrador e use **Desligar**: a sessão do visualizador cai.
- [ ] **Acessos ao painel** (Manutenção): aparecem seus logins; erre a senha de propósito e veja o registro "falhou" com o IP.
- [ ] **Caminho percorrido**: faça uma limpeza curta com o app aberto e a conta Xiaomi conectada. Ao terminar (cerca de 1 min depois)
  o Histórico mostra **Ver caminho** nessa limpeza. Limpezas antigas não têm caminho.
- [ ] **Cobertura** (Dashboards): depois de 1 ou mais limpezas com caminho, o mapa mostra onde o robô passou.
- [ ] **Previsão de troca** (Consumíveis): aparece depois de alguns dias de dados (precisa de 2 dias ou mais de desgaste).
- [ ] **Métricas**: `set H50_METRICS_TOKEN=um-valor-longo` e abra `curl -H "Authorization: Bearer um-valor-longo" http://127.0.0.1:8050/metrics`.
- [ ] **Notificação "parado"**: marque o evento em Notificações; pause o robô por 30 min e confira o aviso.

- [ ] **Editor de mapa (rascunho)**: Início → Editar mapa. Desenhe uma parede (2 toques), coloque um móvel, apague, desfaça. Confira que o robô
  e o app oficial **não mudam nada**. "Fazer backup do mapa" cria um arquivo em `data
obots\<id>\mapackups`. O móvel antes chamado "Cama" agora é "Mesa".

- [ ] **MCP**: com o painel rodando, `set H50_MCP_PASSWORD=<senha do perfil somente leitura>` e adicione o servidor no seu assistente
  (README, "Usar com um assistente de IA"). Peça "como está o robô?" (funciona) e "mande voltar à base" (recusa: só leitura). Depois com a senha de
  administrador: "mande voltar à base" deve **pedir confirmação** antes de executar.

## O que me mandar quando algo falhar
O texto exato do erro (tela ou toast), em qual passo, e as últimas linhas de **Manutenção → Log do app**.
Se for dúvida de segurança ou algo estranho no robô, **Manutenção → Pacote de diagnóstico** (não tem token, DID nem IP completo).
