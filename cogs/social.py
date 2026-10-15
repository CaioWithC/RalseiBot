"""Persistent user profiles rendered locally as PNG cards."""
import asyncio
from io import BytesIO
from pathlib import Path
import re
import time
import uuid
import warnings

import nextcord
from nextcord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError

from db import database, EconomyError
from cogs.leaderboard import font as _base_font
from cogs.command_support import DualCommand, DualGroup


def font(size, bold=False):
    """Profile card font: prefer Segoe UI for a modern look, fall back to Arial/DejaVu."""
    if bold:
        candidates = ["segoeuib.ttf", "C:/Windows/Fonts/segoeuib.ttf"]
    else:
        candidates = ["segoeui.ttf", "C:/Windows/Fonts/segoeui.ttf"]
    for name in candidates:
        try:
            return ImageFont.truetype(name, size, encoding="unic")
        except OSError:
            pass
    return _base_font(size, bold)

WIDTH, HEIGHT = 1000, 790
HEADER_HEIGHT, BACKGROUND_HEIGHT = 190, 400
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_ABOUT_LENGTH = 300
DEFAULT_COLOR = "#101C24"

PETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "profile_pet"

PET_EMOJIS = {
    "bamgeut": "🌰",
    "choi yong meong": "🐶",
    "da-go-nyang": "🐱",
    "hhm nya ring": "🐧",
    "hwang choon": "🦊",
    "sakkukku": "🐱",
    "kimachi": "🐆",
    "heurimong": "👻",
    "zuharong": "🐕",
    "hongppippi": "🐣"
}


def get_available_pets():
    """Discover all PNG pets available in assets/profile_pet."""
    pets = {}
    if not PETS_DIR.exists():
        return pets
    for path in sorted(PETS_DIR.rglob("*.png")):
        rel_key = path.relative_to(PETS_DIR).as_posix()
        stem = path.stem
        version = " 2" if stem.endswith("_2") or stem.endswith("-2") else ""
        raw = stem[:-2] if version else stem
        if raw.isupper():
            words = raw.replace("_", " ").split()
            words = ["-".join(part.capitalize() for part in w.split("-")) for w in words]
            base_name = " ".join(words)
        else:
            base_name = raw.replace("_", " ")
        name = f"{base_name}{version}"
        category = path.parent.name.upper() if path.parent != PETS_DIR else ""
        emoji = PET_EMOJIS.get(base_name.lower(), "🐾")
        pets[rel_key] = {
            "key": rel_key,
            "name": name,
            "path": path,
            "category": category,
            "emoji": emoji,
        }
    return pets


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


def _darken(hex_color, factor=0.65):
    """Return a darker shade of a hex color."""
    rgb = tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    dark = tuple(max(0, int(c * factor)) for c in rgb)
    return f"#{dark[0]:02X}{dark[1]:02X}{dark[2]:02X}"


