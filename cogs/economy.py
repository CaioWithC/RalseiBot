import random
import asyncio
import logging
import uuid
from datetime import datetime
import typing

import nextcord
from nextcord.ext import commands

from db import DAILY_TIMEZONE, database, EconomyError
from cogs.command_support import DualCommand
from cogs.amounts import CoinAmount
from cogs.job_rules import (
    Job, get_available_jobs, find_job,
    get_level_info, format_progress_bar, get_shift_info
)


log = logging.getLogger(__name__)


class PaymentRequest(nextcord.ui.View):
    def __init__(self, sender, receiver, amount, *, storage):
        super().__init__(timeout=120)
        self.sender = sender
        self.receiver = receiver
        self.amount = amount
        self.storage = storage
        self.participants = (sender.id, receiver.id)
        self.confirmed = set()
        self.lock = asyncio.Lock()
        self.message = None
        self.done = False
        self.result = None

    def content(self):
        if self.result is not None:
            return self.result
        status = "\n".join(
            f"<@{user_id}>: {'aceitou' if user_id in self.confirmed else 'aguardando aceite'}"
            for user_id in self.participants
        )
        return (f"<@{self.sender.id}> quer transferir {self.amount:,} D$ para <@{self.receiver.id}>.\n"
                f"{status}\nAmbos precisam clicar em Aceitar para concluir a transferência. "
                "Qualquer um pode cancelar. Expira após 2 minutos sem interação.")

    def finish(self, result):
        self.done = True
        self.result = result
        for item in self.children:
            item.disabled = True
        self.stop()

    async def interaction_check(self, interaction):
        if interaction.user.id not in self.participants:
            await interaction.response.send_message(
                "Só as duas pessoas desta transferência podem responder.", ephemeral=True)
            return False
        return True

    async def respond(self, interaction, *, accept):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self.lock:
            if self.done:
                await interaction.followup.send("Esta transferência já foi encerrada.", ephemeral=True)
                return
            if not accept:
                self.finish(f"<@{interaction.user.id}> cancelou a transferência. Nenhuma moeda foi transferida.")
            else:
                if interaction.user.id in self.confirmed:
                    await interaction.followup.send("Você já aceitou. Aguarde a outra pessoa.", ephemeral=True)
                    return
                self.confirmed.add(interaction.user.id)
                self.confirm.label = f"Aceitar ({len(self.confirmed)}/2)"
                if len(self.confirmed) == 2:
                    try:
                        balance = self.storage.transfer(*self.participants, self.amount)
                    except EconomyError as error:
                        self.finish(f"Transferência cancelada: {error}")
                    else:
                        self.finish(f"{self.sender.display_name} transferiu {self.amount:,} D$ para "
                                    f"{self.receiver.display_name}. Novo saldo: {balance:,} D$.")
            await interaction.message.edit(content=self.content(), view=self)

    @nextcord.ui.button(label="Aceitar (0/2)", style=nextcord.ButtonStyle.success)
    async def confirm(self, button, interaction):
        await self.respond(interaction, accept=True)

    @nextcord.ui.button(label="Cancelar", style=nextcord.ButtonStyle.danger)
    async def cancel(self, button, interaction):
        await self.respond(interaction, accept=False)

    async def on_timeout(self):
        async with self.lock:
            if self.done:
                return
            self.finish("A transferência expirou sem os dois aceites. Nenhuma moeda foi transferida.")
            if self.message is not None:
                try:
                    await self.message.edit(content=self.content(), view=self)
                except nextcord.HTTPException:
                    log.warning("Could not update expired payment request")

    async def on_error(self, error, item, interaction):
        log.error("Payment request failed", exc_info=(type(error), error, error.__traceback__))
        async with self.lock:
            if not self.done:
                self.finish("A transferência foi interrompida por um erro. Consulte seu saldo com r.balance.")
            # Preserve the outcome if sending the receipt failed after the transfer.
            result = self.content()
        try:
            if interaction.response.is_done():
                await interaction.followup.send(result, ephemeral=True)
            else:
                await interaction.response.send_message(result, ephemeral=True)
            if self.message is not None:
                await self.message.edit(content=result, view=self)
        except nextcord.HTTPException:
            log.warning("Could not report payment request outcome")


