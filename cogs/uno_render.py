"""Discord-sized Six card images with replaceable, optional deck artwork.

These placeholders are deliberately simple UI, not the finished deck. Asset
files are opened on each render, so newly supplied artwork takes effect at once.
The functions accept the engine's Card objects without importing game state.
"""
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps, UnidentifiedImageError


DEFAULT_ASSET_DIR = Path(__file__).resolve().parent.parent / "assets" / "uno"
DECKS = {"normal": "Normal", "meme": "Meme", "overwatch": "Overwatch"}
MAX_ASSET_PIXELS = 16_000_000
MAX_HAND_CARDS = 25
CARD_SIZE = (300, 450)
HAND_CARD_SIZE = (120, 180)
HAND_COLUMNS = 7
COLORS = {
    "red": ("Vermelho", "🔴", "#bd3342"),
    "yellow": ("Amarelo", "🟡", "#c49417"),
    "green": ("Verde", "🟢", "#21845b"),
    "blue": ("Azul", "🔵", "#346fc1"),
}
ACTIONS = {
    "skip": ("Bloqueio", "PULA"),
    "reverse": ("Inverter", "INVERTE"),
    "draw2": ("Comprar +2", "+2"),
    "wild": ("Coringa", "CORINGA"),
    "wild4": ("Coringa +4", "+4"),
}


def _value(card):
    return str(card.value).lower()


def card_label(card) -> str:
    """A concise Portuguese label, usable even without an image attachment."""
    value = _value(card)
    if value in ("wild", "wild4"):
        return "🃏 " + ACTIONS[value][0]
    color_name, emoji, _ = COLORS.get(card.color, ("Sem cor", "⚪", "#393749"))
    value_name = ACTIONS.get(value, (value, value))[0]
    return f"{emoji} {value_name} · {color_name}"


def _font(size, bold=False):
    filename = "arialbd.ttf" if bold else "arial.ttf"
    dejavu = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for candidate in (
        str(Path("C:/Windows/Fonts") / filename),
        str(Path("/usr/share/fonts/truetype/dejavu") / dejavu),
        dejavu,
        filename,
    ):
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            pass
    return ImageFont.load_default(size=size)


def _center_text(draw, xy, label, size, fill, max_width=None):
    font = _font(size, bold=True)
    if max_width:
        while size > 10 and draw.textlength(label, font=font) > max_width:
            size -= 1
            font = _font(size, bold=True)
    draw.text(xy, label, font=font, fill=fill, anchor="mm")


def _asset_name(card):
    """Use an allowlist, rather than letting card metadata construct paths."""
    value = _value(card)
    if value in ("wild", "wild4"):
        return f"{value}.png"
    if card.color in COLORS and value in tuple(str(n) for n in range(10)) + (
        "skip", "reverse", "draw2"
    ):
        return f"{card.color}_{value}.png"
    return None


