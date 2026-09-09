"""Roleplay embeds with one ordered GIF rotation per action."""
from itertools import cycle
import asyncio
import logging
import random

import nextcord
from nextcord.ext import commands

from command_support import DualCommand, InteractionContext
from db import database, EconomyError

# Direct GIF URLs from the supplied albums, in album order.
GIFS = {
    # https://imgur.com/a/E5nJtdx
    "kiss": tuple(f"https://i.imgur.com/{image}.gif" for image in
                  ("jKBOXO6", "uLAJwzl", "gt56AAh", "DlCh4dG", "42GKcir", "OeKHxxJ")),
    # https://imgur.com/a/gYHRVCv
    "pat": tuple(f"https://i.imgur.com/{image}.gif" for image in
                 ("GscQvfr", "WJwKX0g", "1ibD5KW", "e0sXAZr", "mmpCeXQ", "yVgH7Ox")),
    # https://imgur.com/a/PLnbgn2
    "hug": tuple(f"https://i.imgur.com/{image}.gif" for image in
                 ("Au4pWWC", "y0NRL5X", "i4heQO3", "BHzKF0s", "ypbHulf", "LKr4ppx")),
}
ACTIONS = {"kiss": ("💕", "beijou"), "hug": ("🤗", "abraçou"),
           "pat": ("🥰", "fez carinho em")}


class ReciprocateView(nextcord.ui.View):
    def __init__(self, cog, author, member, action):
        super().__init__(timeout=120)
        self.cog, self.author, self.member, self.action = cog, author, member, action
        self.message = None
        self.done = False
        self.lock = asyncio.Lock()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("Só quem recebeu a interação pode retribuir.", ephemeral=True)
            return False
        return True

    def finish(self):
        self.done = True
        self.reciprocate.disabled = True
        self.stop()

    @nextcord.ui.button(label="Retribuir", emoji="🔁", style=nextcord.ButtonStyle.primary)
    async def reciprocate(self, button, interaction):
        if not await self.interaction_check(interaction):
            return
        await interaction.response.defer()
        async with self.lock:
            if self.done:
                await interaction.followup.send("Essa interação já foi retribuída ou expirou.", ephemeral=True)
                return
            # Use the same checks, cooldowns and error handling as prefix/slash.
            bot = self.cog.bot
            ctx = InteractionContext(bot, interaction, bot.get_command(self.action), {"member": self.author})
            await bot.invoke(ctx)
            if not ctx.command_failed:
                self.finish()
                await interaction.message.edit(view=self)

    async def on_timeout(self):
        async with self.lock:
            self.finish()
            if self.message is not None:
                try:
                    await self.message.edit(view=self)
                except nextcord.HTTPException:
                    logging.getLogger(__name__).warning("Could not disable expired roleplay button")


class Roleplay(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage or database
        self.gifs = {action: random.choice(urls) for action, urls in GIFS.items()}

    async def interact(self, ctx, member, action):
        if member.id == ctx.author.id:
            raise EconomyError("Escolha outra pessoa para essa interação.")
        emoji, verb = ACTIONS[action]
        embed = nextcord.Embed(
            description=f"{emoji} <@{ctx.author.id}> {verb} <@{member.id}>",
            color=0xcf59ff,
        )
        view = ReciprocateView(self, ctx.author, member, action)
        embed.set_image(url=self.gifs[action])
        points = self.storage.add_marriage_affinity(ctx.author.id, member.id, random.randint(1, 3))
        if points:
            unit = "ponto" if points == 1 else "pontos"
            embed.set_footer(text=f"Como os dois estão casados, o casamento deles ganhou {points} {unit} de afinidade!!")
        try:
            view.message = await ctx.send(embed=embed, view=view)
        except Exception:
            view.stop()
            raise

    @commands.command(cls=DualCommand, aliases=["beijar"],
                      help="Beije alguém com um GIF: r.kiss @membro.")
    @commands.guild_only()
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def kiss(self, ctx, member: nextcord.Member):
        await self.interact(ctx, member, "kiss")

    @commands.command(cls=DualCommand, aliases=["abracar"],
                      help="Abrace alguém com um GIF: r.hug @membro.")
    @commands.guild_only()
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def hug(self, ctx, member: nextcord.Member):
        await self.interact(ctx, member, "hug")

    @commands.command(cls=DualCommand, aliases=["carinho"],
                      help="Faça carinho em alguém com um GIF: r.pat @membro.")
    @commands.guild_only()
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def pat(self, ctx, member: nextcord.Member):
        await self.interact(ctx, member, "pat")


def setup(bot):
    bot.add_cog(Roleplay(bot))
