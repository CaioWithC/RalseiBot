"""Render high-resolution mystical tarot reading tables for Discord embeds."""
from functools import lru_cache
from io import BytesIO
import math
from pathlib import Path
from typing import List, Optional, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

ASSETS = Path(__file__).resolve().parent.parent / "assets"
TAROT_DIR = ASSETS / "tarot"

# Palette: Mystical dark velvet with gold and Ralsei mint accents
CLOTH_BG = "#0b1216"           # Deep dark teal-slate velvet
CLOTH_INNER = "#0f1c20"        # Slightly lighter center glow
GOLD = "#e2b866"               # Warm celestial gold
GOLD_MUTED = "#9a7d43"         # Antique gold
GOLD_LIGHT = "#fff1c2"         # Shimmering gold highlight
MINT = "#77e5bc"               # Ralsei mint green
WHITE = "#f3f7f5"              # Crisp white
MUTED = "#8da29c"              # Muted sage/slate
SHADOW = (0, 0, 0, 160)


@lru_cache(maxsize=48)
def get_font(size: int, bold: bool = False, serif: bool = False):
    """Load font with clean fallbacks for Windows and Linux."""
    if serif:
        candidates = [
            "C:/Windows/Fonts/georgiab.ttf" if bold else "C:/Windows/Fonts/georgia.ttf",
            "C:/Windows/Fonts/timesbd.ttf" if bold else "C:/Windows/Fonts/times.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        ]
    else:
        candidates = [
            "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
            "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
            if bold
            else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]

    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_label(
    draw: ImageDraw.ImageDraw,
    xy: Tuple[float, float],
    text: str,
    size: int = 18,
    color: str = WHITE,
    *,
    width: Optional[int] = None,
    anchor: str = "mm",
    bold: bool = False,
    serif: bool = False,
):
    """Draw text with dynamic size shrinkage and ellipsis when exceeding width."""
    text = str(text)
    current_size = size
    font = get_font(current_size, bold=bold, serif=serif)
    if width:
        while current_size > 10 and draw.textlength(text, font=font) > width:
            current_size -= 1
            font = get_font(current_size, bold=bold, serif=serif)
        if draw.textlength(text, font=font) > width:
            while text and draw.textlength(text + "…", font=font) > width:
                text = text[:-1]
            text += "…"
    draw.text(xy, text, font=font, fill=color, anchor=anchor)


def draw_table_background(canvas: Image.Image):
    """Draw an ornate mystical velvet mat with starry accents and sacred geometry."""
    width, height = canvas.size
    draw = ImageDraw.Draw(canvas)

    # Base gradient/vignette using subtle nested shapes
    for i in range(12):
        factor = i / 12.0
        inset_x = int(factor * (width * 0.25))
        inset_y = int(factor * (height * 0.25))
        alpha = int(12 * (1.0 - factor))
        rect_color = (18, 36, 40, alpha)
        overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        d = ImageDraw.Draw(overlay)
        d.ellipse(
            (inset_x, inset_y, width - inset_x, height - inset_y),
            fill=rect_color,
        )
        canvas.alpha_composite(overlay)

    draw = ImageDraw.Draw(canvas)

    # Outer ornate borders
    draw.rounded_rectangle((14, 14, width - 15, height - 15), radius=18, outline="#1b3036", width=2)
    draw.rounded_rectangle((24, 24, width - 25, height - 25), radius=14, outline=GOLD_MUTED, width=1)
    draw.rounded_rectangle((30, 30, width - 31, height - 31), radius=10, outline="#142b2f", width=1)

    # Corner decorations (celestial diamonds)
    corner_margin = 24
    for cx, cy in (
        (corner_margin, corner_margin),
        (width - corner_margin, corner_margin),
        (corner_margin, height - corner_margin),
        (width - corner_margin, height - corner_margin),
    ):
        draw.polygon(
            [(cx, cy - 7), (cx + 7, cy), (cx, cy + 7), (cx - 7, cy)],
            fill=GOLD,
        )
        draw.ellipse((cx - 2, cy - 2, cx + 2, cy + 2), fill=GOLD_LIGHT)

    # Mystical subtle stars in background
    star_positions = [
        (80, 70), (width - 80, 70), (120, height - 70), (width - 120, height - 70),
        (width // 2 - 200, 50), (width // 2 + 200, 50),
        (width // 4, height // 2 - 120), (3 * width // 4, height // 2 - 120),
        (width // 2, height - 45),
    ]
    for sx, sy in star_positions:
        draw.ellipse((sx - 1, sy - 1, sx + 1, sy + 1), fill="#507068")


def load_and_orient_card(image_filename: str, size: Tuple[int, int], is_reversed: bool = False) -> Image.Image:
    """Load card image, resize with Lanczos, add gold card border and rotate if reversed."""
    path = TAROT_DIR / image_filename
    if not path.exists():
        # Fallback card canvas
        card_img = Image.new("RGBA", size, "#1e2c2a")
        d = ImageDraw.Draw(card_img)
        d.rectangle((2, 2, size[0] - 3, size[1] - 3), outline=GOLD, width=2)
        d.text((size[0] // 2, size[1] // 2), "TAROT", font=get_font(18, bold=True), fill=GOLD, anchor="mm")
        return card_img

    with Image.open(path) as source:
        card_img = source.convert("RGBA").resize(size, Image.Resampling.LANCZOS)

    # Rotate 180 degrees if reversed
    if is_reversed:
        card_img = card_img.rotate(180)

    # Add crisp golden border & thin inner dark rim
    cw, ch = card_img.size
    border_draw = ImageDraw.Draw(card_img)
    border_draw.rectangle((0, 0, cw - 1, ch - 1), outline=GOLD_MUTED, width=2)
    border_draw.rectangle((3, 3, cw - 4, ch - 4), outline="#0c1719", width=1)

    return card_img


def paste_card_with_shadow(
    canvas: Image.Image,
    card_img: Image.Image,
    top_left: Tuple[int, int],
    glow_color: Optional[str] = None,
):
    """Paste card onto canvas with a smooth drop shadow and optional celestial glow."""
    x, y = top_left
    cw, ch = card_img.size

    # Drop shadow
    shadow_offset = (x + 8, y + 10)
    shadow_canvas = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow_canvas)
    shadow_draw.rounded_rectangle(
        (shadow_offset[0], shadow_offset[1], shadow_offset[0] + cw, shadow_offset[1] + ch),
        radius=6,
        fill=(0, 0, 0, 150),
    )
    blurred_shadow = shadow_canvas.filter(ImageFilter.GaussianBlur(radius=8))
    canvas.alpha_composite(blurred_shadow)

    # Optional soft glow
    if glow_color:
        glow_canvas = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow_canvas)
        glow_draw.rounded_rectangle((x - 4, y - 4, x + cw + 4, y + ch + 4), radius=8, fill=glow_color)
        blurred_glow = glow_canvas.filter(ImageFilter.GaussianBlur(radius=10))
        canvas.alpha_composite(blurred_glow)

    # Paste the card itself
    canvas.alpha_composite(card_img, (x, y))


def render_single_card_table(
    card_dict: dict,
    is_reversed: bool = False,
    title: str = "CARTA DO DIA",
    subtitle: Optional[str] = None,
) -> BytesIO:
    """Render a table for a 1-card reading (Carta do Dia)."""
    width, height = 760, 680
    canvas = Image.new("RGBA", (width, height), CLOTH_BG)
    draw_table_background(canvas)
    draw = ImageDraw.Draw(canvas)

    # Header
    draw_label(
        draw,
        (width // 2, 60),
        f"✦  {title.upper()}  ✦",
        size=26,
        color=GOLD,
        bold=True,
        serif=True,
        anchor="mm",
    )
    sub = subtitle or "Oráculo de Tarot Rider-Waite · Reflexão & Energia"
    draw_label(
        draw,
        (width // 2, 92),
        sub,
        size=15,
        color=MUTED,
        anchor="mm",
        width=width - 120,
    )

    # Card dimensions
    card_w, card_h = 240, 400
    card_x = (width - card_w) // 2
    card_y = 135

    # Load and place card
    card_img = load_and_orient_card(card_dict["image"], (card_w, card_h), is_reversed=is_reversed)
    glow = (119, 229, 188, 45) if not is_reversed else (226, 184, 102, 45)
    paste_card_with_shadow(canvas, card_img, (card_x, card_y), glow_color=glow)

    # Badge under the card
    badge_y = card_y + card_h + 24
    name_pt = card_dict.get("name_pt", card_dict.get("name_en", "Carta"))
    orientation_str = "INVERTIDA 🔄" if is_reversed else "EM PÉ ☀️"
    orientation_color = GOLD if is_reversed else MINT

    # Draw card name
    draw_label(
        draw,
        (width // 2, badge_y),
        name_pt.upper(),
        size=22,
        color=WHITE,
        bold=True,
        serif=True,
        anchor="mm",
        width=card_w + 160,
    )

    # Draw orientation pill
    draw_label(
        draw,
        (width // 2, badge_y + 28),
        orientation_str,
        size=14,
        color=orientation_color,
        bold=True,
        anchor="mm",
    )

    # Footer note
    draw_label(
        draw,
        (width // 2, height - 28),
        "Rider-Waite-Smith (1909) · steve-p.org/divm · Ralsei Bot",
        size=12,
        color="#48615a",
        anchor="mm",
    )

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output


def render_three_card_table(
    cards_info: List[Tuple[dict, bool, str]],
    title: str = "TIRAGEM DE TAROT",
    question: Optional[str] = None,
) -> BytesIO:
    """
    Render a panoramic 3-card spread table (Passado / Presente / Futuro).
    cards_info: list of 3 tuples: (card_dict, is_reversed, position_label)
    """
    width, height = 1100, 680
    canvas = Image.new("RGBA", (width, height), CLOTH_BG)
    draw_table_background(canvas)
    draw = ImageDraw.Draw(canvas)

    # Top Header
    draw_label(
        draw,
        (width // 2, 54),
        f"✦  {title.upper()}  ✦",
        size=26,
        color=GOLD,
        bold=True,
        serif=True,
        anchor="mm",
    )

    # Question or subtitle
    if question:
        q_text = f"“{question}”"
        draw_label(
            draw,
            (width // 2, 86),
            q_text,
            size=16,
            color=MINT,
            anchor="mm",
            width=width - 160,
        )
    else:
        draw_label(
            draw,
            (width // 2, 86),
            "Tiragem das Três Fases: Passado · Presente · Futuro",
            size=15,
            color=MUTED,
            anchor="mm",
        )

    # Cards layout
    card_w, card_h = 216, 360
    gap = 70
    total_cards_w = (3 * card_w) + (2 * gap)
    start_x = (width - total_cards_w) // 2
    card_y = 135

    for idx, (card_dict, is_reversed, pos_label) in enumerate(cards_info[:3]):
        cx = start_x + idx * (card_w + gap)

        # Card image
        card_img = load_and_orient_card(card_dict["image"], (card_w, card_h), is_reversed=is_reversed)
        glow = (119, 229, 188, 35) if not is_reversed else (226, 184, 102, 35)
        paste_card_with_shadow(canvas, card_img, (cx, card_y), glow_color=glow)

        # Position Label above card
        draw_label(
            draw,
            (cx + card_w // 2, card_y - 18),
            pos_label.upper(),
            size=13,
            color=GOLD_LIGHT,
            bold=True,
            anchor="mm",
        )

        # Labels below card
        badge_y = card_y + card_h + 20
        name_pt = card_dict.get("name_pt", card_dict.get("name_en", "Carta"))
        draw_label(
            draw,
            (cx + card_w // 2, badge_y),
            name_pt,
            size=18,
            color=WHITE,
            bold=True,
            serif=True,
            anchor="mm",
            width=card_w + 30,
        )

        orientation_str = "Invertida 🔄" if is_reversed else "Em pé ☀️"
        orientation_color = GOLD if is_reversed else MINT
        draw_label(
            draw,
            (cx + card_w // 2, badge_y + 24),
            orientation_str,
            size=13,
            color=orientation_color,
            bold=True,
            anchor="mm",
        )

    # Footer note
    draw_label(
        draw,
        (width // 2, height - 28),
        "Baralho Rider-Waite-Smith (1909) · steve-p.org/divm · Ralsei Bot",
        size=12,
        color="#48615a",
        anchor="mm",
    )

    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG", optimize=True)
    output.seek(0)
    return output

