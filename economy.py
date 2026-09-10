import random

import asyncio
import logging

import nextcord
from nextcord.ext import commands

from db import database, EconomyError
from command_support import DualCommand
from amounts import CoinAmount


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


class Economy(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(cls=DualCommand, aliases=["saldo", "atm", "bal"], help="Mostra seu saldo em DarkMoney.")
    async def balance(self, ctx):
        await ctx.send(f"{ctx.author.display_name}, seu saldo é: {database.balance(ctx.author.id):,} D$.")

    @commands.command(cls=DualCommand, help="Receba sua recompensa diária. Renova todos os dias às 00:00 (GMT-3).")
    async def daily(self, ctx):
        reward = random.randint(5000, 100000)
        balance = database.daily(ctx.author.id, reward)
        await ctx.send(f"{ctx.author.display_name}, você recebeu sua recompensa diária de {reward:,} "
                       f"D$! Seu novo saldo é: {balance:,} D$.")

    @commands.command(cls=DualCommand, aliases=["transferir", "pix", "pagar"], help="Transfira DarkMoney com aceite das duas pessoas por botão: r.pay @membro valor (ex.: 100, 10K, 1.5M)")
    @commands.guild_only()
    async def pay(self, ctx, member: nextcord.Member, amount: CoinAmount):
        if member.id == ctx.author.id:
            raise commands.BadArgument("Você não pode transferir para si mesmo.")
        if member.bot:
            raise commands.BadArgument("Bots não podem aceitar transferências.")
        database.positive(amount)
        if database.balance(ctx.author.id) < amount:
            raise EconomyError("Você não tem saldo suficiente.")
        view = PaymentRequest(ctx.author, member, amount, storage=database)
        try:
            view.message = await ctx.send(view.content(), view=view)
        except Exception:
            view.stop()
            raise

    @commands.command(cls=DualCommand, help="Trabalhe para ganhar DarkMoney: r.work")
    @commands.guild_only()
    @commands.cooldown(1, 7200, lambda message: message.author.id)
    async def work(self, ctx):
        reward = random.randint(10000, 40000)
        balance = database.add_balance(ctx.author.id, reward)
        await ctx.send(f"{ctx.author.display_name}, você trabalhou e ganhou {reward:,} D$! "
                       f"Seu novo saldo é: {balance:,} D$.")

    @commands.command(cls=DualCommand, aliases=["freelancer", "freelas", "frelas"], help="Faça um 'freelance' para ganhar DarkMoney: r.freelance")
    @commands.guild_only()
    @commands.cooldown(1, 600, lambda message: message.author.id)
    async def freelance(self, ctx):
        reward = random.randint(100, 10000)
        balance = database.add_balance(ctx.author.id, reward)
        await ctx.send(f"{ctx.author.display_name}, você fez um freelance e ganhou {reward:,} D$! "
                       f"Seu novo saldo é: {balance:,} D$.")

    @commands.command(cls=DualCommand, help="Roube DarkMoney de outro membro: r.rob @membro")
    @commands.guild_only()
    @commands.cooldown(1, 3600, lambda message: message.author.id)
    async def rob(self, ctx, member: nextcord.Member):
        if member.id == ctx.author.id:
            await ctx.send("Você não pode roubar de si mesmo.")
            return
        if database.balance(member.id) < 1000:
            await ctx.send(f"{member.display_name} não tem dinheiro suficiente para ser roubado.")
            return
        success = random.random() < 0.5
        if success:
            amount = random.randint(100, min(5000, database.balance(member.id)))
            balance = database.transfer(member.id, ctx.author.id, amount)
            await ctx.send(f"{ctx.author.display_name} roubou {amount:,} D$ de {member.display_name}! "
                           f"Novo saldo: {balance:,} D$.")
        else:
            await ctx.send(f"{ctx.author.display_name} tentou roubar {member.display_name}, mas falhou e foi pego!")

    @commands.command(cls=DualCommand, help="Administrador: r.addbalance @membro valor")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def addbalance(self, ctx, member: nextcord.Member, amount: int):
        balance = database.add_balance(member.id, amount)
        await ctx.send(f"Adicionados {amount:,} D$ para {member.display_name}. "
                       f"Novo saldo: {balance:,} D$.")

    @commands.command(cls=DualCommand, help="Administrador: r.setbalance @membro valor")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def setbalance(self, ctx, member: nextcord.Member, amount: int):
        balance = database.set_balance(member.id, amount)
        await ctx.send(f"Saldo de {member.display_name} definido para {balance:,} D$.")

    @commands.command(cls=DualCommand, help="Administrador: r.resetbalance @membro")
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    async def resetbalance(self, ctx, member: nextcord.Member):
        balance = database.reset_balance(member.id)
        await ctx.send(f"Saldo de {member.display_name} redefinido para {balance:,} D$.")

def setup(bot):
    bot.add_cog(Economy(bot))
