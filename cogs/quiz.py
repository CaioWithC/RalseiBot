"""Activity-triggered quizzes and persistent, moderated question suggestions."""
import asyncio
from collections import defaultdict, deque
import json
import logging
import random
import time

import nextcord
from nextcord.ext import commands, tasks

from cogs.command_support import DualCommand
from cogs.quiz_rules import (ACTIVITY_WINDOW, DEFAULT_REWARD, MAX_INTERVAL, MIN_INTERVAL,
                             MIN_MESSAGES, MIN_PARTICIPANTS, ROUND_SECONDS, SEED_QUESTIONS,
                             suggestion_answers)
from db import EconomyError, database

log = logging.getLogger(__name__)


def review_embed(question, answers, author_id, status="Aguardando moderação"):
    embed = nextcord.Embed(title="Sugestão para o quiz", description=question, color=0x77E5BC)
    embed.add_field(name="Resposta e escritas aceitas", value="\n".join(answers), inline=False)
    embed.add_field(name="Enviado por", value=f"<@{author_id}> · ID: {author_id}", inline=False)
    embed.set_footer(text=status)
    return embed


class QuizSuggestionModal(nextcord.ui.Modal):
    def __init__(self, cog, guild_id, review_channel_id):
        super().__init__("Sugerir pergunta para o quiz", timeout=600)
        self.cog, self.guild_id, self.review_channel_id = cog, guild_id, review_channel_id
        self.question = nextcord.ui.TextInput(label="Pergunta", style=nextcord.TextInputStyle.paragraph,
                                              min_length=10, max_length=500)
        self.answer = nextcord.ui.TextInput(label="Resposta correta", max_length=100)
        self.aliases = nextcord.ui.TextInput(label="Outras escritas aceitas (uma por linha)",
            style=nextcord.TextInputStyle.paragraph, required=False, max_length=800,
            placeholder="Opcional. Ex.: seis\n6")
        for item in (self.question, self.answer, self.aliases):
            self.add_item(item)

    async def callback(self, interaction):
        await interaction.response.defer(ephemeral=True)
        async with self.cog.lock_for(self.guild_id):
            config = self.cog.storage.quiz_config(self.guild_id)
            if (interaction.guild is None or interaction.guild.id != self.guild_id
                    or not config or not config["enabled"]
                    or config["review_channel_id"] != self.review_channel_id):
                await interaction.followup.send("A configuração mudou. Abra o formulário novamente.", ephemeral=True)
                return
            channel = interaction.guild.get_channel(int(self.review_channel_id))
            if not self.cog.usable_channel(channel, private=True):
                await interaction.followup.send("O canal da equipe está indisponível. Avise um administrador.", ephemeral=True)
                return
            try:
                question = self.question.value.strip()
                if not 10 <= len(question) <= 500:
                    raise ValueError("A pergunta precisa ter entre 10 e 500 caracteres.")
                answers = suggestion_answers(self.answer.value, self.aliases.value or "")
                self.cog.storage.submit_quiz_suggestion(interaction.id, self.guild_id, interaction.user.id,
                    question, answers, channel.id, int(self.cog.clock()))
            except ValueError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
            try:
                message = await channel.send(embed=review_embed(question, answers, interaction.user.id),
                    view=self.cog.review_view, allowed_mentions=nextcord.AllowedMentions.none())
            except nextcord.HTTPException:
                self.cog.storage.mark_quiz_suggestion(interaction.id, failed=True)
                await interaction.followup.send("Não consegui enviar à equipe. Tente novamente em um minuto.", ephemeral=True)
                return
            self.cog.storage.mark_quiz_suggestion(interaction.id, message_id=message.id)
        await interaction.followup.send("Sugestão enviada! A equipe precisa aprová-la antes de entrar no quiz.", ephemeral=True)