def _draw_chevron(draw, header_h, color, width):
    """Draw diagonal chevron layers that extend flush to the right edge."""
    dark1 = _darken(color, 0.75)
    dark2 = _darken(color, 0.60)
    dark3 = _darken(color, 0.45)
    # Three chevron layers, each with a pointed left edge filling to the right
    tips = [620, 660, 700]  # left tip x-positions
    colors = [dark1, dark2, dark3]
    for tip_x, fill in zip(tips, colors):
        draw.polygon([
            (tip_x, header_h // 2),       # pointed tip
            (tip_x + 50, 0),              # top-left of flat edge
            (width, 0),                   # top-right corner
            (width, header_h),            # bottom-right corner
            (tip_x + 50, header_h),       # bottom-left of flat edge
        ], fill=fill)


def render_profile(profile, name, avatar=None, marriage=None):
    color = profile["color"]
    foreground = text_color(color)
    canvas = Image.new("RGB", (WIDTH, HEIGHT), color)
    draw = ImageDraw.Draw(canvas)

    # ── Header chevron decoration ──
    _draw_chevron(draw, HEADER_HEIGHT, color, WIDTH)

    # ── Avatar circle ──
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

    # ── Left info: name, UID ──
    draw_fitted(draw, (193, 30), name, 39, 400, foreground, True)
    draw_fitted(draw, (196, 75), f"UID: {profile['discord_id']}", 16,
                380, foreground)

    # ── Darkmoney below name ──
    draw.text((196, 123), "DARKMONEY", font=font(14, True), fill=foreground)
    draw_fitted(draw, (196, 143), f"{profile['balance']:,}", 26, 350, foreground, True)

    # ── Right info: rank ──
    draw.text((770, 25), "RANK EM r.rank", font=font(16, True), fill=foreground, anchor="la")
    draw_fitted(draw, (770, 48), f"#{profile['rank']:,}", 34, 200, foreground, True)

    # ── Marriage info (right side, below rank) ──
    if marriage:
        draw.text((770, 100), "CASADO COM", font=font(14, True), fill=foreground)
        draw_fitted(draw, (770, 120), marriage["spouse_name"], 22, 200, foreground)
        draw_fitted(draw, (770, 148), marriage_duration(marriage["married_at"]),
                    12, 200, foreground)

    # ── Background / wallpaper section ──
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

    # ── Footer: darker bar ──
    footer_y = HEADER_HEIGHT + BACKGROUND_HEIGHT
    footer_color = _darken(color, 0.75)
    draw.rectangle((0, footer_y, WIDTH, HEIGHT), fill=footer_color)

    # ── Render pet if selected ──
    pet_key = profile.get("pet")
    pet_image = None
    if pet_key:
        pet_path = PETS_DIR / pet_key
        if pet_path.is_file():
            try:
                with Image.open(pet_path) as pet_source:
                    raw_pet = pet_source.convert("RGBA")
                    bbox = raw_pet.getbbox()
                    if bbox:
                        raw_pet = raw_pet.crop(bbox)
                    target_height = 175
                    aspect = raw_pet.width / raw_pet.height
                    target_width = int(target_height * aspect)
                    if target_width > 220:
                        target_width = 220
                        target_height = int(target_width / aspect)
                    pet_image = raw_pet.resize((target_width, target_height), Image.Resampling.LANCZOS)
            except (OSError, ValueError):
                pet_image = None

    # ── Bio text ──
    draw.text((30, footer_y + 14), "BIO", font=font(20, True), fill=foreground)
    about = profile["about"] or "Conte um pouco sobre você com r.profile about <texto>."
    max_bio_width = WIDTH - 60 - (pet_image.width + 30 if pet_image else 0)
    available_h = HEIGHT - footer_y - 50
    for size in range(22, 14, -1):
        face = font(size)
        lines = wrap_text(draw, about, face, max_bio_width)
        max_lines = available_h // (size + 5)
        if len(lines) <= max_lines:
            break
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while lines[-1] and draw.textlength(lines[-1] + "…", font=face) > max_bio_width:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    bio_start_y = footer_y + 45
    for index, line in enumerate(lines):
        draw.text((30, bio_start_y + index * (size + 5)), line, font=face, fill=foreground)

    # ── Pet image ──
    if pet_image:
        pos_x = WIDTH - pet_image.width - 25
        pos_y = HEIGHT - pet_image.height - 5
        canvas.paste(pet_image, (pos_x, pos_y), mask=pet_image.getchannel("A"))

    output = BytesIO()
    canvas.save(output, format="PNG")
    output.seek(0)
    return output


async def _refresh_profile(cog, target, message, view):
    """Re-render the profile card and edit the original message."""
    try:
        data = cog.storage.profile(target.id)
        marriage = cog.storage.marriage(target.id)
        if marriage:
            spouse_id = int(marriage["second_id"] if str(target.id) == marriage["first_id"] else marriage["first_id"])
            spouse = cog.bot.get_user(spouse_id)
            if spouse is None:
                try:
                    spouse = await asyncio.wait_for(cog.bot.fetch_user(spouse_id), timeout=5)
                except (nextcord.HTTPException, asyncio.TimeoutError):
                    pass
            marriage["spouse_name"] = f"@{spouse.name}" if spouse else f"UID: {spouse_id}"

        avatar = None
        try:
            asset = target.display_avatar.with_size(256).with_static_format("png")
            avatar = await asyncio.wait_for(asset.read(), timeout=5)
        except (nextcord.HTTPException, asyncio.TimeoutError, AttributeError):
            pass

        output = await asyncio.to_thread(render_profile, data, target.display_name, avatar, marriage)
        await message.edit(file=nextcord.File(output, filename="profile.png"), view=view)
    except Exception:
        pass


class BioModal(nextcord.ui.Modal):
    """Modal for editing the profile bio."""
    def __init__(self, cog, target, parent_view):
        super().__init__(title="Editar Bio", timeout=300)
        self.cog = cog
        self.target = target
        self.parent_view = parent_view

        current = cog.storage.profile(target.id).get("about") or ""
        self.bio_input = nextcord.ui.TextInput(
            label="Sua bio (até 300 caracteres)",
            style=nextcord.TextInputStyle.paragraph,
            placeholder="Conte um pouco sobre você...",
            default_value=current,
            required=False,
            max_length=MAX_ABOUT_LENGTH,
        )
        self.add_item(self.bio_input)

    async def callback(self, interaction: nextcord.Interaction):
        text = (self.bio_input.value or "").strip()
        if len(text) > MAX_ABOUT_LENGTH:
            await interaction.response.send_message(
                f"A bio deve ter no máximo {MAX_ABOUT_LENGTH} caracteres.", ephemeral=True)
            return
        self.cog.storage.update_profile(self.target.id, about=text)
        await interaction.response.send_message(
            "✏️ Bio atualizada com sucesso!" if text else "✏️ Bio removida.", ephemeral=True)

        parent_msg = self.parent_view.message if self.parent_view else None
        if parent_msg:
            await _refresh_profile(self.cog, self.target, parent_msg, self.parent_view)


class BackgroundPromptView(nextcord.ui.View):
    """Ephemeral view that waits for a background image upload."""
    def __init__(self, cog, target, parent_view):
        super().__init__(timeout=60)
        self.cog = cog
        self.target = target
        self.parent_view = parent_view

    @nextcord.ui.button(label="Remover Fundo", emoji="🗑️", style=nextcord.ButtonStyle.danger)
    async def remove_bg(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Apenas o dono do perfil pode fazer isso!", ephemeral=True)
            return
        self.cog.storage.update_profile(self.target.id, background=None)
        await interaction.response.edit_message(
            content="🗑️ Fundo personalizado removido com sucesso!", view=None)
        parent_msg = self.parent_view.message if self.parent_view else None
        if parent_msg:
            await _refresh_profile(self.cog, self.target, parent_msg, self.parent_view)


class ProfileView(nextcord.ui.View):
    def __init__(self, cog, target, author_id, message=None):
        super().__init__(timeout=180)
        self.cog = cog
        self.target = target
        self.author_id = author_id
        self.message = message
        # Only show edit buttons when viewing your own profile
        is_own = (target.id == author_id)
        self.bg_button.disabled = not is_own
        self.pet_button.disabled = not is_own
        self.bio_button.disabled = not is_own
        if not is_own:
            self.bg_button.style = nextcord.ButtonStyle.secondary
            self.pet_button.style = nextcord.ButtonStyle.secondary
            self.bio_button.style = nextcord.ButtonStyle.secondary

    @nextcord.ui.button(label="Trocar Fundo", emoji="🖼️", style=nextcord.ButtonStyle.primary, row=0)
    async def bg_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Apenas o dono deste perfil pode alterar o fundo!", ephemeral=True)
            return
        if self.message is None and interaction.message:
            self.message = interaction.message
        bg_view = BackgroundPromptView(self.cog, self.target, parent_view=self)
        await interaction.response.send_message(
            "🖼️ **Trocar foto de fundo**\n"
            "Envie uma imagem com `r.profile background` (anexar imagem ao comando).\n"
            "Ou clique abaixo para remover o fundo atual.",
            view=bg_view,
            ephemeral=True
        )

    @nextcord.ui.button(label="Trocar Pet", emoji="🐾", style=nextcord.ButtonStyle.primary, row=0)
    async def pet_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Apenas o dono deste perfil pode escolher o pet!", ephemeral=True)
            return
        if self.message is None and interaction.message:
            self.message = interaction.message
        select_view = PetSelectView(self.cog, self.target, parent_view=self)
        await interaction.response.send_message(
            "🐾 **Escolha um pet para o seu perfil:**\nSelecione uma opção no menu abaixo:",
            view=select_view,
            ephemeral=True
        )

    @nextcord.ui.button(label="Trocar Bio", emoji="✏️", style=nextcord.ButtonStyle.primary, row=0)
    async def bio_button(self, button: nextcord.ui.Button, interaction: nextcord.Interaction):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Apenas o dono deste perfil pode editar a bio!", ephemeral=True)
            return
        if self.message is None and interaction.message:
            self.message = interaction.message
        modal = BioModal(self.cog, self.target, parent_view=self)
        await interaction.response.send_modal(modal)


class PetSelectView(nextcord.ui.View):
    def __init__(self, cog, target, parent_view=None):
        super().__init__(timeout=120)
        self.cog = cog
        self.target = target
        self.parent_view = parent_view
        self.add_item(PetDropdown(cog, target, parent_view))


class PetDropdown(nextcord.ui.Select):
    def __init__(self, cog, target, parent_view=None):
        self.cog = cog
        self.target = target
        self.parent_view = parent_view

        pets = get_available_pets()
        current_data = self.cog.storage.profile(target.id)
        current_pet = current_data.get("pet")

        options = [
            nextcord.SelectOption(
                label="Nenhum (Remover Pet)",
                value="none",
                description="Não exibir nenhum pet no perfil",
                emoji="❌",
                default=(current_pet is None)
            )
        ]

        for key, pet in pets.items():
            category_tag = f"[{pet['category']}] " if pet["category"] else ""
            options.append(
                nextcord.SelectOption(
                    label=f"{category_tag}{pet['name']}"[:100],
                    value=key,
                    description=f"Coleção {pet['category']}"[:100] if pet["category"] else "Pet do perfil",
                    emoji=pet["emoji"],
                    default=(current_pet == key)
                )
            )

        super().__init__(
            custom_id=f"profile:pet:{uuid.uuid4().hex}",
            placeholder="Selecione um pet para o seu perfil...",
            min_values=1,
            max_values=1,
            options=options[:25]
        )

    async def callback(self, interaction: nextcord.Interaction):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Apenas o dono deste perfil pode escolher o pet!", ephemeral=True)
            return

        selected_key = self.values[0]
        new_pet = None if selected_key == "none" else selected_key
        self.cog.storage.update_profile(self.target.id, pet=new_pet)

        pets = get_available_pets()
        pet_info = pets.get(new_pet) if new_pet else None
        pet_name = pet_info["name"] if pet_info else "Nenhum"

        # Update original profile message if possible
        parent_msg = self.parent_view.message if self.parent_view else None
        if parent_msg:
            await _refresh_profile(self.cog, self.target, parent_msg, self.parent_view)

        if new_pet:
            msg = f"🐾 Pet alterado para **{pet_name}** com sucesso!"
        else:
            msg = "🐾 Pet removido do seu perfil com sucesso."

        await interaction.response.edit_message(content=msg, view=None)


class Social(commands.Cog):
    def __init__(self, bot, storage=None):
        self.bot = bot
        self.storage = storage if storage is not None else database
        self.image_jobs = asyncio.Semaphore(2)

    @commands.group(cls=DualGroup, name="profile", aliases=["perfil"], invoke_without_command=True,
                    help="Veja seu perfil ou o de alguém: r.profile [@usuário]. Personalize com color, about, background e pet.")
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
            view = ProfileView(self, target, ctx.author.id)
            msg = await ctx.send(file=nextcord.File(output, filename="profile.png"), view=view)
            if msg:
                view.message = msg
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

    @profile.command(cls=DualCommand, name="pet", aliases=["animal", "bicho"],
                     help="Escolha ou remova o pet do seu perfil: r.profile pet [nome ou reset]")
    async def pet(self, ctx, *, name: str = None):
        pets = get_available_pets()
        if not name:
            target = ctx.author
            if ctx.guild:
                target = ctx.guild.get_member(target.id) or target
            data = self.storage.profile(target.id)
            current_pet = data.get("pet")
            current_name = pets[current_pet]["name"] if current_pet in pets else "Nenhum"
            view = PetSelectView(self, target)
            await ctx.send(f"Seu pet atual: **{current_name}**.\nSelecione um novo pet abaixo:", view=view)
            return

        name = name.strip()
        if name.lower() in {"reset", "remover", "none", "nenhum", "tirar"}:
            self.storage.update_profile(ctx.author.id, pet=None)
            await ctx.send("Pet removido do seu perfil. Veja com `r.profile`.")
            return

        match = None
        for key, info in pets.items():
            if name.lower() == key.lower() or name.lower() == info["name"].lower() or name.lower() == Path(key).stem.lower():
                match = key
                break
        if not match:
            for key, info in pets.items():
                if name.lower() in info["name"].lower():
                    match = key
                    break
        if not match:
            pet_list = ", ".join(f"`{p['name']}`" for p in pets.values())
            raise EconomyError(f"Pet não encontrado. Pets disponíveis: {pet_list}. Ou use `reset` para remover.")

        self.storage.update_profile(ctx.author.id, pet=match)
        pet_display = pets[match]["name"]
        await ctx.send(f"Pet alterado para **{pet_display}**! Veja com `r.profile`.")


def setup(bot):
    bot.add_cog(Social(bot))
