# RalseiBot

Bot de Discord em Python/Nextcord com comandos `r.` e `/`, economia global em DarkMoney, ranking em imagem e jogos de aposta com moedas virtuais.

## Iniciar

Requer Python 3.12 ou superior.

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
# Configure DISCORD_TOKEN no arquivo .env (veja .env.example).
.\.venv\Scripts\python main.py
```

No Discord Developer Portal, habilite **Message Content Intent** e **Server Members Intent** para os comandos com prefixo. Em **OAuth2 → URL Generator**, selecione os escopos **bot** e **applications.commands** e use o link gerado para adicionar ou reautorizar o bot no servidor. O bot precisa de View Channel, Send Messages, Embed Links e Attach Files nos canais em que será usado; os jogadores precisam de **Use Application Commands** para usar `/`.

Reinicie o bot depois de atualizar os arquivos. O Nextcord registra e atualiza os comandos slash globais automaticamente ao conectar, sem comando manual de sincronização. A lista pode levar algum tempo para aparecer no Discord. `r.help` e `/help` listam os dois formatos; `r.help mines` e `/help command:mines` mostram a ajuda de um jogo.

## Comandos

| Prefixo | Slash | Função |
| --- | --- | --- |
| `r.help [comando]` | `/help [command]` | Lista os comandos ou mostra a ajuda de um deles |
| `r.ping` | `/ping` | Verifica se o bot está online |
| `r.ban @membro [motivo]` | `/ban member:@membro [reason]` | Bane um membro sem apagar suas mensagens; alias: `banir` |
| `r.unban ID [motivo]` | `/unban user_id:ID [reason]` | Remove um banimento pelo ID; alias: `desbanir` |
| `r.kick @membro [motivo]` | `/kick member:@membro [reason]` | Expulsa um membro; alias: `expulsar` |
| `r.mute @membro 10m [motivo]` | `/mute member:@membro duration:10m [reason]` | Aplica timeout temporário; aliases: `timeout`, `silenciar` |
| `r.unmute @membro [motivo]` | `/unmute member:@membro [reason]` | Remove o timeout; alias: `desmutar` |
| `r.lock [#canal] [motivo]` | `/lock [channel] [reason]` | Bloqueia mensagens e tópicos para @everyone; alias: `trancar` |
| `r.unlock [#canal] [motivo]` | `/unlock [channel] [reason]` | Restaura as permissões anteriores ao lock; alias: `destrancar` |
| `r.clear 10` | `/clear amount:10` | Exclui até 100 mensagens anteriores ao comando; aliases: `limpar`, `purge` |
| `r.slowmode 10 [#canal] [motivo]` | `/slowmode seconds:10 [channel] [reason]` | Define o modo lento em segundos; 0 desativa; alias: `modolento` |
| `r.balance` | `/balance` | Saldo; aliases: `saldo`, `atm`, `bal` |
| `r.daily` | `/daily` | Recompensa de 5.000–100.000 moedas uma vez por dia; renova às 00:00 GMT-3, persistente |
| `r.missions [claim]` | `/missions [action:view/claim]` | Veja as missões diárias ou resgate todos os bônus concluídos; aliases: `mission`, `missoes`, `missões` |
| `r.work` | `/work` | Ganha 10.000–40.000 moedas; intervalo de 2h; somente em servidores |
| `r.freelance` | `/freelance` | Ganha 100–10.000 moedas; intervalo de 10min; aliases: `freelancer`, `freelas`, `frelas` |
| `r.rob @membro` | `/rob member:@membro` | Tenta roubar DarkMoney de outro membro; intervalo de 1h |
| `r.pay @membro 100` | `/pay member:@membro amount:100` | Transfere moedas após as duas pessoas clicarem em Aceitar; qualquer uma pode cancelar e o pedido expira após 2 minutos sem interação; aceita `K` (mil) e `M` (milhão), como `1.5k` ou `2M`; aliases: `transferir`, `pix`, `pagar` |
| `r.addbalance @membro 100` | `/addbalance member:@membro amount:100` | Adiciona moedas; somente administradores |
| `r.setbalance @membro 100` | `/setbalance member:@membro amount:100` | Define o saldo disponível; somente administradores |
| `r.resetbalance @membro` | `/resetbalance member:@membro` | Zera o saldo disponível; somente administradores |
| `r.activity Seu texto aqui` | `/activity text:Seu texto aqui` | Atividade personalizada por 5 minutos; somente administradores; aliases: `atividade`, `status`. Use `reset` para retomar a rotação |
| `r.ticket Categoria` | `/ticket category:Categoria` | Publica um painel que cria tickets privados numerados; somente administradores |
| `r.quiz #chat #revisao [premio]` | `/quiz channel:#chat review_channel:#revisao [reward]` | Ativa o quiz automático e publica o painel de sugestões; somente administradores |
| `r.quizpanel` | `/quizpanel` | Publica outro painel de sugestões; somente administradores |
| `r.quizoff` | `/quizoff` | Desativa o quiz e cancela a rodada atual; somente administradores |
| `r.confess #confissões #logs-privados` | `/confess channel:#confissões log_channel:#logs-privados` | Configura e publica um painel de confissões anônimas com imagem opcional e registro do autor para a equipe; somente administradores |
| `r.close` | `/close` | Fecha o ticket atual e exclui seu canal; somente o dono ou quem tem Gerenciar Canais; aliases: `fechar`, `closeticket` |
| `r.rich [página]` | `/rich [page]` | PNG com 10 jogadores, posições, nomes e saldos; aliases: `richlist`, `leaderboard`, `top`, `rank` |
| `r.profile [@usuário]` | `/profile view [member]` | Perfil em imagem com avatar, nome, ID, ranking, saldo, fundo e Sobre mim; alias: `perfil` |
| `r.profile color #77E5BC` | `/profile color value:#77E5BC` | Cor dos painéis do seu perfil em hexadecimal; alias: `cor` |
| `r.profile about Seu texto aqui` | `/profile about text:Seu texto aqui` | Altera o Sobre mim (até 300 caracteres); aliases: `sobremim`, `bio` |
| `r.profile background` + imagem anexada | `/profile background image:arquivo` | Salva o fundo personalizado; alias: `fundo` |
| `r.marry @membro` | `/marry member:@membro` | Pedido de casamento com confirmação das duas pessoas por botões; aliases: `casar`, `propose` |
| `r.ship @usuário [@outro]` | `/ship first:@usuário [second:@outro]` | Imagem com os dois avatares e uma porcentagem aleatória fixa para o par; alias: `shippar` |
| `r.marriage [@usuário]` | `/marriage [member]` | Embed com o casal, data do casamento e tempo juntos; aliases: `casamento`, `married` |
| `r.kiss @membro` | `/kiss member:@membro` | Beija alguém com GIF; alias: `beijar` |
| `r.hug @membro` | `/hug member:@membro` | Abraça alguém com GIF; alias: `abracar` |
| `r.pat @membro` | `/pat member:@membro` | Faz carinho em alguém com GIF; alias: `carinho` |
| `r.slots 100` | `/slots amount:100` | Caça-níqueis; aliases: `slot`, `slotmachine` |
| `r.blackjack 100` | `/blackjack amount:100` | Blackjack com botões; aliases: `bj`, `21` |
| `r.poker [entrada]` | `/poker [amount]` | Texas Hold’em com Ralsei; 1 pessoa joga com 4 bots, ou 2–6 pessoas jogam entre si; alias: `holdem` |
| `r.mines 100 [bombas]` | `/mines amount:100 [mine_count]` | Escolha 1–15 bombas no menu ou informe a quantidade. Tabuleiro 4×4; alias: `minas` |
| `r.six iniciar` ou `r.uno` | `/six iniciar` | Uno em tópicos públicos, com 2–20 pessoas, mãos privadas, regras configuráveis e apostas opcionais |

Nos comandos slash, preencha os campos que o Discord oferece; os itens entre colchetes são opcionais. O Discord exige um subcomando em grupos, então visualizar o perfil usa `/profile view`. Todos os aliases da tabela continuam disponíveis com `r.`. Os dois formatos executam os mesmos comandos, com as mesmas permissões, conversores, saldos e cooldowns; alternar entre prefixo e slash não permite repetir uma recompensa ou evitar o intervalo. Os comandos administrativos de economia alteram apenas o saldo disponível; apostas já iniciadas continuam com sua liquidação normal.

O ranking é global entre todos os usuários registrados e mostra o saldo disponível, sem apostas em andamento. Empates são ordenados pelo ID do usuário. Nomes vêm do cache do Discord, com ID como alternativa. A imagem é desenhada localmente com Pillow, sem serviços de geração ou downloads de avatares.

## Administração e moderação

Os comandos de moderação funcionam somente em servidores, com as mesmas verificações em `r.` e `/`. Administradores podem usá-los; moderadores precisam das permissões correspondentes. O bot também precisa dessas permissões:

| Comandos | Permissões necessárias |
| --- | --- |
| `ban`, `unban` | Banir Membros |
| `kick` | Expulsar Membros |
| `mute`, `unmute` | Moderar Membros |
| `lock`, `unlock` | Ver Canal, Gerenciar Canais e Gerenciar Cargos no canal escolhido |
| `clear` | Ver Canal, Gerenciar Mensagens e Ler Histórico de Mensagens no canal atual |
| `slowmode` | Ver Canal e Gerenciar Canais no canal escolhido |

O cargo mais alto do moderador e o do bot precisam estar acima do cargo do alvo. O dono do servidor dispensa a comparação do próprio cargo, mas o bot continua sujeito à hierarquia. Não é possível punir a si mesmo, o próprio bot ou o dono. O motivo é opcional, aceita até 400 caracteres e acompanha o ID do moderador no log de auditoria de ban, unban, kick, mute, unmute, lock, unlock e slowmode.

`mute` usa o timeout nativo do Discord, que expira automaticamente mesmo com o bot desligado. A duração aceita um número inteiro seguido de `s`, `m`, `h` ou `d`: `30s`, `10m`, `2h`, `7d`, de 1 segundo até 28 dias. Bots e administradores não podem receber timeout. `unmute` remove esse timeout; não altera cargos de silêncio de outros bots. `unban` usa o ID como texto para preservar todos os dígitos; ative o Modo Desenvolvedor no Discord para copiar o ID.

`lock` e `unlock` usam o canal atual quando nenhum é informado. O lock nega enviar mensagens, enviar em tópicos e criar tópicos públicos/privados na permissão de `@everyone`. **Administradores e cargos ou membros com permissões explícitas podem continuar enviando mensagens.** O canal continua com a mesma visibilidade. A tabela SQLite `channel_locks` salva os valores anteriores, incluindo permissões herdadas, antes da alteração; `unlock` os restaura mesmo após reiniciar, preservando outras permissões do canal. Locks repetidos não substituem o registro original. Sem um lock salvo, `unlock` não altera o canal. Se houver falha de comunicação durante um lock, use `unlock` para restaurar o estado salvo antes de tentar novamente. A alteração de permissões pode desvincular o canal da sincronização da categoria; o unlock restaura os valores salvos para `@everyone`.

`clear` exclui de 1 a 100 mensagens anteriores à execução, sem incluir a mensagem do comando, sua resposta ou mensagens posteriores. A resposta informa a quantidade efetivamente excluída. Mensagens antigas são tratadas pelo Nextcord com exclusão individual quando necessário. `slowmode` aceita de 0 a 21600 segundos (6 horas). Os comandos de canal aceitam canais de texto; não aceitam tópicos, voz ou fóruns. Para informar motivo no prefixo de `lock`, `unlock` ou `slowmode`, inclua o `#canal` antes do motivo.

Os testes em `test/test_moderation.py` verificam permissões de usuário e bot, hierarquia, duração de timeout, ações e motivos, restauração persistente do lock, concorrência, falhas do Discord, limites de limpeza/modo lento e execução das opções slash, sem login no Discord.

Referência: [permissões e operações de canais no Nextcord](https://docs.nextcord.dev/en/v3.0.1/api.html#nextcord.TextChannel.set_permissions).

## Poker / Texas Hold’em

Use **`r.poker 1000`**, **`r.holdem 1k`** ou **`/poker amount:1000`** em um servidor. A entrada padrão é **1.000 D$**, com mínimo de **20 D$**; aceita números inteiros e sufixos `K`/`M`. O lobby fica aberto por **5 minutos**. **Entrar** aceita o valor exibido; **Sair** remove sua participação antes da partida. Se o anfitrião sair, a próxima pessoa assume. Só o anfitrião pode **Começar** ou **Cancelar** o lobby.

Ao começar com **uma pessoa**, entram **Kris, Susie, Lancer e Noelle**, quatro bots controlados pelo jogo. Com **2–6 pessoas**, a partida acontece apenas entre os participantes. **Ralsei é sempre o dealer**, representado pela **foto de perfil atual do bot no Discord**. A imagem pública usa a mesa fornecida em `assets/poker/table.png` e as 52 cartas de `assets/cards`, com nomes como `ace_of_spades.png` e `10_of_hearts.png`. Mantenha esses assets disponíveis ao copiar ou implantar o projeto.

Cada partida joga **uma mão completa de No Limit Texas Hold’em**. Todos começam com o mesmo valor de fichas. O small blind é `max(1, entrada // 100)` e o big blind é o dobro; o botão é sorteado. São distribuídas duas cartas privadas por pessoa, seguidas de pré-flop, flop, turn e river. **Ver minhas cartas** mostra as cartas em uma mensagem privada, inclusive ao usar o prefixo. A mesa pública só revela as mãos que chegaram ao showdown. Mãos descartadas e vitórias por desistência preservam as cartas privadas.

Use **Mesa (check)**, **Pagar**, **Aumentar**, **All-in** ou **Desistir (fold)**. No formulário de aumento, informe o **total que deseja colocar naquela rodada**, incluindo o que já pagou. Aumentos mínimos, all-ins curtos, reabertura das apostas, potes laterais e empates são tratados pelo motor do jogo. O melhor conjunto de cinco cartas vence, podendo usar ambas, uma ou nenhuma das cartas privadas. Sobras de divisão são entregues aos vencedores na ordem após o botão. Referência das regras: [Texas Hold’em](https://www.pokerstars.com/poker/games/texas-holdem/) e [apostas e potes laterais](https://www.pokerstars.com/help/articles/poker-rules-master/).

Cada pessoa tem **60 segundos por jogada**. Ao esgotar o prazo, passa se não houver aposta pendente; caso contrário, desiste. Consultar as cartas ou abrir o formulário de aumento não renova o prazo. Os bots decidem usando suas próprias cartas e informações públicas, sem acesso às cartas privadas dos adversários.

A entrada inteira é reservada ao começar; os débitos de todos os participantes acontecem em uma única transação. Se alguém não tiver saldo, ninguém é cobrado. **A entrada é o limite que você pode perder naquela mão.** Ao terminar, as fichas restantes mais os potes ganhos são creditados em D$, sem taxa, uma única vez. No solo, a casa fornece as fichas dos quatro bots; eles não criam contas no ranking. Os resultados dos bots não são creditados a usuários do Discord.

Cada pessoa ocupa uma mesa de poker por vez. Durante a mão, a reserva também impede apostas nos outros jogos. As tabelas `poker_games` e `bets` guardam entradas e recibos; cartas e turnos ficam na memória. Reiniciar ou recarregar o bot, excluir a mensagem/canal da mesa ou uma falha que interrompa a partida devolve as entradas pendentes. Resultados já pagos permanecem pagos. Uma mão iniciada não pode ser cancelada pelo anfitrião. Para jogar outra, abra uma nova mesa com `/poker` ou `r.poker`.

## Uno / Six

Use **`/six iniciar`**, **`r.six iniciar`** ou **`r.uno`** em um canal de texto. O painel lista as mesas desse canal; **Criar nova mesa** publica um convite e abre um **tópico público**. Todos que têm acesso ao canal podem acompanhar o tópico e entrar no lobby. O painel slash é privado; o painel por prefixo é público e seus controles pertencem a quem executou o comando. Convites e controles da mesa são compartilhados.

O lobby aceita **2–20 jogadores**. O anfitrião escolhe as regras, **1, 2 ou 3 vencedores** (sempre menos que a quantidade de jogadores) e a aposta: casual, **100, 1.000 ou 10.000 D$ por pessoa**. As opções começam em modo casual, um vencedor e desafio do +4 ativo. **Entrar** aceita as configurações exibidas. Se o anfitrião mudar regras, quantidade de vencedores ou aposta, os demais precisam clicar em **Entrar** novamente; nenhum dinheiro é debitado até **Começar**. Todos os débitos são realizados juntos, e saldo insuficiente de uma pessoa impede o início sem cobrar as outras.

O anfitrião também escolhe **Normal, Meme ou Overwatch** no seletor **Baralho da mesa**. Cada tema usa imagens próprias na mesa pública, nas mãos privadas e na confirmação da jogada. Essa escolha visual não exige novo aceite dos participantes e fica fixa quando a partida começa.

Somente o anfitrião começa a partida. **Sair** funciona no lobby; se o anfitrião sair, o próximo participante assume. O anfitrião pode cancelar o lobby. A equipe com **Gerenciar Mensagens**, **Gerenciar Tópicos** ou Administrador pode encerrar mesas pelo seletor do painel. Lobbies expiram após 15 minutos. Cada pessoa participa de uma mesa por vez; após começar, também fica impedida de apostar nos outros jogos até a partida acabar.

Cada jogador recebe **7 cartas**. A mesa pública mostra a carta do topo, a cor atual, a direção, a vez e a quantidade de cartas de cada pessoa. **Ver minha mão** envia uma imagem e menus que só o próprio jogador pode ver. Escolha a carta, revise a seleção e clique em **Jogar**; **Voltar** permite corrigir. Coringas abrem quatro botões de cor, e o 7 abre a escolha de outro jogador quando a regra de troca está ativa. Mãos grandes são divididas em páginas de até 25 cartas. Depois de mudanças na partida, uma seleção antiga é recusada e deve ser reaberta.

A cada **10 mensagens de pessoas no tópico**, o bot republica a mesa no final da conversa e remove a mensagem anterior, tanto no lobby quanto durante a partida. Mensagens de bots não entram na contagem. No início de cada turno, o jogador recebe uma **DM com sua menção e o link do tópico**; atualizar ou reposicionar a mesa no mesmo turno não repete o aviso. DMs bloqueadas não interrompem a partida.

- **Regras básicas:** mesma cor, número ou símbolo; bloquear pula uma pessoa e inverter muda a direção (com dois jogadores, joga novamente). Compre uma carta; se ela servir, jogue a carta recém-comprada ou passe. Se não servir, a vez passa automaticamente. Cada vez dura **60 segundos**; ao esgotar, compra 1 e passa, ou aceita a dívida inteira de +2/+4. Comprar não reinicia o prazo da vez.
- **Gritar Uno:** ao ficar com uma carta, o botão fica disponível durante **3 segundos**. Também é possível declarar Uno na confirmação, antes de jogar. Depois do prazo, outro jogador pode apertar **Pegar!** e aplicar +2, antes da próxima ação. Uma ação rápida não reduz os três segundos de declaração. Trocas de mãos exigem nova declaração de quem receber uma carta.
- **Desafiar +4:** é possível blefar mesmo tendo a cor atual. Se o desafio acertar, o autor compra 4 e quem desafiou mantém a vez. Se errar, quem desafiou compra a dívida +2 e perde a vez. Com o desafio desligado, o bot recusa +4 se houver carta da cor atual. Um +4 final aguarda a aceitação ou o desafio antes de definir a vitória.
- **Empilhar +2/+4:** qualquer +2 ou +4 pode responder a uma dívida, aumentando a compra para o próximo. Desafiar um +4 empilhado trata somente o último +4; se o blefe for confirmado, a dívida anterior continua pendente.
- **Jogar cartas repetidas:** permite jogar juntas cartas numéricas de mesmo valor; pelo menos uma precisa combinar com a mesa. Cartas de ação são jogadas individualmente. A confirmação mostra a ordem em que as cartas serão descartadas.
- **Comprar até jogar:** compra até encontrar uma carta utilizável; depois permite jogá-la ou passar. Se todas as cartas disponíveis estiverem nas mãos, a compra termina sem travar o jogo.
- **7–0:** o 7 troca sua mão com a de outra pessoa; o 0 gira todas as mãos na direção da rodada. A troca acontece antes de conferir a vitória: se a mão vazia for transferida, quem a receber termina. Vários 7 ou 0 juntos aplicam a troca uma vez.

O baralho tem 108 cartas, usando dois exemplares nas mesas com 16–20 jogadores para comportar as mãos iniciais. A abertura usa uma carta numérica. Quando o monte acaba, o descarte é embaralhado novamente, preservando o topo. A partida termina ao atingir a quantidade de vencedores escolhida. O pote é dividido integralmente entre eles, com as sobras entregues na ordem de chegada. A recompensa do diagrama foi integrada ao **DarkMoney**: **+30 D$ para o primeiro colocado e +5 D$ para cada participante que jogou até o fim**, incluindo o campeão.

As tabelas `uno_games` e `uno_players` guardam reservas e resultados no SQLite; pagamentos e reembolsos são feitos uma única vez, inclusive com cliques simultâneos. O estado das cartas e os botões ficam em memória. **Reiniciar ou recarregar o bot encerra as mesas; apostas pendentes são devolvidas e não há recompensa por partidas interrompidas.** Abra uma nova mesa depois do reinício. Remover o tópico ou encerrar pela equipe também cancela e devolve as apostas. Execute uma única instância por banco.

O baralho ilustrado ainda pode ser concluído separadamente: o jogo usa **cartas provisórias desenhadas localmente**, com cores, ações e visuais diferentes para cada tema. Coloque os PNGs finais em **`assets/uno/normal/`**, **`assets/uno/meme/`** e **`assets/uno/overwatch/`**, seguindo [os nomes das imagens](assets/uno/README.md). Cada arte disponível substitui sua carta provisória automaticamente; arquivos ausentes ou inválidos continuam usando a alternativa local do tema escolhido.

O bot precisa de **Ver Canal, Enviar Mensagens, Inserir Links, Anexar Arquivos, Ler Histórico de Mensagens, Criar Tópicos Públicos e Enviar Mensagens em Tópicos**. Os tópicos herdam a visibilidade do canal. Referências: [tópicos públicos no Nextcord](https://docs.nextcord.dev/en/stable/api.html#nextcord.Message.create_thread) e [respostas privadas de interações](https://docs.nextcord.dev/en/stable/interactions.html).

Os testes `test_uno_*.py` verificam regras e partidas completas simuladas, mãos privadas, botões, concorrência, apostas, cancelamento, recuperação e renderização sem conexão ao Discord.

## Quiz automático

Um administrador ativa o quiz e publica o painel de sugestões no canal em que executar:

```text
r.quiz #chat-geral #revisao-quiz 1000
/quiz channel:#chat-geral review_channel:#revisao-quiz reward:1000
```

O prêmio é opcional: **1.000 D$** por padrão, configurável entre 1 e 100.000 D$. Há um canal de quiz por servidor. O canal de revisão precisa ser diferente, com **Ver Canal negado para @everyone**; libere somente a equipe, pois as respostas aparecem ali. O bot precisa de **Ver Canal, Enviar Mensagens e Inserir Links** nos dois canais e no canal do painel.

A primeira pergunta pode aparecer após **30–60 minutos** da ativação. Cada publicação sorteia outro intervalo de 30–60 minutos. Quando o horário chega, o bot só publica se houver **pelo menos 5 mensagens de 2 pessoas nos últimos 10 minutos** no canal configurado. Mensagens de bots, webhooks, mensagens vazias e comandos `r.` não contam. Se o chat estiver parado, aguarda movimento; não acumula perguntas atrasadas. A verificação ocorre a cada 15 segundos.

Cada rodada dura **2 minutos**. Responda diretamente no chat: a primeira resposta correta processada ganha o prêmio no saldo global. Maiúsculas, acentos, espaços extras e pontuação simples nas extremidades são ignorados; é preciso responder apenas com a resposta ou uma das escritas aceitas, sem frases extras. Edições não contam. Sem acertos, o bot revela a resposta e não paga ninguém. O banco registra o vencedor e o crédito na mesma transação para impedir pagamentos duplicados, inclusive após reiniciar.

O bot já inclui 10 perguntas de matemática e português. O botão **Sugerir pergunta** abre um modal com pergunta, resposta correta e até 9 outras escritas aceitas, uma por linha. A sugestão vai para o canal de revisão com a identificação do autor. Quem tem **Gerenciar Mensagens** no servidor ou é administrador pode **Aprovar** ou **Recusar**. Somente sugestões aprovadas entram no sorteio daquele servidor. Cada pessoa pode manter até 3 sugestões pendentes e enviar uma por minuto.

Use **`r.quizpanel` ou `/quizpanel`** para publicar outro painel no canal atual. **`r.quizoff` ou `/quizoff`** desativa o quiz e cancela a rodada atual. Esses comandos são exclusivos de administradores. Executar `quiz` novamente reconfigura o canal/prêmio, cancela a rodada atual e reinicia o intervalo, preservando as perguntas aprovadas.

Configurações, sugestões, decisões, prêmios e rodadas ficam nas tabelas `quiz_configs`, `quiz_suggestions` e `quiz_rounds`, criadas automaticamente. Painéis e botões de revisão continuam funcionando após reiniciar. Uma rodada publicada mantém seu prazo original; o histórico de atividade começa vazio após reiniciar. Formulários abertos precisam ser reabertos após reiniciar e expiram em 10 minutos. Uma publicação interrompida antes de registrar o ID da mensagem é cancelada na inicialização; falhas de envio aguardam o próximo intervalo. Execute uma instância do bot por banco, como nos outros jogos.

## Confissões anônimas

Um administrador configura os canais e publica o painel com:

```text
r.confess #confissões #logs-privados
/confess channel:#confissões log_channel:#logs-privados
```

O canal de logs precisa ser diferente do canal de confissões, com **Ver Canal negado para @everyone**. Libere o acesso somente aos cargos ou membros da equipe; o administrador deve conferir essas permissões. O bot precisa de **Ver Canal, Enviar Mensagens, Inserir Links e Anexar Arquivos** nos dois canais. Nenhuma permissão de canal é alterada pelo comando.

Qualquer membro com acesso ao canal pode clicar em **Enviar confissão**, tanto no painel inicial quanto em cada confissão publicada. O formulário aceita texto obrigatório de até **4.000 caracteres** e o upload de **uma imagem opcional** (PNG, JPG, GIF ou WebP, até **8 MB**, respeitando também o limite do servidor, e 16 milhões de pixels). GIFs mantêm a animação. A imagem é reenviada como anexo do bot com nome de arquivo neutro. A confirmação do envio aparece somente para quem enviou.

As confissões aparecem em embeds roxos numerados, sem usuário, avatar ou ID do autor. O painel e o formulário avisam que **a identidade é visível para a equipe**. O canal privado recebe o texto, a imagem, o usuário, o ID e o horário; após a publicação, o registro recebe o link da confissão. Menções não geram notificações. A confissão só é publicada se o registro privado for enviado com sucesso. Se a publicação falhar, o registro permanece e informa a falha quando possível.

A configuração, a numeração por servidor e os IDs de atribuição ficam salvos no SQLite, nas tabelas `confession_configs` e `confessions`. Reiniciar ou reconfigurar não zera a numeração; tentativas interrompidas podem deixar números sem publicação. Os botões continuam funcionando depois de reiniciar. Ao mudar o canal, os painéis antigos ficam desativados; formulários já abertos precisam ser reabertos se a configuração mudar. Formulários expiram após 10 minutos sem interação e precisam ser reabertos após reiniciar o bot.

`cogs/confessions.py` usa o componente de upload documentado pelo Discord por meio de uma subclasse de `nextcord.ui.Modal`, pois Nextcord 3.2 não fornece esse componente em `nextcord.ui`. A implementação preserva o envio e o despacho de interações da biblioteca. Referência: [File Upload em modais](https://docs.discord.com/developers/components/reference#file-upload).

## Missões diárias

Use `r.missions` ou `/missions` para acompanhar três tarefas diárias:

| Tarefa | Meta | Bônus |
| --- | --- | --- |
| Boas-vindas ao reino | Receber `daily` uma vez | 2.500 D$ |
| Um dia de trabalho | Concluir `work` uma vez | 5.000 D$ |
| Talento independente | Concluir `freelance` três vezes | 7.500 D$ |

`r.missions claim` ou `/missions action:claim` resgata todos os bônus disponíveis de uma vez, além do pagamento normal dos comandos. Cada missão paga uma única vez por dia. O progresso é global por usuário, começa a contar após a instalação desta versão e fica salvo mesmo ao reiniciar o bot. As missões renovam às **00:00 GMT-3**; bônus não resgatados expiram nesse horário. Não é necessário abrir a lista para começar a progredir.

Somente pagamentos bem-sucedidos de `daily`, `work` e `freelance` contam; comandos recusados e créditos de administradores não contam. Os cooldowns existentes continuam valendo. A tabela `mission_progress` é criada automaticamente no banco. Metas, títulos e bônus ficam em `cogs/mission_rules.py`.

## Roleplay

O botão **Retribuir** permite que quem recebeu o beijo, abraço ou carinho responda ao autor com a mesma ação e o próximo GIF. Cada botão pode ser usado uma vez e expira após 2 minutos sem interação. A resposta traz um novo botão para o outro participante e respeita os mesmos cooldowns dos comandos.

`kiss`, `hug` e `pat` enviam embeds com os participantes mencionados, uma frase em português e um GIF grande. Cada comando sorteia um dos seus seis GIFs dos álbuns [kiss](https://imgur.com/a/E5nJtdx), [hug](https://imgur.com/a/gYHRVCv) e [pat](https://imgur.com/a/PLnbgn2) a cada uso, passando por todos antes de repetir. O último GIF de uma rodada nunca é o primeiro da próxima. A seleção é compartilhada entre servidores, prefixo/slash e o botão Retribuir, separada por ação, e recomeça ao reiniciar o bot. Os links diretos ficam em `cogs/roleplay.py`; alterações futuras nos álbuns precisam ser atualizadas ali.

Use em um servidor e escolha outro membro. Cada ação tem cooldown de 5 segundos por usuário, compartilhado entre prefixo e slash. Quando os dois participantes são casados entre si, a interação acrescenta de 1 a 3 pontos de afinidade e mostra o valor no rodapé. O total aparece em `r.marriage` e `/marriage` e persiste após reiniciar. A tabela `marriage_affinity` é criada automaticamente, preservando os casamentos existentes.

## Recompensa diária e cooldowns

`r.daily` e `/daily` compartilham uma recompensa por dia, com renovação às **00:00 no fuso fixo GMT-3 (03:00 UTC)**, independentemente do fuso do computador que executa o bot. Quem resgatar às 23:59 GMT-3 poderá resgatar novamente às 00:00. Os registros existentes continuam válidos, e reiniciar o bot não permite repetir a recompensa no mesmo dia.

Ao tentar resgatar novamente, a resposta informa a próxima meia-noite usando `<t:TIMESTAMP:R>`, que o Discord exibe como um tempo relativo, por exemplo **em 2 horas**. As mensagens de cooldown dos demais comandos também usam esse formato nos comandos com prefixo e slash. [Formato de timestamps do Discord](https://docs.discord.com/developers/reference#message-formatting).

## Atividades personalizadas

Após conectar, o bot alterna automaticamente entre **14 atividades**, uma a cada **60 segundos**, usando `nextcord.CustomActivity`. As frases incluem elogios ao dono Caio, dicas de comandos e informações atualizadas: quantidade de comandos e servidores, nome e número de membros de um servidor, tempo online, latência e comandos concluídos nesta sessão. O número de membros inclui bots; se houver vários servidores, a frase sobre membros alterna entre eles a cada volta da lista.

Alguns exemplos:

- `💚 Caio é meu dono e meu orgulho!`
- `✨ Meu dono Caio tem as melhores ideias!`
- `🧣 Caio, obrigado por me dar vida!`
- `🏡 Reino do Caio: 123 membros` (nome e contagem reais do servidor)
- `📚 23 comandos com r. e / | Use r.help ou /help` (contagem atualizada)
- `📡 Latência: 42 ms | Pronto para ajudar!` (latência atualizada)

Quando um administrador conclui um comando com sucesso, o bot dá prioridade a uma reação durante os **30 segundos seguintes** e depois retoma a rotação. Há frases específicas para os comandos de economia, jogos, ranking e perfil; os demais mostram quem usou o comando. Por exemplo, `r.addbalance` ou `/addbalance` pode mostrar `💰 Caio distribuiu DarkMoney. Obrigado por cuidar da turma!`. Comandos de membros sem permissão de administrador, comandos em mensagens diretas e execuções que falham não criam reações. Os argumentos e valores dos comandos não aparecem na atividade.

Administradores também podem definir uma atividade temporária com até **128 caracteres**, por **5 minutos**:

```text
r.activity Evento no reino! Vamos jogar.
/activity text:Evento no reino! Vamos jogar.

r.activity reset
/activity text:reset
```

Uma mensagem definida manualmente tem prioridade sobre as reações até expirar ou receber `reset`. A atividade do bot é **global, igual em todos os servidores**, e os textos temporários são descartados ao reiniciar. As frases e os intervalos podem ser editados em `cogs/activities.py`, nas listas `ACTIVITIES` e `ADMIN_REACTIONS` e nas constantes de tempo.

O bot publica no máximo uma alteração a cada 10 segundos; em uma sequência rápida de comandos, prevalece a reação mais recente. Isso mantém as alterações abaixo do limite documentado de cinco atualizações em 20 segundos. Emojis são incluídos no próprio texto da atividade. [Referência de atividades e limites do Discord](https://docs.discord.com/developers/events/gateway-events#activity-object).

## Perfil social

`cogs/social.py` gera um cartão de 1000×790: avatar circular e identidade no cabeçalho, posição no `r.rich` e saldo à direita, imagem personalizada no centro e Sobre mim no rodapé. A cor escolhida preenche o cabeçalho e o rodapé; a cor do texto muda automaticamente para manter a leitura. A posição e o saldo são consultados a cada visualização.

Para definir o fundo, anexe **uma imagem à mesma mensagem** que contém `r.profile background`, ou envie o arquivo na opção **image** de `/profile background`. São aceitos PNG, JPG, WebP e GIF, até 8 MB e 16 milhões de pixels. A imagem é recortada pelo centro para 1000×400; GIFs usam o primeiro quadro. O fundo é salvo no SQLite e continua disponível após reiniciar o bot. Use `r.profile background reset` ou `/profile background action:reset` para remover o fundo, e `r.profile about reset` ou `/profile about text:reset` para limpar a bio. Cada usuário altera apenas seu próprio perfil.

## Casamentos e ships

Use `r.marry @membro` ou `/marry member:@membro` em um servidor para abrir um pedido. **As duas pessoas precisam clicar em Confirmar**, incluindo quem enviou o pedido; o comando sozinho não conta como aceitação. Cada pessoa confirma uma única vez, e terceiros não podem usar os botões. Qualquer uma das duas pessoas pode clicar em **Recusar / cancelar**. Pedidos expiram após 2 minutos sem interação.

Cada pessoa pode ter **um casamento** e participar de **um pedido pendente** por vez. Não é possível casar consigo mesmo ou com bots. O casamento só é salvo depois das duas confirmações, com verificação final de que as duas pessoas ainda estão disponíveis. Os casamentos são globais entre os servidores do bot e continuam salvos após reiniciar. Pedidos pendentes precisam ser enviados novamente após uma reinicialização.

`r.marriage` e `/marriage` mostram seu casamento. Informe um usuário para consultar o casamento dele: `r.marriage @usuário` ou `/marriage member:@usuário`. O embed mostra os dois participantes, a data e hora do casamento com `<t:TIMESTAMP:F>` e o tempo juntos com `<t:TIMESTAMP:R>`, no idioma e fuso do Discord de quem está vendo. Usuários sem casamento recebem um embed informando isso.

Para shippar você com alguém, use `r.ship @usuário` ou `/ship first:@usuário`. Para escolher as duas pessoas, use `r.ship @pessoa1 @pessoa2` ou `/ship first:@pessoa1 second:@pessoa2`. O bot sorteia um inteiro de **0 a 100 uma única vez por par** e salva o resultado. Inverter os usuários, trocar de servidor ou reiniciar o bot mantém a mesma porcentagem. O ship é uma brincadeira e não altera o estado civil das pessoas.

A imagem de 1000×680 mostra os dois avatares circulares, os nomes e a porcentagem abaixo dos avatares. As fotos são lidas do Discord a cada consulta; se uma foto não puder ser carregada, aparece a inicial do nome. A imagem é montada localmente com Pillow. `ship-preview.png` demonstra o layout com iniciais de exemplo. Pedidos têm cooldown de 10 segundos, e ships têm cooldown de 5 segundos, compartilhados entre prefixo e slash.

## Regras dos jogos

As opções **amount** de `/slots`, `/blackjack` e `/mines` aceitam os mesmos valores do prefixo, incluindo `10k`, `1.5m`, `half` e `all`. Valores de moedas são enviados como texto nos comandos slash para preservar números inteiros grandes sem arredondamento. Os botões, menus e timeouts funcionam nos dois formatos.

Apostas não têm teto fixo: você pode apostar **de 1 DarkMoney até todo o saldo disponível**. Slots, blackjack e Mines aceitam `k` para mil e `m` para milhão: `r.slots 10k`, `r.blackjack 1.5k`, `r.mines 5m 5`. Use `half` para metade do saldo, arredondada para baixo (`r.blackjack half`), ou `all` para todo o saldo (`r.slots all`, `r.mines all 5`). Os aliases são calculados no momento do débito; saldo zero e metade de um saldo de 1 moeda são rejeitados. Maiúsculas também funcionam (`10K`, `1M`, `HALF`, `ALL`). Decimais usam ponto e precisam resultar em moedas inteiras: `0.001k` vale 1, mas `0.0001k` é rejeitado. Cada jogador pode ter um jogo em andamento. Todos os retornos incluem a aposta inicial; frações de moeda nos pagamentos são arredondadas para baixo.

- **Slots:** três rolos independentes com seis símbolos equiprováveis. Qualquer par paga 2×. Trincas: cereja/limão/uva 3×, sino 4×, estrela 5×, diamante 10×. Três símbolos diferentes pagam zero. Retorno teórico: 208/216, aproximadamente 96,30%. A tabela aparece no resultado.
- **Blackjack:** baralho novo de 52 cartas a cada rodada. Ás vale 1 ou 11; figuras valem 10. A banca para em qualquer 17, incluindo 17 com ás valendo 11. Vitória paga 2×; blackjack inicial paga 2,5× (lucro 3:2); empate devolve 1×. Blackjack natural vence um 21 com mais cartas. Sem seguro, divisão ou dobro. Ao atingir 21, o jogador para automaticamente. Após 120s sem ação, o bot executa “Parar”.
- **Mines:** escolha a quantidade de bombas antes de jogar. Mais bombas aumentam o multiplicador e o risco; o menu mostra o retorno após a primeira casa segura (1 bomba: 1,03×; 5: 1,41×; 10: 2,59×; 15: 15,52×). A escolha fica fixa durante a rodada. Revele casas usando os botões. Uma mina perde a aposta. Após pelo menos uma casa segura, “Retirar” encerra o jogo com o retorno exibido. O multiplicador para `k` casas seguras e `m` minas é `0,97 × C(16,k) / C(16-m,k)`. Revelar todas as casas seguras retira automaticamente. Após 120s sem ação, o bot retira o valor atual, ou devolve a aposta se nenhuma casa foi aberta ou nenhuma quantidade foi escolhida.

Apenas o jogador que iniciou a rodada pode usar seus botões. Apostas são debitadas antes do início e liquidadas uma única vez em transações SQLite. Jogos pendentes são reembolsados na próxima inicialização; jogos encerrados não são pagos novamente. Execute **uma instância do bot por banco**, pois os controles ativos ficam na memória desse processo.

O arquivo `bot.db` existente é preservado. As tabelas `bets`, `daily_claims`, `social_profiles`, `ship_scores`, `marriages` e `ticket_configs` são adicionadas automaticamente. `BOT_DATABASE_URL` pode apontar para outro banco SQLite. O token é lido de `DISCORD_TOKEN` e nunca deve ser incluído no código.

Valores monetários que ultrapassam o inteiro de 64 bits do SQLite são armazenados como bytes com ordenação numérica, sem arredondamento. Saldos, apostas, pagamentos e posições no ranking continuam exatos, e os valores inteiros antigos permanecem compatíveis.

## Verificar

```powershell
.\.venv\Scripts\python -m unittest discover -s test -p "test_*.py" -v
```

Os testes usam bancos temporários e interações simuladas, sem login no Discord. Cobrem regras, concorrência, pagamentos duplicados, reinicialização, permissões dos botões, timeouts, falha no envio e geração do PNG. Também verificam o registro de todos os comandos slash, a leitura das opções pelo Nextcord, anexos, permissões administrativas, alteração e reset de saldo, ajuda em ambos os formatos e cooldowns compartilhados entre prefixo, aliases e slash. A recompensa diária é verificada antes e exatamente à meia-noite GMT-3, nas viradas de mês e ano, após reiniciar e com pedidos simultâneos; os timestamps relativos são verificados nos dois formatos de comando. As atividades são verificadas com relógio simulado: rotação, reações a comandos de administradores, prioridade e expiração de textos manuais, limite de atualizações, reconexão e encerramento da tarefa. `test/bot.test.js` é um teste legado de uma implementação JavaScript ausente; não pertence à suíte Python.

Referência de extensões Nextcord: https://docs.nextcord.dev/en/stable/ext/commands/extensions.html

Os testes de casamento verificam consentimento individual, cliques simultâneos e repetidos, terceiros, recusa, expiração, conflitos entre casamentos, falhas no envio, datas persistentes, porcentagens fixas e simétricas e imagens com os dois avatares. Os três comandos também são exercitados com opções slash e aliases de prefixo.

Referência de comandos slash Nextcord: https://docs.nextcord.dev/en/stable/interactions.html

Referência de CustomActivity Nextcord: https://docs.nextcord.dev/en/stable/api.html#nextcord.CustomActivity
