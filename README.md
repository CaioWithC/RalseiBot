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
| `r.balance` | `/balance` | Saldo; aliases: `saldo`, `atm`, `bal` |
| `r.daily` | `/daily` | Recompensa de 5.000–100.000 moedas uma vez por dia; renova às 00:00 GMT-3, persistente |
| `r.work` | `/work` | Ganha 10.000–40.000 moedas; intervalo de 2h; somente em servidores |
| `r.freelance` | `/freelance` | Ganha 100–10.000 moedas; intervalo de 10min; aliases: `freelancer`, `freelas`, `frelas` |
| `r.rob @membro` | `/rob member:@membro` | Tenta roubar DarkMoney de outro membro; intervalo de 1h |
| `r.pay @membro 100` | `/pay member:@membro amount:100` | Transfere moedas após as duas pessoas clicarem em Aceitar; qualquer uma pode cancelar e o pedido expira após 2 minutos sem interação; aceita `K` (mil) e `M` (milhão), como `1.5k` ou `2M`; aliases: `transferir`, `pix`, `pagar` |
| `r.addbalance @membro 100` | `/addbalance member:@membro amount:100` | Adiciona moedas; somente administradores |
| `r.setbalance @membro 100` | `/setbalance member:@membro amount:100` | Define o saldo disponível; somente administradores |
| `r.resetbalance @membro` | `/resetbalance member:@membro` | Zera o saldo disponível; somente administradores |
| `r.activity Seu texto aqui` | `/activity text:Seu texto aqui` | Atividade personalizada por 5 minutos; somente administradores; aliases: `atividade`, `status`. Use `reset` para retomar a rotação |
| `r.ticket Categoria` | `/ticket category:Categoria` | Publica um painel que cria tickets privados numerados; somente administradores |
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
| `r.mines 100 [bombas]` | `/mines amount:100 [mine_count]` | Escolha 1–15 bombas no menu ou informe a quantidade. Tabuleiro 4×4; alias: `minas` |

Nos comandos slash, preencha os campos que o Discord oferece; os itens entre colchetes são opcionais. O Discord exige um subcomando em grupos, então visualizar o perfil usa `/profile view`. Todos os aliases da tabela continuam disponíveis com `r.`. Os dois formatos executam os mesmos comandos, com as mesmas permissões, conversores, saldos e cooldowns; alternar entre prefixo e slash não permite repetir uma recompensa ou evitar o intervalo. Os comandos de administração alteram apenas o saldo disponível; apostas já iniciadas continuam com sua liquidação normal.

O ranking é global entre todos os usuários registrados e mostra o saldo disponível, sem apostas em andamento. Empates são ordenados pelo ID do usuário. Nomes vêm do cache do Discord, com ID como alternativa. A imagem é desenhada localmente com Pillow, sem serviços de geração ou downloads de avatares.

## Roleplay

O botão **Retribuir** permite que quem recebeu o beijo, abraço ou carinho responda ao autor com a mesma ação e o próximo GIF. Cada botão pode ser usado uma vez e expira após 2 minutos sem interação. A resposta traz um novo botão para o outro participante e respeita os mesmos cooldowns dos comandos.

`kiss`, `hug` e `pat` enviam embeds com os participantes mencionados, uma frase em português e um GIF grande. Cada comando sorteia um dos seus seis GIFs dos álbuns [kiss](https://imgur.com/a/E5nJtdx), [hug](https://imgur.com/a/gYHRVCv) e [pat](https://imgur.com/a/PLnbgn2) a cada uso, passando por todos antes de repetir. O último GIF de uma rodada nunca é o primeiro da próxima. A seleção é compartilhada entre servidores, prefixo/slash e o botão Retribuir, separada por ação, e recomeça ao reiniciar o bot. Os links diretos ficam em `roleplay.py`; alterações futuras nos álbuns precisam ser atualizadas ali.

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

Uma mensagem definida manualmente tem prioridade sobre as reações até expirar ou receber `reset`. A atividade do bot é **global, igual em todos os servidores**, e os textos temporários são descartados ao reiniciar. As frases e os intervalos podem ser editados em `activities.py`, nas listas `ACTIVITIES` e `ADMIN_REACTIONS` e nas constantes de tempo.

O bot publica no máximo uma alteração a cada 10 segundos; em uma sequência rápida de comandos, prevalece a reação mais recente. Isso mantém as alterações abaixo do limite documentado de cinco atualizações em 20 segundos. Emojis são incluídos no próprio texto da atividade. [Referência de atividades e limites do Discord](https://docs.discord.com/developers/events/gateway-events#activity-object).

## Perfil social

`social.py` gera um cartão de 1000×790: avatar circular e identidade no cabeçalho, posição no `r.rich` e saldo à direita, imagem personalizada no centro e Sobre mim no rodapé. A cor escolhida preenche o cabeçalho e o rodapé; a cor do texto muda automaticamente para manter a leitura. A posição e o saldo são consultados a cada visualização.

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
