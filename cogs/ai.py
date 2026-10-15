import asyncio
import collections
import logging
import os
import re
import aiohttp
import nextcord
from nextcord.ext import commands

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
    "Se o usuário falar 'seu dono' perguntado quem é, você deve responder 'meu dono é o Caio, ele me criou e me mantém funcionando'."
    "Você funciona da seguinte forma: você tem varias funcionalidades, você tem comandos de economia, comandos de jogos, comandos de música, comandos de perfil, comandos de roleplay, comandos de confissões, comandos de quiz, comandos de uno, comandos de moderação e comandos de inteligência artificial;"
    "Se o usuário te perguntar algo besta ou sem sentido, você deve responder do jeito que o usuário perguntou, sem corrigir ou mudar o que ele disse."
    "Se o usuário tem o nome de usuário 'Matt', você deve falar no final da mensagem que o Caio o ama muito."
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

    async def generate_response(self, channel_id: int, user_entry: dict) -> str | None:
        """Envia o histórico do canal e a nova mensagem para a API do Gemini."""
        api_key = self.get_api_key()
        if not api_key:
            log.error("Chave da API não configurada no .env (gemini_api_key ou openrouter_api_key).")
            return "Desculpe, a minha chave de inteligência artificial não foi configurada no `.env` ainda!"

        session = await self.get_session()
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/RalseiBot",
            "X-Title": "RalseiBot",
        }

        # Constrói o histórico completo para a API
        current_history = self.channel_memory[channel_id]
        messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}] + current_history + [user_entry]

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
                            # Salva na memória do canal
                            self.channel_memory[channel_id].append(user_entry)
                            assistant_entry = {
                                "role": "assistant",
                                "content": final_text,
                            }
                            # Preserva reasoning_details se fornecido pelo modelo
                            if msg_data.get("reasoning_details"):
                                assistant_entry["reasoning_details"] = msg_data["reasoning_details"]
                            self.channel_memory[channel_id].append(assistant_entry)

                            # Mantém apenas as últimas mensagens para não exceder limites
                            if len(self.channel_memory[channel_id]) > MAX_MEMORY_MESSAGES:
                                self.channel_memory[channel_id] = self.channel_memory[channel_id][-MAX_MEMORY_MESSAGES:]

                            return final_text
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
            return "Estou recebendo muitas mensagens no momento! Pode esperar alguns segundinhos e tentar de novo? 🍰"
        return "Desculpe, tive um probleminha para pensar agora... podemos tentar de novo em instantes?"

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        # Ignora mensagens de bots ou do próprio bot
        if message.author.bot or message.author.id == self.bot.user.id:
            return

        bot_user = self.bot.user
        if not bot_user:
            return

        # Verifica se o bot foi mencionado diretamente ou se é resposta a uma mensagem dele
        is_mentioned = bot_user in message.mentions and not message.mention_everyone
        is_reply_to_bot = False
        if message.reference and isinstance(message.reference.resolved, nextcord.Message):
            if message.reference.resolved.author.id == bot_user.id:
                is_reply_to_bot = True

        if not (is_mentioned or is_reply_to_bot):
            return

        # Ignora comandos com prefixo para não colidir com outros cogs (ex: r.hug @Ralsei)
        content_stripped = message.content.strip()
        prefixes = await self.bot.get_prefix(message)
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        if any(content_stripped.startswith(p) for p in prefixes):
            return

        # Remove a menção do Ralsei do texto da mensagem
        clean_text = re.sub(rf"<@!?{bot_user.id}>", "", message.content).strip()

        # Se o usuário apenas marcou o bot sem falar nada
        if not clean_text:
            await message.reply("Olá! Em que posso te ajudar hoje? *sorri gentilmente*", mention_author=False)
            return

        channel_id = message.channel.id
        async with self.channel_locks[channel_id]:
            async with message.channel.typing():
                user_entry = {
                    "role": "user",
                    "content": f"{message.author.display_name}: {clean_text}",
                }
                response = await self.generate_response(channel_id, user_entry)
                if not response:
                    return

                # Discord possui limite de 2000 caracteres por mensagem
                if len(response) <= 2000:
                    await message.reply(response, mention_author=False)
                else:
                    chunks = [response[i:i + 1950] for i in range(0, len(response), 1950)]
                    first = True
                    for chunk in chunks:
                        if first:
                            await message.reply(chunk, mention_author=False)
                            first = False
                        else:
                            await message.channel.send(chunk)

    @commands.command(name="clearmemory", aliases=["limparmemoria", "esquecer"], help="Limpa a memória de conversa do Ralsei neste canal.")
    async def clear_memory(self, ctx: commands.Context):
        self.channel_memory.pop(ctx.channel.id, None)
        await ctx.send("Minha memória deste canal foi limpa! Podemos começar um novo assunto. 🍰")


def setup(bot: commands.Bot):
    bot.add_cog(AI(bot))