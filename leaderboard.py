"""Render live ranking data as a Discord-ready PNG without external assets."""
import asyncio
from io import BytesIO
from pathlib import Path

import nextcord
from nextcord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageOps

from db import database, EconomyError
from command_support import DualCommand

MAX_IMAGE_PIXELS = 16_000_000

def font(size, bold=False):
    """Use Unicode fonts for every card, including Linux/Docker deployments."""
    filename = "arialbd.ttf" if bold else "arial.ttf"
    windows = Path("C:/Windows/Fonts") / filename
    dejavu = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    linux = Path("/usr/share/fonts/truetype/dejavu") / dejavu
    for candidate in (filename, str(windows), str(linux), dejavu):
        try:
            return ImageFont.truetype(candidate, size, encoding="unic")
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def fit(draw, text, typeface, width):
    text = " ".join(str(text).split()) or "Jogador"
    while text and draw.textlength(text, font=typeface) > width:
        text = text[:-1]
    return text

def render_profile(canvas, avatar, x, y, size):
    """Draw a circular avatar at (x, y) with the given size."""
    if not avatar:
        return
    try:
        with Image.open(BytesIO(avatar)) as source:
            if source.width * source.height > MAX_IMAGE_PIXELS:
                return
            portrait = ImageOps.fit(source.convert("RGBA"), (size, size),
                                    method=Image.Resampling.LANCZOS)
        mask = Image.new("L", (size, size), 0)
        ImageDraw.Draw(mask).ellipse((0, 0, size - 1, size - 1), fill=255)
        # Composite transparency onto the existing fallback before clipping.
        background = canvas.crop((x, y, x + size, y + size)).convert("RGBA")
        background.alpha_composite(portrait)
        canvas.paste(background.convert("RGB"), (x, y), mask)
    except (OSError, ValueError, Image.DecompressionBombError):
        pass
def render_leaderboard(entries, page, pages, total):
    """entries are (rank, display_name, balance, is_requester[, avatar_bytes])."""
    width, height = 1000, 252 + max(1, len(entries)) * 78
    canvas = Image.new("RGB", (width, height), "#101c24")
    draw = ImageDraw.Draw(canvas)
    title, name_font, small = font(42, True), font(23, True), font(17)
    amount_font = font(24, True)
    draw.rounded_rectangle((28, 25, 972, 159), radius=24, fill="#1a3438")
    draw.text((54, 43), "RALSEI  /  DarkMoney", font=small, fill="#77e5bc")
    draw.text((52, 72), "Os mais ricos", font=title, fill="#f1f8f4")
    draw.text((55, 128), "RANKING GLOBAL  •  Saldo disponível", font=small, fill="#adc6c5")
    draw.text((48, 178), "POSIÇÃO / JOGADOR", font=small, fill="#adc6c5")
    draw.text((952, 178), "DarkMoney", font=small, fill="#adc6c5", anchor="ra")
    top_balance = max((entry[2] for entry in entries), default=1) or 1
    medals = {1: "#f4cc72", 2: "#bed0e0", 3: "#dca887"}
    if not entries:
        draw.text((50, 230), "Ainda não há jogadores. Comece com r.daily!", font=name_font, fill="#f1f8f4")
    for index, entry in enumerate(entries):
        rank, name, balance, own = entry[:4]
        avatar = entry[4] if len(entry) > 4 else None
        y = 207 + index * 78
        color = medals.get(rank, "#80a3ac")
        draw.rounded_rectangle((30, y, 970, y + 69), radius=14,
                               fill="#203d3d" if own else "#192a34",
                               outline="#77e5bc" if own else None, width=2)
        rank_label = f"{rank:02}"
        rank_size = 23
        rank_font = name_font
        while draw.textlength(rank_label, font=rank_font) > 60 and rank_size > 10:
            rank_size -= 1
            rank_font = font(rank_size, True)
        draw.text((70, y + 34), rank_label, font=rank_font, fill=color, anchor="mm")
        draw.ellipse((108, y + 12, 152, y + 56), fill=color)
        initial = next((char.upper() for char in name if char.isalnum()), "?")
        draw.text((130, y + 34), initial, font=font(20, True), fill="#101c24", anchor="mm")
        render_profile(canvas, avatar, 108, y + 12, 44)
        draw.text((170, y + 13), fit(draw, name, name_font, 470), font=name_font, fill="#f1f8f4")
        bar = int(440 * max(0, balance) / top_balance)
        draw.rounded_rectangle((170, y + 49, 610, y + 53), radius=2, fill="#29414a")
        if bar > 0:
            draw.rounded_rectangle((170, y + 49, 170 + bar, y + 53), radius=2, fill=color)
        draw.text((950, y + 20), f"{balance:,}", font=amount_font, fill="#f1f8f4", anchor="ra")
    draw.text((40, height - 29), f"Página {page}/{pages}  •  {total} jogadores", font=small, fill="#adc6c5")
    draw.text((960, height - 29), "r.rich [página]", font=small, fill="#77e5bc", anchor="ra")
    output = BytesIO()
    canvas.save(output, format="PNG")
    output.seek(0)
    return output


class Leaderboard(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database

    async def ranking_entry(self, ctx, rank, discord_id, balance):
        try:
            user_id = int(discord_id)
        except (TypeError, ValueError):
            user_id = 0
        member = ctx.guild.get_member(user_id) if ctx.guild else None
        user = member or self.bot.get_user(user_id)
        avatar = None
        try:
            async with asyncio.timeout(10):
                if user is None and user_id > 0:
                    user = await self.bot.fetch_user(user_id)
                asset = getattr(user, "display_avatar", None)
                if asset is not None:
                    avatar = await asset.with_size(128).with_static_format("png").read()
        except (nextcord.HTTPException, asyncio.TimeoutError, OSError):
            pass
        name = user.display_name if user else f"Usuário {discord_id}"
        return rank, name, balance, ctx.author.id == user_id, avatar

    @commands.command(cls=DualCommand, name="rich", aliases=["richlist", "leaderboard", "top", "rank"],
                      help="Ranking global em imagem, 10 jogadores por página: r.rich [página]")
    # Use a callable key to avoid Nextcord 3.2's BucketType mapping error.
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def rich(self, ctx, page: int = 1):
        if not 1 <= page <= 1_000_000:
            raise EconomyError("Use um número de página entre 1 e 1.000.000.")
        rows, total = self.storage.leaderboard(page)
        pages = max(1, (total + 9) // 10)
        if page > pages:
            raise EconomyError(f"Essa página não existe. O ranking tem {pages} página(s).")
        entries = await asyncio.gather(*(
            self.ranking_entry(ctx, rank, discord_id, balance)
            for rank, (discord_id, balance) in enumerate(rows, start=(page - 1) * 10 + 1)
        ))
        output = await asyncio.to_thread(render_leaderboard, entries, page, pages, total)
        try:
            await ctx.send(content=f"Ranking global de DarkMoney • página {page}/{pages}",
                           file=nextcord.File(output, filename="rich-list.png"))
        finally:
            output.close()


def setup(bot):
    bot.add_cog(Leaderboard(bot))
