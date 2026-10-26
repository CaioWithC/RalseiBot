import asyncio
import collections
import logging
import os
import re
import aiohttp
import nextcord
from nextcord.ext import commands
from cogs.command_support import DualCommand

log = logging.getLogger(__name__)

GEMINI = os.getenv("AI_API_URL", "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions")
MAX_MEMORY_MESSAGES = 16  # Armazena até 16 mensagens (8 rodadas de conversa) por canal

SYSTEM_PROMPT = (
    "Você é um assistente de IA chamado Ralsei, que fala português brasileiro."
    "Você é um assistente pessoal que se comunica de forma natural, direta e humana, como alguém conversando no dia a dia"
    "Use emojis quase nunca."
    "Se o usuário te perguntar de forma ofensiva ou inapropriada, você pode responder do mesmo jeito dele"
    "Se a conversa tiver descontraida ou sem nexo, você deve responder de forma descontraida e sem nexo também."
    "Se o usuário pedir para você se comportar como um personagem, você deve seguir o papel do personagem."
    "Se o usuário falar 'seu dono' perguntado quem é, você deve responder algo do tipo 'meu dono é o Caio, ele me criou e me mantém funcionando'."
    "Você funciona da seguinte forma: você tem varias funcionalidades, você tem comandos de economia, comandos de jogos, comandos de música, comandos de perfil, comandos de roleplay, comandos de confissões, comandos de quiz, comandos de uno, comandos de moderação e comandos de inteligência artificial;"
    "Se o usuário te perguntar algo besta ou sem sentido, você deve responder do jeito que o usuário perguntou, sem corrigir ou mudar o que ele disse."
)

# Lista de modelos em ordem de prioridade. Se o primeiro sofrer rate limit (429), tenta os próximos.
DEFAULT_MODELS = [
    os.getenv("AI_MODEL", "gemini-3.1-flash-lite"),
    os.getenv("AI_MODEL_FALLBACK", "gemini-3.5-flash-lite")
]


