"""User info command: displays detailed embeds about a Discord user/member."""
import asyncio
import re
import typing

import nextcord
from nextcord.ext import commands

from cogs.command_support import DualCommand, InteractionContext

DEFAULT_EMBED_COLOR = 0x5865F2  # Discord Blurple


def _user_badges(user: nextcord.User) -> str:
    """Return emoji representations of the user's public flags (badges)."""
    flag_emojis = {
        "staff": "<:discordstaff:1561063809412501504>",
        "partner": "<:partner:1561063802165002280>",
        "hypesquad": "<:hypesquad:1561065441256800387>",
        "bug_hunter": "<:bughunter:1561063805537222806>",
        "hypesquad_bravery": "<:bravery:1561063812063436971>",
        "hypesquad_brilliance": "<:brilliance:1561063813325787266>",
        "hypesquad_balance": "<:balance:1561063810633175261>",
        "early_supporter": "<:earlysupporter:1561063803796324432>",
        "bug_hunter_level_2": "<:bughuntergold:1561063808095494304>",
        "verified_bot_developer": "<:verifieddeveloper:1561064942642401401>",
        "active_developer": "<:activedev:1561063806749380659>",
        "discord_certified_moderator": "<:certifiedmod:1561065162885046485>",
    }
    badges = []
    if hasattr(user, "public_flags") and user.public_flags:
        for flag_name, emoji in flag_emojis.items():
            if getattr(user.public_flags, flag_name, False):
                badges.append(emoji)
    if user.avatar and user.avatar.is_animated():
        badges.append("<:nitro:1561063814882140250>")
    return " ".join(badges) if badges else "Nenhuma"


def _relative_time(dt) -> str:
    """Format a datetime as Discord timestamp showing relative + absolute."""
    if dt is None:
        return "Desconhecida"
    ts = int(dt.timestamp())
    return f"<t:{ts}:f> ( <t:{ts}:R> )"


class AvatarLinksView(nextcord.ui.View):
    """View with direct download links for avatar formats."""

    def __init__(self, user: nextcord.User):
        super().__init__(timeout=120)
        avatar = user.avatar or user.default_avatar

        self.add_item(nextcord.ui.Button(
            label="PNG",
            url=str(avatar.with_format("png").with_size(4096).url),
            style=nextcord.ButtonStyle.link,
        ))
        self.add_item(nextcord.ui.Button(
            label="JPG",
            url=str(avatar.with_format("jpg").with_size(4096).url),
            style=nextcord.ButtonStyle.link,
        ))
        self.add_item(nextcord.ui.Button(
            label="WebP",
            url=str(avatar.with_format("webp").with_size(4096).url),
            style=nextcord.ButtonStyle.link,
        ))
        if user.avatar and user.avatar.is_animated():
            self.add_item(nextcord.ui.Button(
                label="GIF",
                url=str(user.avatar.with_format("gif").with_size(4096).url),
                style=nextcord.ButtonStyle.link,
            ))


