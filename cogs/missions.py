"""Daily mission progress and bonus claims for the DarkMoney economy."""
import nextcord
from nextcord.ext import commands

from cogs.command_support import DualCommand
from db import database, EconomyError


class Missions(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database

    @commands.command(cls=DualCommand, aliases=["mission", "missoes", "missões"],
                      help="Veja suas missões diárias: r.missions. Resgate os bônus com r.missions claim. Renova às 00:00 GMT-3.")
    async def missions(self, ctx, action: str = "view"):
        action = action.casefold()
        if action in {"claim", "resgatar"}:
            reward, balance = self.storage.claim_missions(ctx.author.id)
            await ctx.send(f"Você resgatou {reward:,} D$ em bônus de missões! Saldo: {balance:,} D$.")
            return
        if action not in {"view", "ver"}:
            raise EconomyError("Use r.missions para ver o progresso ou r.missions claim para resgatar os bônus.")
        statuses, reset_at = self.storage.mission_status(ctx.author.id)
        embed = nextcord.Embed(title="📜 Missões diárias", color=0x77E5BC,
                              description="Complete as tarefas e ganhe bônus de DarkMoney!\n"
                                          f"Renovam <t:{reset_at}:R> (00:00 GMT-3).")
        for status in statuses:
            mission = status["mission"]
            state = ("✅ Resgatada" if status["claimed"] else
                     "🎁 Pronta para resgatar" if status["progress"] >= mission.target else "⏳ Em andamento")
            embed.add_field(name=mission.title,
                            value=f"Use `r.{mission.key}` ou `/{mission.key}` {mission.target} vez(es).\n"
                                  f"**{status['progress']}/{mission.target}** • Bônus: **{mission.reward:,} D$**\n{state}",
                            inline=False)
        embed.set_footer(text="Resgate com r.missions claim ou /missions action:claim. Bônus não resgatados expiram à meia-noite.")
        await ctx.send(embed=embed)


def setup(bot):
    bot.add_cog(Missions(bot))
