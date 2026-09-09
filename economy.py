import random

import nextcord
from nextcord.ext import commands

from db import database
from command_support import DualCommand
from amounts import CoinAmount


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

    @commands.command(cls=DualCommand, aliases=["transferir", "pix", "pagar"], help="Transfira DarkMoney: r.pay @membro valor (ex.: 100, 10K, 1.5M)")
    @commands.guild_only()
    async def pay(self, ctx, member: nextcord.Member, amount: CoinAmount):
        balance = database.transfer(ctx.author.id, member.id, amount)
        await ctx.send(f"{ctx.author.display_name} transferiu {amount:,} D$ para "
                       f"{member.display_name}. Novo saldo: {balance:,} D$.")

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
