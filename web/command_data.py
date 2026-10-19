"""Command metadata and descriptions for the web dashboard."""
from typing import Dict, List

COMMAND_METADATA: Dict[str, Dict] = {
    # Economia
    "balance": {"name": "balance", "desc": "Consulta o saldo de DarkMoney (D$) de um usuário.", "cat": "economia"},
    "daily": {"name": "daily", "desc": "Reivindica a recompensa diária de DarkMoney.", "cat": "economia"},
    "pay": {"name": "pay", "desc": "Transfere DarkMoney para outro usuário.", "cat": "economia"},
    "work": {"name": "work", "desc": "Trabalha para ganhar DarkMoney e subir de nível de profissão.", "cat": "economia"},
    "freelance": {"name": "freelance", "desc": "Faz bicos rápidos para faturar moedas extras.", "cat": "economia"},
    "rob": {"name": "rob", "desc": "Tenta roubar moedas de outro usuário (com risco de multa!).", "cat": "economia"},

    # Jogos & Cassino
    "blackjack": {"name": "blackjack", "desc": "Jogue Blackjack (21) apostando DarkMoney contra a mesa.", "cat": "jogos"},
    "dice": {"name": "dice", "desc": "Aposte em rolagens de dados contra a sorte.", "cat": "jogos"},
    "mines": {"name": "mines", "desc": "Campo minado interativo com multiplicadores crescentes.", "cat": "jogos"},
    "poker": {"name": "poker", "desc": "Mesa de Texas Hold'em Poker multiplayer com botões.", "cat": "jogos"},
    "six": {"name": "six", "desc": "Jogo de cartas estilo Uno multiplayer em tempo real.", "cat": "jogos"},
    "slots": {"name": "slots", "desc": "Máquina caça-níqueis com combinações premiadas.", "cat": "jogos"},

    # Social & Casamento
    "profile": {"name": "profile", "desc": "Exibe o cartão de perfil customizado do usuário.", "cat": "social"},
    "marry": {"name": "marry", "desc": "Pede outro usuário em casamento.", "cat": "social"},
    "divorce": {"name": "divorce", "desc": "Divorcia-se do cônjuge atual.", "cat": "social"},
    "marriage": {"name": "marriage", "desc": "Exibe detalhes e afinidade do casamento.", "cat": "social"},
    "ship": {"name": "ship", "desc": "Calcula a porcentagem de afinidade amorosa entre dois membros.", "cat": "social"},
    "rich": {"name": "rich", "desc": "Exibe o ranking dos usuários mais ricos de DarkMoney.", "cat": "social"},
    "userinfo": {"name": "userinfo", "desc": "Mostra informações detalhadas sobre a conta de um membro.", "cat": "social"},
    "tarot": {"name": "tarot", "desc": "Tira cartas de tarô com leituras místicas e ilustrações.", "cat": "social"},
    "anilist": {"name": "anilist", "desc": "Pesquisa animes e mangás diretamente no AniList.", "cat": "social"},
    "namemc": {"name": "namemc", "desc": "Consulta histórico de skins e nicks do Minecraft.", "cat": "social"},

    # Roleplay
    "kiss": {"name": "kiss", "desc": "Dá um beijo carinhoso em outro membro com GIF animado.", "cat": "roleplay"},
    "hug": {"name": "hug", "desc": "Dá um abraço quentinho em outro membro com GIF animado.", "cat": "roleplay"},
    "pat": {"name": "pat", "desc": "Faz carinho na cabeça de outro membro com GIF animado.", "cat": "roleplay"},

    # Missões & Música
    "missions": {"name": "missions", "desc": "Exibe missões diárias ativas e progresso para resgatar prêmios.", "cat": "missoes_musica"},
    "musica": {"name": "musica", "desc": "Recomenda uma música selecionada do dia com capa e link Spotify.", "cat": "missoes_musica"},

    # Moderação
    "ban": {"name": "ban", "desc": "Bane um membro do servidor preservando histórico de mensagens.", "cat": "moderacao"},
    "unban": {"name": "unban", "desc": "Remove o banimento de um usuário pelo ID.", "cat": "moderacao"},
    "kick": {"name": "kick", "desc": "Expulsa um membro do servidor.", "cat": "moderacao"},
    "mute": {"name": "mute", "desc": "Aplica timeout temporário silenciando um membro.", "cat": "moderacao"},
    "unmute": {"name": "unmute", "desc": "Remove o timeout de um membro silenciado.", "cat": "moderacao"},
    "lock": {"name": "lock", "desc": "Tranca o canal impedindo envio de novas mensagens por membros.", "cat": "moderacao"},
    "unlock": {"name": "unlock", "desc": "Destranca o canal restaurando as permissões originais.", "cat": "moderacao"},
    "clear": {"name": "clear", "desc": "Exclui mensagens recentes em massa no canal.", "cat": "moderacao"},
    "slowmode": {"name": "slowmode", "desc": "Configura o tempo de espera do modo lento do canal.", "cat": "moderacao"},

    # Administração
    "confess": {"name": "confess", "desc": "Envia uma confissão anônima para o canal configurado.", "cat": "administracao"},
    "quiz": {"name": "quiz", "desc": "Sugerir perguntas para o sistema de quiz automático.", "cat": "administracao"},
    "quizpanel": {"name": "quizpanel", "desc": "Painel de controle para aprovar sugestões de quiz.", "cat": "administracao"},
    "quizoff": {"name": "quizoff", "desc": "Desativa as rodadas de quiz no servidor.", "cat": "administracao"},
    "ticket": {"name": "ticket", "desc": "Cria um canal privado de suporte/atendimento.", "cat": "administracao"},
    "close": {"name": "close", "desc": "Fecha e arquiva o ticket de atendimento atual.", "cat": "administracao"},
    "send": {"name": "send", "desc": "Envia uma mensagem de texto simples em qualquer canal.", "cat": "administracao"},
    "embedsend": {"name": "embedsend", "desc": "Envia uma mensagem formatada em embed customizado.", "cat": "administracao"},
    "admmusica": {"name": "admmusica", "desc": "Muda manualmente a música recomendada do dia.", "cat": "administracao"},

    # Geral
    "help": {"name": "help", "desc": "Menu interativo de ajuda com todos os comandos.", "cat": "geral", "protected": True},
    "ping": {"name": "ping", "desc": "Verifica se o bot está online e medindo a latência.", "cat": "geral", "protected": True},
    "sync": {"name": "sync", "desc": "Sincroniza os slash commands com a API do Discord.", "cat": "administracao", "protected": True},
}

CATEGORIES_INFO: Dict[str, Dict] = {
    "economia": {"label": "Economia", "emoji": "🪙", "desc": "DarkMoney, trabalho, transferências e roubos."},
    "jogos": {"label": "Jogos & Cassino", "emoji": "🎲", "desc": "Apostas, Blackjack, Roleta, Minas, Poker e Uno."},
    "social": {"label": "Social & Perfil", "emoji": "💍", "desc": "Perfis customizados, casamentos, ship e rankings."},
    "roleplay": {"label": "Roleplay & Afeto", "emoji": "🎭", "desc": "Interações sociais com GIFs animados."},
    "missoes_musica": {"label": "Missões & Música", "emoji": "📜", "desc": "Desafios diários e recomendações de músicas."},
    "moderacao": {"label": "Moderação", "emoji": "🛡️", "desc": "Punições, silenciamentos e controle de canais."},
    "administracao": {"label": "Administração & Utilidades", "emoji": "⚙️", "desc": "Confissões, tickets, quiz e envios de avisos."},
    "geral": {"label": "Geral", "emoji": "ℹ️", "desc": "Comandos básicos informativos do bot."},
}