def _load_asset(card, asset_dir):
    filename = _asset_name(card)
    if filename is None:
        return None
    directory = Path(asset_dir) if asset_dir is not None else DEFAULT_ASSET_DIR
    try:
        with Image.open(directory / filename) as source:
            if source.width * source.height > MAX_ASSET_PIXELS:
                return None
            artwork = ImageOps.contain(source.convert("RGBA"), CARD_SIZE,
                                       method=Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", CARD_SIZE, "#242230")
        canvas.alpha_composite(artwork, ((CARD_SIZE[0] - artwork.width) // 2,
                                         (CARD_SIZE[1] - artwork.height) // 2))
        return canvas
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError):
        # Partial uploads, absent files and unsupported artwork keep the UI usable.
        return None


def _placeholder(card, deck="normal"):
    value = _value(card)
    wild = value in ("wild", "wild4")
    color_name, _, fill = COLORS.get(card.color, ("Coringa", "🃏", "#393749"))
    if wild:
        color_name, fill = "Coringa", "#393749"
    canvas = Image.new("RGBA", CARD_SIZE, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((1, 1, 298, 448), radius=27, fill="#f4f2ec")
    draw.rounded_rectangle((9, 9, 290, 440), radius=21, fill=fill)
    draw.rounded_rectangle((27, 103, 272, 341), radius=24,
                           fill="#242230" if wild else "#f4f2ec")
    symbol = ACTIONS.get(value, (value, value))[1]
    corner = {"skip": "X", "reverse": "<>"}.get(value, symbol)
    _center_text(draw, (53, 48), corner, 35, "#ffffff", max_width=79)
    _center_text(draw, (247, 400), corner, 35, "#ffffff", max_width=79)
    _center_text(draw, (150, 218), symbol, 126 if value.isdigit() else 79,
                 "#ffffff" if wild else fill, max_width=219)
    _center_text(draw, (150, 363), color_name.upper(), 23, "#ffffff", max_width=248)
    if wild:
        for index, (_, _, color) in enumerate(COLORS.values()):
            left = 54 + index * 50
            draw.rounded_rectangle((left, 286, left + 40, 314), radius=8, fill=color)
    if deck == "meme":
        # A distinct provisional comic frame; final meme images replace the whole face.
        draw.rounded_rectangle((5, 5, 294, 444), radius=23, outline="#ff75dc", width=7)
        draw.polygon(((76, 112), (65, 80), (102, 102), (150, 86), (201, 102),
                      (236, 81), (226, 112)), fill="#fff070")
        draw.rounded_rectangle((83, 381, 217, 426), radius=8, fill="#50204f")
        _center_text(draw, (150, 404), "MEME", 25, "#fff070")
    elif deck == "overwatch":
        # Orange/graphite frame keeps the gameplay color and number readable.
        draw.rounded_rectangle((5, 5, 294, 444), radius=23, outline="#f99e1a", width=7)
        draw.polygon(((83, 14), (216, 14), (199, 69), (101, 69)), fill="#202b36")
        draw.line(((103, 69), (197, 69)), fill="#f99e1a", width=5)
        draw.rounded_rectangle((70, 381, 230, 426), radius=5, fill="#202b36")
        _center_text(draw, (150, 404), "OVERWATCH", 21, "#f99e1a")
    return canvas


def _card_image(card, asset_dir, deck):
    artwork = _load_asset(card, asset_dir)
    return artwork if artwork is not None else _placeholder(card, deck)


def _deck_directory(deck, asset_dir):
    if deck not in DECKS:
        raise ValueError("Escolha um baralho: normal, meme ou overwatch.")
    return Path(asset_dir) if asset_dir is not None else DEFAULT_ASSET_DIR / deck


def _png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    output.seek(0)
    return output


def render_card(card, asset_dir=None, *, deck="normal") -> BytesIO:
    """Render the table's top card; a supplied asset replaces its placeholder."""
    return _png(_card_image(card, _deck_directory(deck, asset_dir), deck))


def render_hand(cards, selected_ids=(), asset_dir=None, *, deck="normal") -> BytesIO:
    """Render up to 25 cards, with selected cards raised and outlined in gold.

    The caller paginates larger hands. Indices in this image start at one for
    each page, matching the order passed by the caller. Selected cards are
    composited last so their faces remain fully visible in overlapping rows.
    """
    asset_dir = _deck_directory(deck, asset_dir)
    cards = list(cards)
    if len(cards) > MAX_HAND_CARDS:
        raise ValueError("Renderize no máximo 25 cartas por página.")
    if not cards:
        canvas = Image.new("RGB", (360, 120), "#211c2b")
        _center_text(ImageDraw.Draw(canvas), (180, 60), "Sem cartas", 25, "#d6d1df")
        return _png(canvas)

    selected_ids = set(selected_ids)
    columns = min(HAND_COLUMNS, len(cards))
    rows = (len(cards) + HAND_COLUMNS - 1) // HAND_COLUMNS
    margin, step_x, step_y, raised = 16, 103, 227, 18
    width = margin * 2 + HAND_CARD_SIZE[0] + step_x * (columns - 1)
    height = margin * 2 + rows * step_y
    canvas = Image.new("RGBA", (width, height), "#211c2b")

    for row in range(rows):
        row_cards = list(enumerate(cards[row * HAND_COLUMNS:(row + 1) * HAND_COLUMNS],
                                   start=row * HAND_COLUMNS))
        for index, card in sorted(row_cards, key=lambda entry: entry[1].uid in selected_ids):
            selected = card.uid in selected_ids
            x = margin + (index % HAND_COLUMNS) * step_x
            base_y = margin + row * step_y + raised
            y = base_y - raised if selected else base_y
            face = _card_image(card, asset_dir, deck).resize(HAND_CARD_SIZE, Image.Resampling.LANCZOS)
            draw = ImageDraw.Draw(canvas)
            if selected:
                draw.rounded_rectangle((x - 4, y - 4, x + HAND_CARD_SIZE[0] + 3,
                                        y + HAND_CARD_SIZE[1] + 3),
                                       radius=13, fill="#ffd76a")
            canvas.alpha_composite(face, (x, y))
            # Fixed baseline keeps page indices legible even for raised cards.
            draw = ImageDraw.Draw(canvas)
            _center_text(draw, (x + HAND_CARD_SIZE[0] // 2, base_y + HAND_CARD_SIZE[1] + 15),
                         str(index + 1), 17, "#ffd76a" if selected else "#d6d1df")

    return _png(canvas.convert("RGB"))
