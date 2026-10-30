"""e621 booru search commands and guild rankings for RalseiBot."""
import logging
import os
import random
from typing import List, Optional

import aiohttp
import nextcord
from nextcord.ext import commands

from db import database
from cogs.command_support import DualCommand, DualGroup

log = logging.getLogger(__name__)

E621_API_URL = "https://e621.net/posts.json"
E621_COLOR = 0x012E57
E621_ICON = "https://e621.net/favicon.ico"
USER_AGENT = "RalseiBot/1.0 (by CaioWithC on e621)"


# ---------------------------------------------------------------------------
# Pagination View (Search Results)
# ---------------------------------------------------------------------------

class E621PaginatorView(nextcord.ui.View):
    """Arrow-button paginator for e621 search results."""

    def __init__(self, posts: List[dict], tags: str, search_type: str,
                 author_id: int, *, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.posts = posts
        self.tags = tags
        self.search_type = search_type
        self.author_id = author_id
        self.index = 0
        self.message: Optional[nextcord.Message] = None
        # Remove the video button for image searches
        if search_type != "video":
            self.remove_item(self.send_video)
        self._update_buttons()

    # -- helpers --

    def _update_buttons(self):
        self.first_page.disabled = self.index == 0
        self.prev_page.disabled = self.index == 0
        self.next_page.disabled = self.index >= len(self.posts) - 1
        self.last_page.disabled = self.index >= len(self.posts) - 1

    def _build_embed(self) -> nextcord.Embed:
        post = self.posts[self.index]
        return build_e621_embed(post, self.tags, self.search_type,
                                self.index, len(self.posts))

    async def _is_author(self, interaction: nextcord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Somente quem pesquisou pode trocar de post.", ephemeral=True)
            return False
        return True

    async def _update(self, interaction: nextcord.Interaction):
        self._update_buttons()
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True  # type: ignore[union-attr]
        if self.message:
            try:
                await self.message.edit(view=self)
            except nextcord.NotFound:
                pass

    # -- buttons --

    @nextcord.ui.button(emoji="⏪", style=nextcord.ButtonStyle.secondary)
    async def first_page(self, button, interaction):
        if not await self._is_author(interaction):
            return
        self.index = 0
        await self._update(interaction)

    @nextcord.ui.button(emoji="◀️", style=nextcord.ButtonStyle.primary)
    async def prev_page(self, button, interaction):
        if not await self._is_author(interaction):
            return
        self.index = max(0, self.index - 1)
        await self._update(interaction)

    @nextcord.ui.button(emoji="▶️", style=nextcord.ButtonStyle.primary)
    async def next_page(self, button, interaction):
        if not await self._is_author(interaction):
            return
        self.index = min(len(self.posts) - 1, self.index + 1)
        await self._update(interaction)

    @nextcord.ui.button(emoji="⏩", style=nextcord.ButtonStyle.secondary)
    async def last_page(self, button, interaction):
        if not await self._is_author(interaction):
            return
        self.index = len(self.posts) - 1
        await self._update(interaction)

    @nextcord.ui.button(emoji="🗑️", style=nextcord.ButtonStyle.danger)
    async def delete_msg(self, button, interaction):
        if not await self._is_author(interaction):
            return
        if self.message:
            try:
                await self.message.delete()
            except nextcord.NotFound:
                pass
        self.stop()

    @nextcord.ui.button(label="Ver Vídeo", emoji="🎬", style=nextcord.ButtonStyle.success)
    async def send_video(self, button, interaction):
        if not await self._is_author(interaction):
            return
        post = self.posts[self.index]
        file_url = post.get("file", {}).get("url")
        if file_url:
            await interaction.response.send_message(file_url)
        else:
            await interaction.response.send_message(
                "URL do vídeo não disponível.", ephemeral=True)


# ---------------------------------------------------------------------------
# Ranking View (Top Tags / Artists)
# ---------------------------------------------------------------------------

class E621TopView(nextcord.ui.View):
    """Interactive tabs for guild e621 tag and artist rankings."""

    def __init__(self, guild: nextcord.Guild, mode: str = "tudo",
                 author_id: int = 0, *, timeout: float = 180.0):
        super().__init__(timeout=timeout)
        self.guild = guild
        self.mode = mode
        self.author_id = author_id
        self.message: Optional[nextcord.Message] = None
        self._update_buttons()

    def _update_buttons(self):
        self.btn_all.disabled = (self.mode == "tudo")
        self.btn_all.style = nextcord.ButtonStyle.primary if self.mode == "tudo" else nextcord.ButtonStyle.secondary

        self.btn_tags.disabled = (self.mode == "tags")
        self.btn_tags.style = nextcord.ButtonStyle.primary if self.mode == "tags" else nextcord.ButtonStyle.secondary

        self.btn_artists.disabled = (self.mode == "artistas")
        self.btn_artists.style = nextcord.ButtonStyle.primary if self.mode == "artistas" else nextcord.ButtonStyle.secondary

    @staticmethod
    def _format_item(rank: int, name: str, count: int, max_count: int = 1) -> str:
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        medal = medals.get(rank, f"`{rank:02d}.`")
        filled = max(1, round((count / max(1, max_count)) * 6)) if max_count > 0 else 0
        bar = "▰" * filled + "▱" * (6 - filled)
        unit = "pesquisa" if count == 1 else "pesquisas"
        return f"{medal} `{name}` — **{count}** {unit}  `{bar}`"

    def build_embed(self) -> nextcord.Embed:
        guild_id = str(self.guild.id)
        summary = database.get_e621_stats_summary(guild_id)

        if self.mode == "tags":
            top_tags = database.get_top_e621(guild_id, category="tag", limit=15)
            embed = nextcord.Embed(
                title=f"🏷️ Top Tags Mais Pesquisadas — {self.guild.name}",
                color=E621_COLOR,
            )
            if top_tags:
                max_c = top_tags[0][1]
                lines = [self._format_item(i + 1, tag, cnt, max_c) for i, (tag, cnt) in enumerate(top_tags)]
                embed.description = "\n".join(lines)
            else:
                embed.description = (
                    "*(Nenhuma tag registrada ainda neste servidor.)*\n\n"
                    "💡 Use `r.e621 image <tags>` ou `r.e621 video <tags>` para começar!"
                )
            embed.set_footer(
                text=f"Total de {summary['distinct_tags']} tags únicas • {summary['total_tags']} buscas no servidor",
                icon_url=E621_ICON,
            )

        elif self.mode == "artistas":
            top_artists = database.get_top_e621(guild_id, category="artist", limit=15)
            embed = nextcord.Embed(
                title=f"🎨 Top Artistas Mais Pesquisados — {self.guild.name}",
                color=E621_COLOR,
            )
            if top_artists:
                max_c = top_artists[0][1]
                lines = [self._format_item(i + 1, art, cnt, max_c) for i, (art, cnt) in enumerate(top_artists)]
                embed.description = "\n".join(lines)
            else:
                embed.description = (
                    "*(Nenhum artista registrado ainda neste servidor.)*\n\n"
                    "💡 Pesquise com `r.e621 image artist:<nome>` ou inclua o nome do artista nas tags!"
                )
            embed.set_footer(
                text=f"Total de {summary['distinct_artists']} artistas únicos • {summary['total_artists']} buscas no servidor",
                icon_url=E621_ICON,
            )

        else:  # "tudo"
            top_tags = database.get_top_e621(guild_id, category="tag", limit=10)
            top_artists = database.get_top_e621(guild_id, category="artist", limit=10)

            embed = nextcord.Embed(
                title=f"📊 Ranking e621 do Servidor — {self.guild.name}",
                description="Tags e artistas mais buscados nos comandos `r.e621` deste servidor:",
                color=E621_COLOR,
            )

            # Field: Top Tags
            if top_tags:
                max_c = top_tags[0][1]
                tag_lines = [self._format_item(i + 1, tag, cnt, max_c) for i, (tag, cnt) in enumerate(top_tags)]
                embed.add_field(name="🏷️ Top 10 Tags", value="\n".join(tag_lines), inline=False)
            else:
                embed.add_field(
                    name="🏷️ Top 10 Tags",
                    value="*(Nenhuma tag registrada)*\nComece usando `r.e621 image <tags>`",
                    inline=False,
                )

            # Field: Top Artists
            if top_artists:
                max_c = top_artists[0][1]
                art_lines = [self._format_item(i + 1, art, cnt, max_c) for i, (art, cnt) in enumerate(top_artists)]
                embed.add_field(name="🎨 Top 10 Artistas", value="\n".join(art_lines), inline=False)
            else:
                embed.add_field(
                    name="🎨 Top 10 Artistas",
                    value="*(Nenhum artista registrado)*\nBusque com `artist:nome` ou nome do artista",
                    inline=False,
                )

            embed.set_footer(
                text=f"Servidor: {self.guild.name} • {summary['distinct_tags']} tags • {summary['distinct_artists']} artistas",
                icon_url=E621_ICON,
            )

        if self.guild.icon:
            embed.set_thumbnail(url=self.guild.icon.url)
        return embed

    async def _handle_click(self, interaction: nextcord.Interaction, new_mode: str):
        if self.author_id and interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Apenas quem abriu o ranking pode trocar as abas.", ephemeral=True
            )
            return
        self.mode = new_mode
        self._update_buttons()
        embed = self.build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except nextcord.NotFound:
                pass

    @nextcord.ui.button(label="Geral", emoji="📊", style=nextcord.ButtonStyle.primary)
    async def btn_all(self, button, interaction):
        await self._handle_click(interaction, "tudo")

    @nextcord.ui.button(label="Tags", emoji="🏷️", style=nextcord.ButtonStyle.secondary)
    async def btn_tags(self, button, interaction):
        await self._handle_click(interaction, "tags")

    @nextcord.ui.button(label="Artistas", emoji="🎨", style=nextcord.ButtonStyle.secondary)
    async def btn_artists(self, button, interaction):
        await self._handle_click(interaction, "artistas")


# ---------------------------------------------------------------------------
# Embed builder
# ---------------------------------------------------------------------------

def build_e621_embed(post: dict, tags: str, search_type: str,
                     index: int, total: int) -> nextcord.Embed:
    """Build a Discord embed for a single e621 post."""
    file_info = post.get("file", {})
    file_url = file_info.get("url")
    sample = post.get("sample", {})
    sample_url = sample.get("url")
    preview = post.get("preview", {})
    preview_url = preview.get("url")

    score = post.get("score", {}).get("total", 0)
    fav_count = post.get("fav_count", 0)
    rating_raw = post.get("rating", "?")
    rating_map = {"s": "Safe", "q": "Questionable", "e": "Explicit"}
    rating_label = rating_map.get(rating_raw, rating_raw)
    post_id = post.get("id", "?")
    artist_tags = post.get("tags", {}).get("artist", [])
    artist = ", ".join(artist_tags) if artist_tags else "Desconhecido"

    title = f"e621 — {'Vídeo' if search_type == 'video' else 'Imagem'}"
    post_url = f"https://e621.net/posts/{post_id}"

    embed = nextcord.Embed(
        title=title,
        url=post_url,
        color=E621_COLOR,
    )
    embed.add_field(name="Artista", value=artist, inline=True)
    embed.add_field(name="Score", value=f"⬆️ {score}", inline=True)
    embed.add_field(name="Favoritos", value=f"❤️ {fav_count}", inline=True)
    embed.add_field(name="Rating", value=rating_label, inline=True)
    embed.add_field(name="Resolução",
                    value=f"{file_info.get('width', '?')}×{file_info.get('height', '?')}",
                    inline=True)
    embed.add_field(name="ID", value=str(post_id), inline=True)

    if search_type == "video":
        # Videos can't be embedded as image; show preview thumbnail + link
        if preview_url:
            embed.set_image(url=preview_url)
        if file_url:
            embed.description = f"**[▶️ Assistir Vídeo]({file_url})**"
    else:
        # For images, use the sample (smaller) if available, else the full file
        display_url = sample_url or file_url
        if display_url:
            embed.set_image(url=display_url)

    embed.set_footer(
        text=f"Post {index + 1}/{total} • Tags: {tags}",
        icon_url=E621_ICON,
    )
    return embed


# ---------------------------------------------------------------------------
# API helper
# ---------------------------------------------------------------------------

async def search_e621(tags: str, search_type: str, limit: int = 50,
                     blocked_tags: List[str] = ()) -> List[dict]:
    """Search e621 for posts matching *tags* and filter by type."""
    username = os.getenv("E621_USERNAME", "")
    api_key = os.getenv("E621_API_KEY", "")

    # Inject type filter into the tag string
    if search_type == "video":
        query = f"{tags} type:webm"
    else:
        query = f"{tags} -type:webm -type:swf"

    # Append guild-blocked tags as exclusions
    for bt in blocked_tags:
        bt = bt.strip()
        if bt and not bt.startswith("-"):
            query += f" -{bt}"

    headers = {"User-Agent": USER_AGENT}
    params = {"tags": query, "limit": limit}

    auth = aiohttp.BasicAuth(username, api_key) if username and api_key else None
    timeout = aiohttp.ClientTimeout(total=12)

    async with aiohttp.ClientSession(timeout=timeout, auth=auth) as session:
        async with session.get(E621_API_URL, headers=headers, params=params) as resp:
            if resp.status != 200:
                text = await resp.text()
                log.warning("e621 API returned %d: %s", resp.status, text[:300])
                return []
            data = await resp.json()

    posts = data.get("posts", [])
    # Filter out posts with null file URL (deleted / unavailable)
    posts = [p for p in posts if p.get("file", {}).get("url")]
    random.shuffle(posts)
    return posts


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Booru(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @staticmethod
    def _record_search(guild_id: str, tags: str, posts: List[dict]):
        """Parse query tags and record searched tags and artists in the database."""
        if not guild_id or not tags:
            return

        ignored_artists = {
            "conditional_dnp",
            "sound_warning",
            "third-party_edit",
            "epilepsy_warning",
            "avoid_posting",
            "tagme",
        }
        artists_in_results = set()
        for p in posts:
            for art in p.get("tags", {}).get("artist", []):
                art_clean = art.strip().lower()
                if art_clean and art_clean not in ignored_artists:
                    artists_in_results.add(art_clean)

        system_prefixes = {
            "order", "sort", "rating", "score", "favcount", "type", "filetype",
            "status", "id", "date", "age", "limit", "width", "height", "mpixels",
            "ratio", "filesize", "duration", "tagcount", "gentags", "arttags",
            "chartags", "copytags", "spectags", "pool", "set", "parent", "child",
            "deleted", "pending", "flagged", "uploader", "approver", "commenter",
            "commentary", "note", "noteprovider", "description", "source", "md5",
        }

        searched_tags = set()
        searched_artists = set()

        for term in tags.strip().split():
            t = term.strip().lower()
            if not t or t.startswith("-") or t.startswith("~"):
                continue

            if t.startswith("artist:") or t.startswith("by:"):
                _, _, art_name = t.partition(":")
                art_name = art_name.strip()
                if art_name and art_name not in ignored_artists:
                    searched_artists.add(art_name)
                continue

            if ":" in t:
                prefix, _, val = t.partition(":")
                prefix = prefix.strip()
                val = val.strip()
                if prefix in system_prefixes:
                    continue
                if prefix in ("character", "char", "species", "spec", "copyright", "copy", "lore", "general", "gen"):
                    if val:
                        searched_tags.add(val)
                    continue
                if val:
                    searched_tags.add(t)
                continue

            if t in artists_in_results:
                searched_artists.add(t)
            else:
                searched_tags.add(t)

        try:
            database.record_e621_search(guild_id, tags=searched_tags, artists=searched_artists)
        except Exception:
            log.exception("Erro ao gravar estatísticas de busca do e621 para a guild %s", guild_id)

    @commands.group(
        cls=DualGroup,
        name="e621",
        help="Pesquise imagens, vídeos ou rankings no e621: r.e621 image <tags>, r.e621 video <tags> ou r.e621 top.",
        invoke_without_command=True,
    )
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def e621(self, ctx, *, args: str = None):
        """Fallback when no subcommand is given."""
        await ctx.send(
            "Use `r.e621 image <tags>` para imagens, `r.e621 video <tags>` para vídeos ou `r.e621 top` para o ranking de buscas.\n"
            "Exemplo: `r.e621 image male/male -solo order:score`"
        )

    @e621.command(
        cls=DualCommand,
        name="image",
        aliases=["img", "imagem"],
        help="Pesquise uma imagem no e621: r.e621 image <tags>.",
    )
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def e621_image(self, ctx, *, tags: str):
        await self._search(ctx, tags, "image")

    @e621.command(
        cls=DualCommand,
        name="video",
        aliases=["vid", "webm"],
        help="Pesquise um vídeo no e621: r.e621 video <tags>.",
    )
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def e621_video(self, ctx, *, tags: str):
        await self._search(ctx, tags, "video")

    @e621.command(
        cls=DualCommand,
        name="top",
        aliases=["ranking", "rank", "lb"],
        help="Veja o ranking de tags e artistas mais pesquisados no servidor: r.e621 top [tags|artistas].",
    )
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def e621_top(self, ctx, tipo: str = "tudo"):
        if not ctx.guild:
            await ctx.send("Este ranking está disponível apenas em servidores.")
            return

        mode = tipo.strip().lower() if tipo else "tudo"
        if mode in ("tag", "tags"):
            mode = "tags"
        elif mode in ("artista", "artistas", "artist", "artists"):
            mode = "artistas"
        else:
            mode = "tudo"

        view = E621TopView(ctx.guild, mode=mode, author_id=ctx.author.id)
        embed = view.build_embed()
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @e621.command(
        cls=DualCommand,
        name="blocktag",
        aliases=["block", "bloquear"],
        help="Bloqueie uma tag das buscas e621 neste servidor: r.e621 blocktag <tag>.",
    )
    @commands.has_guild_permissions(manage_guild=True)
    async def e621_blocktag(self, ctx, *, tag: str):
        if not ctx.guild:
            await ctx.send("Este comando está disponível apenas em servidores.")
            return

        tag = tag.strip().lower()
        if not tag:
            await ctx.send("Informe a tag que deseja bloquear. Exemplo: `r.e621 blocktag gore`")
            return

        # Support blocking multiple tags at once (space-separated)
        tags_to_block = [t.strip().lower() for t in tag.split() if t.strip()]
        added = []
        already = []
        for t in tags_to_block:
            if database.add_e621_blocked_tag(str(ctx.guild.id), t):
                added.append(t)
            else:
                already.append(t)

        parts = []
        if added:
            tag_list = ", ".join(f"`{t}`" for t in added)
            parts.append(f"🚫 {'Tags bloqueadas' if len(added) > 1 else 'Tag bloqueada'}: {tag_list}")
        if already:
            tag_list = ", ".join(f"`{t}`" for t in already)
            parts.append(f"⚠️ Já {'bloqueadas' if len(already) > 1 else 'bloqueada'}: {tag_list}")

        blocked = database.get_e621_blocked_tags(str(ctx.guild.id))
        parts.append(f"📋 Total de tags bloqueadas: **{len(blocked)}**")
        await ctx.send("\n".join(parts))

    @e621.command(
        cls=DualCommand,
        name="unblocktag",
        aliases=["unblock", "desbloquear"],
        help="Desbloqueie uma tag das buscas e621 neste servidor: r.e621 unblocktag <tag>.",
    )
    @commands.has_guild_permissions(manage_guild=True)
    async def e621_unblocktag(self, ctx, *, tag: str):
        if not ctx.guild:
            await ctx.send("Este comando está disponível apenas em servidores.")
            return

        tag = tag.strip().lower()
        if not tag:
            await ctx.send("Informe a tag que deseja desbloquear. Exemplo: `r.e621 unblocktag gore`")
            return

        tags_to_unblock = [t.strip().lower() for t in tag.split() if t.strip()]
        removed = []
        not_found = []
        for t in tags_to_unblock:
            if database.remove_e621_blocked_tag(str(ctx.guild.id), t):
                removed.append(t)
            else:
                not_found.append(t)

        parts = []
        if removed:
            tag_list = ", ".join(f"`{t}`" for t in removed)
            parts.append(f"✅ {'Tags desbloqueadas' if len(removed) > 1 else 'Tag desbloqueada'}: {tag_list}")
        if not_found:
            tag_list = ", ".join(f"`{t}`" for t in not_found)
            parts.append(f"⚠️ {'Não estavam' if len(not_found) > 1 else 'Não estava'} bloqueada: {tag_list}")

        blocked = database.get_e621_blocked_tags(str(ctx.guild.id))
        parts.append(f"📋 Total de tags bloqueadas: **{len(blocked)}**")
        await ctx.send("\n".join(parts))

    @e621.command(
        cls=DualCommand,
        name="blocklist",
        aliases=["blocked", "bloqueadas"],
        help="Veja a lista de tags bloqueadas no servidor: r.e621 blocklist.",
    )
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def e621_blocklist(self, ctx):
        if not ctx.guild:
            await ctx.send("Este comando está disponível apenas em servidores.")
            return

        blocked = database.get_e621_blocked_tags(str(ctx.guild.id))
        if not blocked:
            await ctx.send(
                "📋 Nenhuma tag bloqueada neste servidor.\n"
                "💡 Use `r.e621 blocktag <tag>` para bloquear tags das buscas."
            )
            return

        tag_list = ", ".join(f"`{t}`" for t in blocked)
        embed = nextcord.Embed(
            title=f"🚫 Tags Bloqueadas — {ctx.guild.name}",
            description=tag_list,
            color=E621_COLOR,
        )
        embed.set_footer(
            text=f"{len(blocked)} tag{'s' if len(blocked) != 1 else ''} bloqueada{'s' if len(blocked) != 1 else ''} • Use r.e621 unblocktag para remover",
            icon_url=E621_ICON,
        )
        if ctx.guild.icon:
            embed.set_thumbnail(url=ctx.guild.icon.url)
        await ctx.send(embed=embed)

    @e621.command(
        cls=DualCommand,
        name="random",
        aliases=["aleatorio", "aleatório"],
        help="Veja um post aleatório popular do e621 (score ≥ 1000): r.e621 random [tags].",
    )
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def e621_random(self, ctx, *, tags: str = ""):
        tags = tags.strip()
        query = f"{tags} score:>=1000 order:random".strip()

        blocked = []
        if ctx.guild:
            blocked = database.get_e621_blocked_tags(str(ctx.guild.id))

        async with ctx.typing():
            posts = await search_e621(query, "image", limit=1, blocked_tags=blocked)

        if not posts:
            await ctx.send(
                f"Nenhum post popular encontrado"
                + (f" para as tags: `{tags}`" if tags else "")
                + ".\nTente tags diferentes ou remova filtros."
            )
            return

        if ctx.guild:
            self._record_search(str(ctx.guild.id), tags or "random", posts)

        post = posts[0]
        embed = build_e621_embed(post, tags or "random (score ≥ 1000)", "image", 0, 1)
        embed.title = "e621 — Post Aleatório Popular ⭐"
        await ctx.send(embed=embed)

    async def _search(self, ctx, tags: str, search_type: str):
        """Shared search logic for image and video subcommands."""
        if not tags or not tags.strip():
            await ctx.send("Informe pelo menos uma tag. Exemplo: `r.e621 image canine order:score`")
            return

        tags = tags.strip()

        # Fetch guild-blocked tags
        blocked = []
        if ctx.guild:
            blocked = database.get_e621_blocked_tags(str(ctx.guild.id))

        async with ctx.typing():
            posts = await search_e621(tags, search_type, blocked_tags=blocked)

        if not posts:
            await ctx.send(f"Nenhum {'vídeo' if search_type == 'video' else 'imagem'} encontrado para as tags: `{tags}`")
            return

        # Record search statistics for this guild
        if ctx.guild:
            self._record_search(str(ctx.guild.id), tags, posts)

        view = E621PaginatorView(posts, tags, search_type, ctx.author.id)
        embed = view._build_embed()
        message = await ctx.send(embed=embed, view=view)
        view.message = message


def setup(bot):
    bot.add_cog(Booru(bot))