def build_job_menu_embed(author, category: str, available_jobs: list, user_stats: dict, hour: int) -> nextcord.Embed:
    shift_name, shift_emoji = get_shift_info(hour)
    now_str = f"{hour:02d}:00"
    if category == "work":
        title = "💼 Mercado de Trabalho • Vagas Abertas"
        action_name = "trabalhar"
    else:
        title = "🧩 Painel de Freelance • Bicos Disponíveis"
        action_name = "fazer um freelance"

    lines = [
        f"🕒 **Horário atual:** {now_str} (Turno da {shift_name} {shift_emoji})",
        f"Selecione uma vaga no menu abaixo para {action_name}:\n",
    ]

    for job in available_jobs:
        xp, level = user_stats.get(job.id, (0, 1))
        _, rank_title, bonus_pct, _, _, _ = get_level_info(xp)
        bonus_text = f" • Bônus: +{int(bonus_pct * 100)}%" if bonus_pct > 0 else ""
        lines.append(
            f"{job.emoji} **{job.title}** (`{job.id}`)\n"
            f"• **Horário:** {job.hours_display} | **Ganhos:** {job.min_reward:,} a {job.max_reward:,} D$\n"
            f"• **Seu Nível:** Nível {level} ({rank_title}){bonus_text} • {xp} XP\n"
            f"• *{job.description}*\n"
        )

    return nextcord.Embed(title=title, description="\n".join(lines), color=0x77E5BC)


class JobSelect(nextcord.ui.Select):
    def __init__(self, parent_view: "JobSelectView"):
        self.parent_view = parent_view
        options = []
        for job in parent_view.available_jobs:
            xp, level = parent_view.user_stats.get(job.id, (0, 1))
            _, rank_title, bonus_pct, _, _, _ = get_level_info(xp)
            bonus_str = f" (+{int(bonus_pct * 100)}%)" if bonus_pct > 0 else ""
            desc = f"Nív. {level} {rank_title}{bonus_str} • {job.min_reward:,} a {job.max_reward:,} D$"
            options.append(
                nextcord.SelectOption(
                    label=job.title[:100],
                    value=job.id,
                    description=desc[:100],
                    emoji=job.emoji,
                )
            )
        placeholder = (
            "Escolha uma vaga para trabalhar..."
            if parent_view.category == "work"
            else "Escolha um freelance para realizar..."
        )
        custom_id = f"job_select:{parent_view.category}:{uuid.uuid4().hex}"
        super().__init__(
            custom_id=custom_id,
            placeholder=placeholder,
            min_values=1,
            max_values=1,
            options=options,
        )

    async def callback(self, interaction: nextcord.Interaction):
        await self.parent_view.choose_job(interaction, self.values[0])


class JobSelectView(nextcord.ui.View):
    def __init__(self, author, category: str, available_jobs: list, user_stats: dict, ctx, *, storage=None, timeout: float = 60):
        super().__init__(timeout=timeout)
        self.author = author
        self.category = category
        self.available_jobs = available_jobs
        self.user_stats = user_stats
        self.ctx = ctx
        self.storage = storage if storage is not None else database
        self.lock = asyncio.Lock()
        self.message = None
        self.done = False

        self.select = JobSelect(self)
        self.add_item(self.select)

    async def interaction_check(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "Apenas a pessoa que usou o comando pode escolher uma vaga.", ephemeral=True
            )
            return False
        return True

    async def choose_job(self, interaction: nextcord.Interaction, job_id: str):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self.lock:
            if self.done:
                await interaction.followup.send("Esta escolha já foi finalizada.", ephemeral=True)
                return
            self.done = True
            for child in self.children:
                child.disabled = True
            self.stop()

            job = next((j for j in self.available_jobs if j.id == job_id), None)
            if job is None:
                await interaction.followup.send("Vaga não encontrada ou não está mais disponível.", ephemeral=True)
                return

            embed = self.build_result_embed(job)
            if self.message:
                try:
                    await self.message.edit(embed=embed, view=self)
                except nextcord.HTTPException:
                    log.warning("Could not edit message with job result")
            elif interaction.message:
                try:
                    await interaction.message.edit(embed=embed, view=self)
                except nextcord.HTTPException:
                    pass

    def build_result_embed(self, job: Job) -> nextcord.Embed:
        xp, level = self.storage.get_job_experience(self.author.id, self.category, job.id)
        level, rank_title, bonus_pct, _, _, _ = get_level_info(xp)

        base_reward = random.randint(job.min_reward, job.max_reward)
        bonus_amount = int(base_reward * bonus_pct)
        total_reward = base_reward + bonus_amount

        result = self.storage.record_job_work(self.author.id, self.category, job.id, total_reward)
        new_xp = result["new_xp"]
        new_level = result["new_level"]
        leveled_up = result["leveled_up"]
        balance = result["balance"]

        new_level_num, new_rank_title, _, _, _, _ = get_level_info(new_xp)
        bar = format_progress_bar(new_xp)

        if self.category == "work":
            title = f"💼 Trabalho concluído • {job.title}"
            verb = "trabalhou como"
        else:
            title = f"🧩 Freelance concluído • {job.title}"
            verb = "concluiu o freelance"

        bonus_detail = (
            f"\n*(Base: {base_reward:,} D$ + Bônus Nível {level} [{rank_title}]: {bonus_amount:,} D$)*"
            if bonus_amount > 0 else ""
        )
        level_up_msg = (
            f"\n\n🎉 **PARABÉNS!** Você subiu para o **Nível {new_level} ({new_rank_title})** nesta vaga!"
            if leveled_up else ""
        )

        desc = (
            f"{self.author.mention} {verb} **{job.title}** {job.emoji} e ganhou **{total_reward:,} D$**!{bonus_detail}\n\n"
            f"⭐ **Experiência na vaga:**\n"
            f"Nível {new_level_num} • **{new_rank_title}**\n"
            f"Progresso: {bar}{level_up_msg}\n\n"
            f"💰 Seu novo saldo é **{balance:,} D$**."
        )
        return nextcord.Embed(title=title, description=desc, color=0x77E5BC)

    async def on_timeout(self):
        async with self.lock:
            if self.done:
                return
            self.done = True
            for child in self.children:
                child.disabled = True
            self.stop()
            if self.ctx and hasattr(self.ctx, "command") and self.ctx.command:
                self.ctx.command.reset_cooldown(self.ctx)
            if self.message:
                try:
                    embed = nextcord.Embed(
                        title="⏰ Tempo esgotado",
                        description=f"{self.author.mention}, você não escolheu uma vaga a tempo.\nO tempo de espera (cooldown) foi cancelado para você poder tentar novamente quando quiser!",
                        color=0x77E5BC,
                    )
                    await self.message.edit(embed=embed, view=self)
                except nextcord.HTTPException:
                    log.warning("Could not update expired job menu")


