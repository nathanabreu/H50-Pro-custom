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

## O que me mandar quando algo falhar
O texto exato do erro (tela ou toast), em qual passo, e as últimas linhas de **Manutenção → Log do app**.
Se for dúvida de segurança ou algo estranho no robô, **Manutenção → Pacote de diagnóstico** (não tem token, DID nem IP completo).
