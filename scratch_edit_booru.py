"""Add blocked tag commands and random command to booru.py."""
import pathlib

p = pathlib.Path(r"c:\Users\CaioWithC\Documents\RalseiBot\cogs\booru.py")
content = p.read_text(encoding="utf-8")

# 1) Update search_e621 to accept blocked_tags parameter
old_search = '''async def search_e621(tags: str, search_type: str, limit: int = 50) -> List[dict]:
    """Search e621 for posts matching *tags* and filter by type."""'''
new_search = '''async def search_e621(tags: str, search_type: str, limit: int = 50,
                     blocked_tags: List[str] = ()) -> List[dict]:
    """Search e621 for posts matching *tags* and filter by type."""'''
content = content.replace(old_search, new_search, 1)

# 2) Add blocked_tags exclusion into the query building
old_query_block = '''    # Inject type filter into the tag string
    if search_type == "video":
        query = f"{tags} type:webm"
    else:
        query = f"{tags} -type:webm -type:swf"'''
new_query_block = '''    # Inject type filter into the tag string
    if search_type == "video":
        query = f"{tags} type:webm"
    else:
        query = f"{tags} -type:webm -type:swf"

    # Append guild-blocked tags as exclusions
    for bt in blocked_tags:
        bt = bt.strip()
        if bt and not bt.startswith("-"):
            query += f" -{bt}"'''
content = content.replace(old_query_block, new_query_block, 1)

# 3) Update _search to pass blocked_tags
old_search_call = '''        async with ctx.typing():
            posts = await search_e621(tags, search_type)'''
new_search_call = '''        # Fetch guild-blocked tags
        blocked = []
        if ctx.guild:
            blocked = database.get_e621_blocked_tags(str(ctx.guild.id))

        async with ctx.typing():
            posts = await search_e621(tags, search_type, blocked_tags=blocked)'''
content = content.replace(old_search_call, new_search_call, 1)

# 4) Add new commands before the _search method
old_search_method = '''    async def _search(self, ctx, tags: str, search_type: str):'''
new_commands = '''    @e621.command(
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
        await ctx.send("\\n".join(parts))

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
        await ctx.send("\\n".join(parts))

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
                "📋 Nenhuma tag bloqueada neste servidor.\\n"
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
                + ".\\nTente tags diferentes ou remova filtros."
            )
            return

        if ctx.guild:
            self._record_search(str(ctx.guild.id), tags or "random", posts)

        post = posts[0]
        embed = build_e621_embed(post, tags or "random (score ≥ 1000)", "image", 0, 1)
        embed.title = "e621 — Post Aleatório Popular ⭐"
        await ctx.send(embed=embed)

    async def _search(self, ctx, tags: str, search_type: str):'''
content = content.replace(old_search_method, new_commands, 1)

p.write_text(content, encoding="utf-8")
print("booru.py updated successfully!")