class Economy(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self._storage = storage

    @property
    def storage(self):
        return self._storage if self._storage is not None else database

    @storage.setter
    def storage(self, value):
        self._storage = value

    def money_embed(self, title: str, description: str, color: int = 0x77E5BC) -> nextcord.Embed:
        return nextcord.Embed(title=title, description=description, color=color)

    @commands.command(cls=DualCommand, aliases=["saldo", "atm", "bal"], help="Mostra seu saldo em DarkMoney.")
    async def balance(self, ctx):
        embed = self.money_embed(
            "💰 Saldo atual",
            f"{ctx.author.mention}, seu saldo atual é **{self.storage.balance(ctx.author.id):,} D$**.",
        )
        await ctx.send(embed=embed)

    @commands.command(cls=DualCommand, help="Receba sua recompensa diária. Renova todos os dias às 00:00 (GMT-3).")
    async def daily(self, ctx):
        reward = random.randint(5000, 100000)
        balance = self.storage.daily(ctx.author.id, reward)
        embed = self.money_embed(
            "🎁 Recompensa diária",
            f"{ctx.author.mention} recebeu **{reward:,} D$**!\n"
            f"Seu novo saldo é **{balance:,} D$**.",
        )
        await ctx.send(embed=embed)

    @commands.command(cls=DualCommand, aliases=["transferir", "pix", "pagar"], help="Transfira DarkMoney com aceite das duas pessoas por botão: r.pay @membro valor (ex.: 100, 10K, 1.5M)")
    async def pay(self, ctx, member: typing.Union[nextcord.Member, nextcord.User], amount: CoinAmount):
        if member.id == ctx.author.id:
            raise commands.BadArgument("Você não pode transferir para si mesmo.")
        if member.bot:
            raise commands.BadArgument("Bots não podem aceitar transferências.")
        self.storage.positive(amount)
        if self.storage.balance(ctx.author.id) < amount:
            raise EconomyError("Você não tem saldo suficiente.")
        view = PaymentRequest(ctx.author, member, amount, storage=self.storage)
        try:
            view.message = await ctx.send(view.content(), view=view)
        except Exception:
            view.stop()
            raise

    async def handle_job_command(self, ctx, category: str, vaga_arg: str = None):
        now = datetime.now(DAILY_TIMEZONE)
        hour = now.hour
        available = get_available_jobs(category, hour)
        user_stats = self.storage.get_user_job_stats(ctx.author.id, category)

        if vaga_arg:
            job = find_job(category, vaga_arg)
            if job is None:
                if ctx.command:
                    ctx.command.reset_cooldown(ctx)
                open_jobs_str = ", ".join(f"`{j.id}`" for j in available)
                embed = self.money_embed(
                    "⚠️ Vaga não encontrada",
                    f"A vaga `{vaga_arg}` não existe.\n"
                    f"Vagas abertas agora: {open_jobs_str}\n\n"
                    f"O cooldown foi cancelado. Use `{ctx.prefix}{ctx.invoked_with}` para abrir o menu interativo."
                )
                await ctx.send(embed=embed)
                return

            if not job.is_available(hour):
                if ctx.command:
                    ctx.command.reset_cooldown(ctx)
                shift_name, shift_emoji = get_shift_info(hour)
                open_jobs_str = "\n".join(f"• `{j.id}`: {j.title} ({j.hours_display})" for j in available)
                embed = self.money_embed(
                    "⚠️ Vaga indisponível neste horário",
                    f"A vaga **{job.title}** {job.emoji} funciona das **{job.hours_display}**.\n"
                    f"Horário atual: {hour:02d}:00 (Turno da {shift_name} {shift_emoji}).\n\n"
                    f"**Vagas abertas agora:**\n{open_jobs_str}\n\n"
                    f"O cooldown foi cancelado. Escolha uma vaga aberta no menu ou tente novamente no horário dela."
                )
                await ctx.send(embed=embed)
                return

            view = JobSelectView(ctx.author, category, [job], user_stats, ctx, storage=self.storage)
            embed = view.build_result_embed(job)
            await ctx.send(embed=embed)
            return

        embed = build_job_menu_embed(ctx.author, category, available, user_stats, hour)
        view = JobSelectView(ctx.author, category, available, user_stats, ctx, storage=self.storage)
        view.message = await ctx.send(embed=embed, view=view)

    @commands.command(cls=DualCommand, help="Escolha uma vaga aberta para trabalhar e ganhar DarkMoney: r.work [vaga]")
    @commands.cooldown(1, 7200, lambda message: message.author.id)
    async def work(self, ctx, *, vaga: str = None):
        await self.handle_job_command(ctx, "work", vaga)

    @commands.command(cls=DualCommand, aliases=["freelancer", "freelas", "frelas"], help="Faça um 'freelance' para ganhar DarkMoney: r.freelance [vaga]")
    @commands.cooldown(1, 600, lambda message: message.author.id)
    async def freelance(self, ctx, *, vaga: str = None):
        await self.handle_job_command(ctx, "freelance", vaga)

    @commands.command(cls=DualCommand, help="Roube DarkMoney de outro membro: r.rob @membro")
    @commands.cooldown(1, 3600, lambda message: message.author.id)
    async def rob(self, ctx, member: typing.Union[nextcord.Member, nextcord.User]):
        if member.id == ctx.author.id:
            await ctx.send(embed=self.money_embed("⚠️ Roubo inválido", "Você não pode roubar de si mesmo."))
            return
        if database.balance(member.id) < 1000:
            embed = self.money_embed(
                "⚠️ Roubo indisponível",
                f"{member.mention} não tem dinheiro suficiente para ser roubado.",
            )
            await ctx.send(embed=embed)
            return
        success = random.random() < 0.5
        if success:
            amount = random.randint(100, min(5000, database.balance(member.id)))
            balance = database.transfer(member.id, ctx.author.id, amount)
            embed = self.money_embed(
                "💸 Roubo bem-sucedido",
                f"{ctx.author.mention} roubou **{amount:,} D$** de {member.mention}!\n"
                f"Novo saldo: **{balance:,} D$**.",
            )
            await ctx.send(embed=embed)
        else:
            embed = self.money_embed(
                "🚫 Roubo falhou",
                f"{ctx.author.mention} tentou roubar {member.mention}, mas falhou e foi pego!",
            )
            await ctx.send(embed=embed)

    @commands.command(cls=DualCommand, help="Administrador: r.addbalance @membro valor")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def addbalance(self, ctx, member: nextcord.Member, amount: int):
        balance = database.add_balance(member.id, amount)
        embed = self.money_embed(
            "💰 Saldo ajustado",
            f"Adicionados **{amount:,} D$** para {member.mention}.\n"
            f"Novo saldo: **{balance:,} D$**.",
        )
        await ctx.send(embed=embed)

    @commands.command(cls=DualCommand, help="Administrador: r.setbalance @membro valor")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setbalance(self, ctx, member: nextcord.Member, amount: int):
        balance = database.set_balance(member.id, amount)
        embed = self.money_embed(
            "💰 Saldo definido",
            f"Saldo de {member.mention} definido para **{balance:,} D$**.",
        )
        await ctx.send(embed=embed)

    @commands.command(cls=DualCommand, help="Administrador: r.resetbalance @membro")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def resetbalance(self, ctx, member: nextcord.Member):
        balance = database.reset_balance(member.id)
        embed = self.money_embed(
            "💰 Saldo redefinido",
            f"Saldo de {member.mention} redefinido para **{balance:,} D$**.",
        )
        await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(Economy(bot))