class AI(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session: aiohttp.ClientSession | None = None
        # Memória de conversa por canal: channel_id -> list[dict]
        self.channel_memory: dict[int, list[dict]] = collections.defaultdict(list)
        # Trava por canal para evitar conflitos de requisições simultâneas
        self.channel_locks: dict[int, asyncio.Lock] = collections.defaultdict(asyncio.Lock)

    async def get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=50))
        return self.session

    def cog_unload(self):
        if self.session and not self.session.closed:
            asyncio.create_task(self.session.close())

    def get_api_key(self) -> str | None:
        return (
            os.getenv("gemini_api_key")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("openrouter_api_key")
            or os.getenv("OPENROUTER_API_KEY")
        )

    async def generate_completion(self, messages_payload: list[dict]) -> tuple[str | None, dict | None]:
        """Envia um payload de mensagens para a API de IA com suporte a fallback de modelos."""
        api_key = self.get_api_key()
        if not api_key:
            log.error("Chave da API não configurada no .env (gemini_api_key ou openrouter_api_key).")
            return "Desculpe, a minha chave de inteligência artificial não foi configurada no `.env` ainda!", None

        session = await self.get_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/RalseiBot",
            "X-Title": "RalseiBot",
        }

        # Remove duplicatas consecutivas de modelos na lista de tentativas
        models_to_try = []
        for m in DEFAULT_MODELS:
            if m and m not in models_to_try:
                models_to_try.append(m)

        last_error = None
        for model in models_to_try:
            payload = {
                "model": model,
                "messages": messages_payload,
                "reasoning_effort": os.getenv("AI_REASONING_EFFORT", "low"),
            }
            try:
                async with session.post(GEMINI, headers=headers, json=payload) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        choices = data.get("choices", [])
                        if not choices:
                            continue
                        msg_data = choices[0].get("message", {})
                        content = msg_data.get("content", "").strip()

                        # Remove tags internas de pensamento como <think>...</think> se presentes
                        cleaned_content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                        final_text = cleaned_content if cleaned_content else content

                        if final_text:
                            return final_text, msg_data.get("reasoning_details")
                    elif resp.status == 429:
                        log.warning("Modelo %s retornou 429 (rate-limit). Tentando fallback...", model)
                        last_error = "rate_limit"
                        continue
                    else:
                        text_err = await resp.text()
                        log.error("Erro na API OpenRouter (%s - status %s): %s", model, resp.status, text_err[:200])
                        last_error = f"status_{resp.status}"
            except Exception as e:
                log.exception("Exceção ao chamar OpenRouter com modelo %s: %s", model, e)
                last_error = str(e)

        if last_error == "rate_limit":
            return "Estou recebendo muitas mensagens no momento! Pode esperar alguns segundinhos e tentar de novo? 🍰", None
        return "Desculpe, tive um probleminha para pensar agora... podemos tentar de novo em instantes?", None

    async def generate_response(self, channel_id: int, user_entry: dict) -> str | None:
        """Envia o histórico do canal e a nova mensagem para a API do Gemini."""
        current_history = self.channel_memory[channel_id]
        messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}] + current_history + [user_entry]

        final_text, reasoning_details = await self.generate_completion(messages_payload)
        if final_text and not final_text.startswith("Desculpe,") and not final_text.startswith("Estou recebendo muitas"):
            self.channel_memory[channel_id].append(user_entry)
            assistant_entry = {
                "role": "assistant",
                "content": final_text,
            }
            if reasoning_details:
                assistant_entry["reasoning_details"] = reasoning_details
            self.channel_memory[channel_id].append(assistant_entry)

            # Mantém apenas as últimas mensagens para não exceder limites
            if len(self.channel_memory[channel_id]) > MAX_MEMORY_MESSAGES:
                self.channel_memory[channel_id] = self.channel_memory[channel_id][-MAX_MEMORY_MESSAGES:]

        return final_text

    async def explain_tarot(
        self,
        question: str | None,
        cards_data: list[tuple[dict, bool]],
        author_name: str = "Viajante",
    ) -> str:
        """Usa a IA para sintetizar e explicar as cartas tiradas na leitura de tarot."""
        is_three_spread = len(cards_data) == 3
        positions = ["Passado / Origem", "Presente / Desafio", "Futuro / Conselho"] if is_three_spread else ["Carta do Dia"]

        cards_desc = []
        for idx, (card, is_rev) in enumerate(cards_data):
            pos_label = positions[idx] if idx < len(positions) else f"Carta {idx + 1}"
            orient = "Invertida 🔄 (energia bloqueada ou reflexão interna)" if is_rev else "Em pé ☀️ (energia manifestada e direta)"
            keywords = card.get("keywords_reversed" if is_rev else "keywords_upright", "")
            waite = card.get("div_mean_rev_en" if is_rev else "div_mean_en", "")

            desc_line = (
                f"• Posição: {pos_label}\n"
                f"  Carta: {card.get('name_pt', card.get('name_en'))} ({card.get('name_en')}) [{orient}]\n"
                f"  Palavras-chave: {keywords}\n"
                f"  Significado tradicional A.E. Waite: {waite}"
            )
            cards_desc.append(desc_line)

        cards_text = "\n\n".join(cards_desc)

        tarot_system_prompt = (
            "Você é o Ralsei, atuando como um sábio leitor de tarot."
            "Você fala português brasileiro e tem um tom acolhedor, gentil, intuitivo e encorajador."
            "Interprete as cartas do baralho Rider-Waite-Smith (1910) com sabedoria, sem inventar fatos ou ser excessivamente formal."
            "Não use muitos emojis, apenas alguns para dar leveza."
        )

        if question:
            user_content = (
                f"O consulente {author_name} perguntou às cartas do tarot:\n"
                f"“{question}”\n\n"
                f"Cartas tiradas na mesa:\n"
                f"{cards_text}\n\n"
                f"Faça um resumo e interpretação fluida de 2 a 4 parágrafos curtos:\n"
                f"1. Conecte as cartas diretamente à pergunta de {author_name}, explicando a narrativa do Passado para o Presente e o Futuro.\n"
                f"2. Explique os desafios revelados e o conselho prático final para que {author_name} tome as melhores decisões.\n"
                f"Resuma em poucas palavras, de forma clara, direta e humana, como se estivesse conversando com {author_name}."
            )
        else:
            user_content = (
                f"O consulente {author_name} tirou a Carta do Dia:\n"
                f"{cards_text}\n\n"
                f"Faça uma interpretação e conselho diário de 2 a 3 parágrafos curtos sobre a energia de hoje para {author_name}, "
                f"trazendo clareza, incentivo e uma recomendação prática para o dia."
            )

        messages = [
            {"role": "system", "content": tarot_system_prompt},
            {"role": "user", "content": user_content},
        ]

        final_text, _ = await self.generate_completion(messages)
        return final_text or "Não foi possível gerar o resumo com a IA no momento."

    @commands.command(
        cls=DualCommand,
        name="ia",
        aliases=["chat", "pergunta", "ai"],
        help="Converse com o Ralsei usando inteligência artificial: r.ia <pergunta>",
    )
    @commands.cooldown(1, 3, lambda message: message.author.id)
    async def ia(self, ctx: commands.Context, *, pergunta: str = None):
        """Responde a perguntas usando inteligência artificial."""
        if not pergunta or not pergunta.strip():
            await ctx.send("Por favor, faça uma pergunta! Exemplo: `r.ia Olá, tudo bem?`")
            return

        clean_text = pergunta.strip()
        channel_id = ctx.channel.id if ctx.channel else ctx.author.id
        is_interaction = getattr(ctx, "interaction", None) is not None

        async with self.channel_locks[channel_id]:
            # Ativa indicador de digitação se for mensagem de texto comum
            typing_active = False
            typing_cm = None
            if ctx.channel and not is_interaction:
                try:
                    typing_cm = ctx.channel.typing()
                    await typing_cm.__aenter__()
                    typing_active = True
                except Exception:
                    pass

            try:
                user_entry = {
                    "role": "user",
                    "content": f"{ctx.author.display_name}: {clean_text}",
                }
                response = await self.generate_response(channel_id, user_entry)
            finally:
                if typing_active and typing_cm:
                    try:
                        await typing_cm.__aexit__(None, None, None)
                    except Exception:
                        pass

        if not response:
            await ctx.send("Desculpe, não consegui pensar em uma resposta agora...")
            return

        # Discord possui limite de 2000 caracteres por mensagem
        chunks = [response[i:i + 1950] for i in range(0, len(response), 1950)] if len(response) > 2000 else [response]

        for idx, chunk in enumerate(chunks):
            if idx == 0 and not is_interaction:
                try:
                    await ctx.reply(chunk, mention_author=False)
                    continue
                except Exception:
                    pass
            await ctx.send(chunk)

    @commands.command(cls=DualCommand, name="clearmemory", aliases=["limparmemoria", "esquecer"], help="Limpa a memória de conversa do Ralsei neste canal.")
    async def clear_memory(self, ctx: commands.Context):
        channel_id = ctx.channel.id if ctx.channel else ctx.author.id
        self.channel_memory.pop(channel_id, None)
        await ctx.send("Minha memória deste canal foi limpa! Podemos começar um novo assunto. 🍰")


def setup(bot: commands.Bot):
    bot.add_cog(AI(bot))