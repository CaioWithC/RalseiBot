"""Persistent user profiles rendered locally as PNG cards."""
import asyncio
from io import BytesIO
import re
import time
import warnings

import nextcord
from nextcord.ext import commands
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

from db import database, EconomyError
from leaderboard import font
from command_support import DualCommand, DualGroup

WIDTH, HEIGHT = 1000, 790
HEADER_HEIGHT, BACKGROUND_HEIGHT = 190, 400
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_ABOUT_LENGTH = 300
DEFAULT_COLOR = "#101C24"


def parse_color(value):
    value = value.strip().removeprefix("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", value):
        raise EconomyError("Use uma cor hexadecimal de 6 dígitos, como `#77E5BC`.")
    return "#" + value.upper()


def normalize_background(data):
    """Decode bounded uploads and store a resized image, independent of CDN URLs."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise EconomyError("A imagem deve ter no máximo 8 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as source:
                if source.format not in {"PNG", "JPEG", "WEBP", "GIF"}:
                    raise EconomyError("Envie uma imagem PNG, JPG, WebP ou GIF.")
                if source.width * source.height > MAX_IMAGE_PIXELS:
                    raise EconomyError("A imagem deve ter no máximo 16 milhões de pixels.")
                # Animated uploads use the first frame; EXIF orientation is respected.
                oriented = ImageOps.exif_transpose(source)
                resized = ImageOps.fit(oriented.convert("RGBA"), (WIDTH, BACKGROUND_HEIGHT),
                                       method=Image.Resampling.LANCZOS)
                flattened = Image.new("RGB", resized.size, DEFAULT_COLOR)
                flattened.paste(resized, mask=resized.getchannel("A"))
                output = BytesIO()
                flattened.save(output, format="JPEG", quality=90)
                return output.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning) as error:
        if isinstance(error, EconomyError):
            raise
        raise EconomyError("Não foi possível ler essa imagem. Envie um PNG, JPG, WebP ou GIF válido.") from error


def text_color(background):
    rgb = tuple(int(background[i:i + 2], 16) / 255 for i in (1, 3, 5))
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    luminance = sum(c * weight for c, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
    return "#000000" if luminance > 0.179 else "#FFFFFF"


def draw_fitted(draw, xy, text, size, width, fill, bold=False):
    text = " ".join(str(text).split())
    face = font(size, bold)
    while size > 12 and draw.textlength(text, font=face) > width:
        size -= 1
        face = font(size, bold)
    if draw.textlength(text, font=face) > width:
        while text and draw.textlength(text + "…", font=face) > width:
            text = text[:-1]
        text += "…"
    draw.text(xy, text, font=face, fill=fill)


def wrap_text(draw, text, face, width):
    lines = []
    for paragraph in text.splitlines() or [""]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}" if line else word
            if draw.textlength(candidate, font=face) <= width:
                line = candidate
                continue
            if line:
                lines.append(line)
            line = ""
            for char in word:
                if line and draw.textlength(line + char, font=face) > width:
                    lines.append(line)
                    line = ""
                line += char
        lines.append(line)
    return lines


def marriage_duration(married_at):
    elapsed = max(0, int(time.time()) - married_at)
    days, remaining = divmod(elapsed, 86400)
    hours, remaining = divmod(remaining, 3600)
    minutes = remaining // 60
    if days:
        return f"{days} {'dia' if days == 1 else 'dias'} e {hours} h juntos"
    if hours:
        return f"{hours} h e {minutes} min juntos"
    if minutes:
        return f"{minutes} min juntos"
    return "Menos de 1 min juntos"


def render_profile(profile, name, avatar=None, marriage=None):
    color = profile["color"]
    foreground = text_color(color)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), color)
    draw = ImageDraw.Draw(canvas)

    draw.ellipse((26, 23, 172, 169), fill=foreground)
    portrait = None
    if avatar:
        try:
            with Image.open(BytesIO(avatar)) as source:
                if source.width * source.height <= MAX_IMAGE_PIXELS:
                    portrait = ImageOps.fit(source.convert("RGBA"), (134, 134),
                                            method=Image.Resampling.LANCZOS)
        except (OSError, ValueError, Image.DecompressionBombError):
            pass
    if portrait:
        mask = Image.new("L", (134, 134))
        ImageDraw.Draw(mask).ellipse((0, 0, 133, 133), fill=255)
        base = Image.new("RGBA", portrait.size, color)
        base.alpha_composite(portrait)
        canvas.paste(base.convert("RGB"), (32, 29), mask)
    else:
        initial = next((char.upper() for char in name if char.isalnum()), "?")
        draw.text((99, 96), initial, font=font(60, True), fill=color, anchor="mm")
    draw.text((196, 29), "PERFIL", font=font(15, True), fill=foreground)
    draw_fitted(draw, (193, 55), name, 39, 470, foreground, True)
    draw_fitted(draw, (196, 109), f"UID: {profile['discord_id']}", 18,
                290 if marriage else 475, foreground)
    draw.text((714, 32), "RANK EM r.rich", font=font(16, True), fill=foreground)
    draw_fitted(draw, (710, 55), f"#{profile['rank']:,}", 34, 256, foreground, True)
    balance_x = 506 if marriage else 711
    draw.text((balance_x + 3, 113), "DARKMONEY", font=font(15, True), fill=foreground)
    draw_fitted(draw, (balance_x, 138), f"{profile['balance']:,}", 26,
                180 if marriage else 257, foreground, True)
    if marriage:
        draw.text((710, 103), "Casado com", font=font(16), fill=foreground)
        draw_fitted(draw, (710, 130), marriage["spouse_name"], 26, 258, foreground)
        draw_fitted(draw, (710, 158), marriage_duration(marriage["married_at"]),
                    13, 258, foreground)

    if profile["background"]:
        with Image.open(BytesIO(profile["background"])) as background:
            canvas.paste(ImageOps.fit(background.convert("RGB"), (WIDTH, BACKGROUND_HEIGHT),
                                     method=Image.Resampling.LANCZOS), (0, HEADER_HEIGHT))
    else:
        draw.rectangle((0, HEADER_HEIGHT, WIDTH, HEADER_HEIGHT + BACKGROUND_HEIGHT - 1), fill="#182C35")
        for x in range(-400, WIDTH, 100):
            draw.line((x, HEADER_HEIGHT, x + 400, HEADER_HEIGHT + BACKGROUND_HEIGHT), fill="#213E46", width=2)
        draw.text((WIDTH // 2, 365), "Seu espaço, seu estilo.", font=font(32, True), fill="#EBF7F3", anchor="mm")
        draw.text((WIDTH // 2, 414), "Envie uma imagem com r.profile background", font=font(20), fill="#A9CDC4", anchor="mm")

    draw.text((30, 614), "SOBRE MIM", font=font(23, True), fill=foreground)
    about = profile["about"] or "Conte um pouco sobre você com r.profile about <texto>."
    for size in range(24, 15, -1):
        face = font(size)
        lines = wrap_text(draw, about, face, WIDTH - 60)
        max_lines = 124 // (size + 5)
        if len(lines) <= max_lines:
            break
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=face) > WIDTH - 60:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    for index, line in enumerate(lines):
        draw.text((30, 653 + index * (size + 5)), line, font=face, fill=foreground)
    output = BytesIO()
    canvas.save(output, format="PNG")
    output.seek(0)
    return output


class Social(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.image_jobs = asyncio.Semaphore(2)

    @commands.group(cls=DualGroup, name="profile", aliases=["perfil"], invoke_without_command=True,
                    help="Veja seu perfil ou o de alguém: r.profile [@usuário]. Personalize com color, about e background.")
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def profile(self, ctx, member: nextcord.User = None):
        target = member or ctx.author
        if ctx.guild:
            target = ctx.guild.get_member(target.id) or target
        data = self.storage.profile(target.id)
        marriage = self.storage.marriage(target.id)
        if marriage:
            spouse_id = int(marriage["second_id"] if str(target.id) == marriage["first_id"]
                            else marriage["first_id"])
            spouse = (ctx.guild.get_member(spouse_id) if ctx.guild else None) or self.bot.get_user(spouse_id)
            if spouse is None:
                try:
                    spouse = await asyncio.wait_for(self.bot.fetch_user(spouse_id), timeout=10)
                except (nextcord.HTTPException, asyncio.TimeoutError):
                    pass
            marriage["spouse_name"] = f"@{spouse.name}" if spouse else f"UID: {spouse_id}"
        avatar = None
        async with self.image_jobs:
            try:
                asset = target.display_avatar.with_size(256).with_static_format("png")
                avatar = await asyncio.wait_for(asset.read(), timeout=10)
            except (nextcord.HTTPException, asyncio.TimeoutError):
                pass  # A failed avatar download still produces a usable profile.
            output = await asyncio.to_thread(render_profile, data, target.display_name, avatar, marriage)
        try:
            await ctx.send(file=nextcord.File(output, filename="profile.png"))
        finally:
            output.close()

    @profile.command(cls=DualCommand, name="color", aliases=["cor"], help="Cor dos painéis do seu perfil: r.profile color #77E5BC")
    async def color(self, ctx, value: str):
        color = parse_color(value)
        self.storage.update_profile(ctx.author.id, color=color)
        await ctx.send(f"Cor do perfil alterada para **{color}**. Veja com `r.profile`.")

    @profile.command(cls=DualCommand, name="about", aliases=["sobremim", "bio"], help="r.profile about <texto de até 300 caracteres>. Use reset para limpar.")
    async def about(self, ctx, *, text: str):
        text = text.strip()
        if text.lower() in {"reset", "remover"}:
            text = ""
        elif not text or len(text) > MAX_ABOUT_LENGTH:
            raise EconomyError("O Sobre mim deve ter entre 1 e 300 caracteres.")
        self.storage.update_profile(ctx.author.id, about=text)
        await ctx.send("Sobre mim atualizado. Veja com `r.profile`.")

    @profile.command(cls=DualCommand, name="background", aliases=["fundo"],
                     help="Anexe uma imagem ao comando r.profile background (até 8 MB). Use r.profile background reset para remover.")
    @commands.cooldown(1, 5, lambda message: message.author.id)
    async def background(self, ctx, action: str = None):
        if action is not None:
            if action.lower() not in {"reset", "remover"}:
                raise EconomyError("Envie uma imagem com `r.profile background` ou `/profile background image:`; use reset para remover.")
            self.storage.update_profile(ctx.author.id, background=None)
            await ctx.send("Fundo personalizado removido. Veja com `r.profile`.")
            return
        if len(ctx.message.attachments) != 1:
            raise EconomyError("Envie exatamente uma imagem com `r.profile background` ou na opção image de `/profile background`.")
        attachment = ctx.message.attachments[0]
        if attachment.size > MAX_UPLOAD_BYTES:
            raise EconomyError("A imagem deve ter no máximo 8 MB.")
        async with self.image_jobs:
            try:
                data = await asyncio.wait_for(attachment.read(), timeout=20)
            except (nextcord.HTTPException, asyncio.TimeoutError) as error:
                raise EconomyError("Não foi possível baixar a imagem. Anexe o arquivo novamente.") from error
            background = await asyncio.to_thread(normalize_background, data)
        self.storage.update_profile(ctx.author.id, background=background)
        await ctx.send("Fundo personalizado salvo! Veja com `r.profile`.")


def setup(bot):
    bot.add_cog(Social(bot))