class UserinfoView(nextcord.ui.View):
    """Buttons beneath the userinfo embeds: view avatar + view profile."""

    def __init__(self, cog, target_user, target_member, author_id):
        super().__init__(timeout=180)
        self.cog = cog
        self.target_user = target_user
        self.target_member = target_member
        self.author_id = author_id
        self.message = None

    @nextcord.ui.button(
        label="Ver o avatar global do usuário",
        style=nextcord.ButtonStyle.primary,
        row=0,
    )
    async def view_avatar(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        user = self.target_user
        avatar = user.avatar or user.default_avatar
        avatar_url = avatar.with_size(4096).url

        embed = nextcord.Embed(
            title=f"Avatar global de {user.display_name}",
            color=user.accent_color or DEFAULT_EMBED_COLOR,
        )
        embed.set_image(url=str(avatar_url))
        view = AvatarLinksView(user)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @nextcord.ui.button(
        label="Ver perfil",
        emoji="👤",
        style=nextcord.ButtonStyle.secondary,
        row=0,
    )
    async def view_profile(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        await interaction.response.defer()
        bot = self.cog.bot
        profile_cmd = bot.get_command("profile")
        if profile_cmd is None:
            await interaction.followup.send("O comando de perfil não está disponível.", ephemeral=True)
            return

        ctx = InteractionContext(
            bot, interaction, profile_cmd, {"member": self.target_user},
        )
        await bot.invoke(ctx)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except nextcord.HTTPException:
                pass


class UserInfo(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command(
        cls=DualCommand,
        name="userinfo",
        aliases=["ui", "whois", "user"],
        help="Informações detalhadas sobre um usuário: r.userinfo [@membro].",
    )
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def userinfo(
        self,
        ctx,
        *,
        member: typing.Union[nextcord.Member, nextcord.User, str] = None,
    ):
        target = member or ctx.author

        # Resolve string IDs or mentions if passed as text
        if isinstance(target, str):
            cleaned = target.strip()
            mention_match = re.match(r"^<@!?(\d+)>$", cleaned)
            user_id = int(mention_match.group(1)) if mention_match else (int(cleaned) if cleaned.isdigit() else None)
            if user_id:
                target = (
                    (ctx.guild.get_member(user_id) if ctx.guild else None)
                    or self.bot.get_user(user_id)
                )
                if target is None:
                    try:
                        target = await asyncio.wait_for(self.bot.fetch_user(user_id), timeout=5)
                    except (nextcord.HTTPException, asyncio.TimeoutError):
                        target = ctx.author
            else:
                target = ctx.author

        # Try to resolve guild member for guild-specific info
        guild_member = None
        if ctx.guild:
            guild_member = ctx.guild.get_member(target.id)
            if guild_member is None:
                try:
                    guild_member = await asyncio.wait_for(
                        ctx.guild.fetch_member(target.id), timeout=5,
                    )
                except (nextcord.HTTPException, asyncio.TimeoutError):
                    pass

        # Fetch fresh user data for accurate accent color, flags, and banner
        try:
            user = await asyncio.wait_for(self.bot.fetch_user(target.id), timeout=5)
        except (nextcord.HTTPException, asyncio.TimeoutError):
            user = getattr(target, "_user", target)

        # ── Embed 1: Informações sobre o Usuário ──
        user_embed = nextcord.Embed(
            title=user.display_name,
            url=f"https://discord.com/users/{user.id}",
            color=user.accent_color or DEFAULT_EMBED_COLOR,
        )
        user_embed.set_author(name="Informações sobre o Usuário")
        user_embed.set_thumbnail(url=user.display_avatar.with_size(256).url)

        badges = _user_badges(user)
        user_embed.add_field(name="🏅 Insígnias", value=badges, inline=True)
        user_embed.add_field(
            name="🆔 ID do Discord",
            value=f"`{user.id}`",
            inline=True,
        )
        user_embed.add_field(
            name="🏷️ Tag do Discord",
            value=f"@{user.name}",
            inline=True,
        )
        user_embed.add_field(
            name="📅 Data de Criação da Conta",
            value=_relative_time(user.created_at),
            inline=False,
        )

        embeds = [user_embed]

        # ── Embed 2: Informações sobre o Membro (guild only) ──
        if guild_member is not None:
            top_role = guild_member.top_role
            role_value = top_role.mention if top_role and top_role.name != "@everyone" else "@everyone"
            member_color = guild_member.color if guild_member.color.value else 0xE91E63

            member_embed = nextcord.Embed(
                title=guild_member.display_name,
                color=member_color,
            )
            member_embed.set_author(name="Informações sobre o Membro")
            member_embed.set_thumbnail(url=guild_member.display_avatar.with_size(256).url)

            member_embed.add_field(
                name="📅 Data de Entrada no Servidor",
                value=_relative_time(guild_member.joined_at),
                inline=True,
            )
            member_embed.add_field(
                name="🏅 Maior cargo",
                value=role_value,
                inline=True,
            )

            embeds.append(member_embed)

        view = UserinfoView(self, user, guild_member, ctx.author.id)
        msg = await ctx.send(embeds=embeds, view=view)
        if msg:
            view.message = msg


def setup(bot):
    bot.add_cog(UserInfo(bot))
