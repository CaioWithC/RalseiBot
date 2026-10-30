"""Add slash commands for blocktag, unblocktag, blocklist, and random to slash_commands.py."""
import pathlib

p = pathlib.Path(r"c:\Users\CaioWithC\Documents\RalseiBot\cogs\slash_commands.py")
content = p.read_text(encoding="utf-8")

# Add new subcommands before the closing 'def setup(bot):' at the end
old_setup = '''    @e621.subcommand(name="top", description="Ranking de tags e artistas mais pesquisados no servidor.")
    async def e621_top(self, interaction: nextcord.Interaction,
                       tipo: str = nextcord.SlashOption(
                           description="Escolha a categoria do ranking (padrão: tudo).",
                           choices=["tudo", "tags", "artistas"],
                           default="tudo",
                           required=False,
                       )):
        await self.invoke(interaction, "e621 top", tipo=tipo)


def setup(bot):
    bot.add_cog(SlashCommands(bot))'''

new_setup = '''    @e621.subcommand(name="top", description="Ranking de tags e artistas mais pesquisados no servidor.")
    async def e621_top(self, interaction: nextcord.Interaction,
                       tipo: str = nextcord.SlashOption(
                           description="Escolha a categoria do ranking (padrão: tudo).",
                           choices=["tudo", "tags", "artistas"],
                           default="tudo",
                           required=False,
                       )):
        await self.invoke(interaction, "e621 top", tipo=tipo)

    @e621.subcommand(name="blocktag", description="Bloqueie uma tag das buscas e621 neste servidor.")
    async def e621_blocktag(self, interaction: nextcord.Interaction,
                            tag: str = nextcord.SlashOption(description="Tag(s) a bloquear (separadas por espaço). Ex.: gore scat")):
        await self.invoke(interaction, "e621 blocktag", tag=tag)

    @e621.subcommand(name="unblocktag", description="Desbloqueie uma tag das buscas e621 neste servidor.")
    async def e621_unblocktag(self, interaction: nextcord.Interaction,
                              tag: str = nextcord.SlashOption(description="Tag(s) a desbloquear (separadas por espaço). Ex.: gore scat")):
        await self.invoke(interaction, "e621 unblocktag", tag=tag)

    @e621.subcommand(name="blocklist", description="Veja a lista de tags bloqueadas no servidor.")
    async def e621_blocklist(self, interaction: nextcord.Interaction):
        await self.invoke(interaction, "e621 blocklist")

    @e621.subcommand(name="random", description="Post aleatório popular do e621 (score ≥ 1000).")
    async def e621_random(self, interaction: nextcord.Interaction,
                          tags: str = nextcord.SlashOption(description="Tags opcionais para filtrar. Ex.: canine male/male", required=False, default="")):
        await self.invoke(interaction, "e621 random", tags=tags)


def setup(bot):
    bot.add_cog(SlashCommands(bot))'''

content = content.replace(old_setup, new_setup, 1)

p.write_text(content, encoding="utf-8")
print("slash_commands.py updated successfully!")