class QuizPanel(nextcord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @nextcord.ui.button(label="Sugerir pergunta", emoji="💡", style=nextcord.ButtonStyle.green,
                        custom_id="ralseibot:quiz:suggest")
    async def suggest(self, button, interaction):
        config = self.cog.storage.quiz_config(interaction.guild.id) if interaction.guild else None
        if not config or not config["enabled"]:
            await interaction.response.send_message("O quiz não está ativado neste servidor.", ephemeral=True)
            return
        await interaction.response.send_modal(QuizSuggestionModal(
            self.cog, interaction.guild.id, config["review_channel_id"]))


class QuizReview(nextcord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def decide(self, interaction, approve):
        if (interaction.guild is None or not (interaction.user.guild_permissions.administrator
                                             or interaction.user.guild_permissions.manage_messages)):
            await interaction.response.send_message("Só moderadores com Gerenciar Mensagens podem avaliar sugestões.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        async with self.cog.lock_for(interaction.guild.id):
            try:
                row = self.cog.storage.review_quiz_suggestion(interaction.guild.id, interaction.channel_id,
                    interaction.message.id, interaction.user.id, approve)
            except EconomyError as error:
                await interaction.followup.send(str(error), ephemeral=True)
                return
        status = "Aprovada" if approve else "Recusada"
        try:
            await interaction.message.edit(embed=review_embed(row["question"], json.loads(row["answers"]),
                row["author_id"], f"{status} por {interaction.user} · ID: {interaction.user.id}"), view=None)
        except nextcord.HTTPException:
            log.warning("Could not update reviewed quiz suggestion %s", row["id"], exc_info=True)
        await interaction.followup.send(f"{status}!" + (" A pergunta entrou no quiz deste servidor." if approve else ""), ephemeral=True)

    @nextcord.ui.button(label="Aprovar", style=nextcord.ButtonStyle.green, custom_id="ralseibot:quiz:approve")
    async def approve(self, button, interaction):
        await self.decide(interaction, True)

    @nextcord.ui.button(label="Recusar", style=nextcord.ButtonStyle.red, custom_id="ralseibot:quiz:reject")
    async def reject(self, button, interaction):
        await self.decide(interaction, False)


class Quiz(commands.Cog):
    def __init__(self, bot, storage=None, *, clock=time.time, rng=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.clock = clock
        self.rng = rng or random.SystemRandom()
        self.activity = defaultdict(lambda: deque(maxlen=1000))
        self.locks = {}
        self.last_question = {}
        self.panel_view = self.review_view = None

    def lock_for(self, guild_id):
        return self.locks.setdefault(int(guild_id), asyncio.Lock())

    def next_time(self, now):
        return int(now) + self.rng.randint(MIN_INTERVAL, MAX_INTERVAL)

    @staticmethod
    def usable_channel(channel, private=False):
        if not isinstance(channel, nextcord.TextChannel) or channel.guild.me is None:
            return False
        permissions = channel.permissions_for(channel.guild.me)
        return (permissions.view_channel and permissions.send_messages and permissions.embed_links
                and (not private or not channel.permissions_for(channel.guild.default_role).view_channel))

    def register_views(self):
        if self.panel_view is None:
            self.panel_view, self.review_view = QuizPanel(self), QuizReview(self)
            self.bot.add_view(self.panel_view)
            self.bot.add_view(self.review_view)

    @commands.Cog.listener()
    async def on_ready(self):
        self.register_views()
        if not self.ticker.is_running():
            self.storage.recover_quiz_rounds()
            self.ticker.start()

    def cog_unload(self):
        self.ticker.cancel()
        for view in (self.panel_view, self.review_view):
            if view:
                view.stop()

    @commands.Cog.listener()
    async def on_message(self, message):
        if (message.guild is None or message.author.bot or message.webhook_id
                or not message.content.strip() or message.content.startswith("r.")):
            return
        async with self.lock_for(message.guild.id):
            config = self.storage.quiz_config(message.guild.id)
            if not config or not config["enabled"] or config["channel_id"] != str(message.channel.id):
                return
            now = self.clock()
            self.activity[message.guild.id].append((now, message.author.id))
            row = self.storage.quiz_round(message.guild.id)
            if not row:
                return
            try:
                reward = self.storage.answer_quiz(row["id"], message.guild.id, message.channel.id,
                    message.author.id, message.id, message.content, now)
            except EconomyError as error:
                await message.channel.send(str(error))
                return
            if reward is not None:
                try:
                    await message.channel.send(
                        f"🎉 {message.author.mention} respondeu primeiro e ganhou **{reward:,} D$**!\n"
                        f"Resposta: **{nextcord.utils.escape_markdown(json.loads(row['answers'])[0])}**",
                        allowed_mentions=nextcord.AllowedMentions.none())
                except nextcord.HTTPException:
                    log.warning("Quiz prize credited but announcement failed: %s", row["id"], exc_info=True)

    @tasks.loop(seconds=15)
    async def ticker(self):
        try:
            configs = self.storage.quiz_configs()
        except Exception:
            log.exception("Could not read quiz configuration")
            return
        for config in configs:
            try:
                await self.tick_guild(int(config["guild_id"]))
            except Exception:
                log.exception("Quiz tick failed for guild %s", config["guild_id"])

    async def tick_guild(self, guild_id):
        async with self.lock_for(guild_id):
            now = self.clock()
            config = self.storage.quiz_config(guild_id)
            if not config or not config["enabled"]:
                return
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                return
            channel = guild.get_channel(int(config["channel_id"]))
            active = self.storage.quiz_round(guild_id)
            if active:
                if self.storage.expire_quiz_round(active["id"], now) and self.usable_channel(channel):
                    await channel.send("⌛ Tempo esgotado! Ninguém acertou. Resposta: **"
                        + nextcord.utils.escape_markdown(json.loads(active["answers"])[0]) + "**.",
                        allowed_mentions=nextcord.AllowedMentions.none())
                return
            if config["next_at"] > now or not self.usable_channel(channel):
                return
            recent = self.activity[guild_id]
            while recent and recent[0][0] < now - ACTIVITY_WINDOW:
                recent.popleft()
            if len(recent) < MIN_MESSAGES or len({user_id for _, user_id in recent}) < MIN_PARTICIPANTS:
                return
            questions = [*SEED_QUESTIONS, *self.storage.approved_quiz_questions(guild_id)]
            choices = [question for question in questions if question[0] != self.last_question.get(guild_id)]
            question, answers = self.rng.choice(choices or questions)
            row = self.storage.prepare_quiz_round(guild_id, question, answers, now,
                int(now) + ROUND_SECONDS, self.next_time(now))
            if row is None:
                return
            embed = nextcord.Embed(title="🧠 Quiz relâmpago!", description=question, color=0x77E5BC)
            embed.add_field(name=f"Prêmio: {row['reward']:,} D$", value=
                f"Escreva a resposta neste chat. A primeira pessoa a acertar ganha!\n"
                f"Encerra <t:{row['expires_at']}:R>.", inline=False)
            embed.set_footer(text="Maiúsculas e acentos não fazem diferença. Responda apenas com a resposta.")
            try:
                message = await channel.send(embed=embed, allowed_mentions=nextcord.AllowedMentions.none())
                self.storage.publish_quiz_round(row["id"], message.id)
            except Exception:
                self.storage.cancel_quiz_round(row["id"])
                raise
            self.last_question[guild_id] = question
            recent.clear()

    async def send_panel(self, ctx):
        self.register_views()
        embed = nextcord.Embed(title="💡 Ajude a criar o quiz!", color=0x77E5BC,
            description="Clique em **Sugerir pergunta** e informe a pergunta e a resposta correta.\n"
                        "A equipe verá seu usuário e avaliará a sugestão antes de adicioná-la ao quiz.\n"
                        "Até 3 sugestões pendentes por pessoa; intervalo de 1 minuto entre envios.")
        await ctx.send(embed=embed, view=self.panel_view, allowed_mentions=nextcord.AllowedMentions.none())

    @commands.command(cls=DualCommand, name="quiz",
        help="Administrador: r.quiz #chat #revisao [premio]. Ativa perguntas a cada 30–60 min de chat ativo e publica o painel. Prêmio padrão: 1.000 D$; máximo: 100.000.")
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def quiz(self, ctx, channel: nextcord.TextChannel, review_channel: nextcord.TextChannel,
                   reward: int = DEFAULT_REWARD):
        self.storage.positive(reward, maximum=100_000)
        if (channel.guild.id != ctx.guild.id or review_channel.guild.id != ctx.guild.id
                or channel.id == review_channel.id or not self.usable_channel(channel)
                or not self.usable_channel(review_channel, private=True)):
            await ctx.send("Escolha dois canais de texto diferentes deste servidor. No canal da equipe, negue Ver Canal "
                           "a @everyone e libere somente a equipe. Preciso de Ver Canal, Enviar Mensagens e Inserir Links nos dois.",
                           allowed_mentions=nextcord.AllowedMentions.none())
            return
        async with self.lock_for(ctx.guild.id):
            self.storage.configure_quiz(ctx.guild.id, channel.id, review_channel.id, reward, self.next_time(self.clock()))
            self.activity.pop(ctx.guild.id, None)
        await self.send_panel(ctx)
        await ctx.send(f"Quiz ativado em {channel.mention}: **{reward:,} D$**, a cada **30–60 minutos**, "
                       "se houver pelo menos 5 mensagens de 2 pessoas nos últimos 10 minutos. "
                       f"Sugestões vão para {review_channel.mention}. Use `r.quizoff` ou `/quizoff` para desativar.")

    @commands.command(cls=DualCommand, name="quizpanel", help="Administrador: publica neste canal o botão de sugestões do quiz já configurado.")
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def quizpanel(self, ctx):
        config = self.storage.quiz_config(ctx.guild.id)
        if not config or not config["enabled"]:
            await ctx.send("Configure primeiro com `r.quiz #chat #revisao [premio]` ou `/quiz`.")
            return
        await self.send_panel(ctx)

    @commands.command(cls=DualCommand, name="quizoff", help="Administrador: desativa o quiz e cancela a rodada atual, preservando as perguntas aprovadas.")
    @commands.guild_only()
    @commands.has_guild_permissions(administrator=True)
    async def quizoff(self, ctx):
        async with self.lock_for(ctx.guild.id):
            self.storage.disable_quiz(ctx.guild.id)
            self.activity.pop(ctx.guild.id, None)
        await ctx.send("Quiz desativado; a rodada atual foi cancelada. As perguntas aprovadas continuam salvas.")


def setup(bot):
    bot.add_cog(Quiz(bot))
