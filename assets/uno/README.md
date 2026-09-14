# Artes dos três baralhos de Six / Uno

O baralho final ainda está em produção. Enquanto isso, o bot desenha cartas
provisórias com número/ação e cor, sem precisar baixar imagens. Cada PNG entregue
substitui apenas a carta correspondente; as demais continuam funcionando.

O anfitrião escolhe **Normal**, **Meme** ou **Overwatch** no lobby. A escolha fica
fixa ao começar e muda tanto a carta pública quanto todas as mãos e confirmações.
Cada baralho usa suas próprias imagens. Coloque os mesmos nomes de arquivos em:

- `assets/uno/normal/` — baralho normal;
- `assets/uno/meme/` — baralho de memes;
- `assets/uno/overwatch/` — baralho de Overwatch.

Por exemplo, `normal/red_3.png`, `meme/red_3.png` e `overwatch/red_3.png` são três
artes diferentes para o mesmo 3 vermelho. Se faltar uma arte, o bot usa uma carta
provisória **do tema escolhido**, sem pegar a imagem de outro baralho. Os temas
provisórios usam molduras e identificações diferentes; os PNGs finais substituem
a face inteira, sem moldura extra. Use os nomes abaixo em letras minúsculas:

| Cartas | Nomes de arquivo |
| --- | --- |
| Números vermelhos | `red_0.png` até `red_9.png` |
| Números amarelos | `yellow_0.png` até `yellow_9.png` |
| Números verdes | `green_0.png` até `green_9.png` |
| Números azuis | `blue_0.png` até `blue_9.png` |
| Bloqueio | `red_skip.png`, `yellow_skip.png`, `green_skip.png`, `blue_skip.png` |
| Inverter | `red_reverse.png`, `yellow_reverse.png`, `green_reverse.png`, `blue_reverse.png` |
| Comprar +2 | `red_draw2.png`, `yellow_draw2.png`, `green_draw2.png`, `blue_draw2.png` |
| Coringa | `wild.png` |
| Coringa +4 | `wild4.png` |

São **54 imagens por baralho, 162 para os três completos**; cartas repetidas usam
o mesmo arquivo dentro de cada tema. Use PNG em pé,
preferencialmente com proporção 2:3 (por exemplo, 600 × 900 px). A renderização da
carta da mesa usa 300 × 450 px; na mão, cada carta usa 120 × 180 px. Outras
proporções são centralizadas e ajustadas sem corte ou distorção. Transparência é
aceita e recebe um fundo escuro.

As imagens são abertas a cada renderização: adicionar ou substituir uma arte
não exige reiniciar o bot. Mensagens já enviadas conservam a imagem anterior até
a próxima atualização. Para evitar a leitura de um arquivo pela metade, termine
o upload com outro nome e só então renomeie para o nome definitivo.

Arquivo ausente, inválido ou com mais de 16 milhões de pixels usa a carta
provisória. O código não altera os arquivos de arte. Os nomes e emojis em texto
continuam disponíveis nos controles, independentemente das imagens.
