"""Compose the supplied table, card assets and the bot's Discord avatar."""
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

from cogs.poker_rules import STREETS
from cogs.uno_render import _font

ASSETS = Path(__file__).resolve().parent.parent / "assets"
MINT = "#77e5bc"
WHITE = "#f0f5f3"
MUTED = "#9eaead"
POSITIONS = ((350, 230), (850, 230), (1040, 451), (850, 669), (350, 669), (160, 451))


@lru_cache(maxsize=64)
def font(size, bold=False):
    return _font(size, bold)


def label(draw, xy, text, size=18, color=WHITE, *, width=None, anchor="mm", bold=False):
    text = str(text)
    while width and size > 11 and draw.textlength(text, font=font(size, bold)) > width:
        size -= 1
    if width and draw.textlength(text, font=font(size, bold)) > width:
        while text and draw.textlength(text + "…", font=font(size, bold)) > width:
            text = text[:-1]
        text += "…"
    draw.text(xy, text, font=font(size, bold), fill=color, anchor=anchor)


def png(canvas):
    output = BytesIO()
    canvas.convert("RGB").save(output, format="PNG")
    output.seek(0)
    return output


@lru_cache(maxsize=96)
def card_image(card=None, size=(68, 99)):
    if card is not None:
        with Image.open(ASSETS / "cards" / card.filename) as source:
            return source.convert("RGBA").resize(size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", size)
    draw = ImageDraw.Draw(canvas)
    w, h = size
    draw.rounded_rectangle((0, 0, w - 1, h - 1), radius=6, fill="#b7c7c2")
    draw.rounded_rectangle((3, 3, w - 4, h - 4), radius=4, fill="#173f34", outline=MINT)
    for y in range(12, h - 9, 12):
        for x in range(10, w - 8, 12):
            draw.polygon(((x, y - 3), (x + 3, y), (x, y + 3), (x - 3, y)), fill="#35785f")
    return canvas


@lru_cache(maxsize=1)
def table_image():
    with Image.open(ASSETS / "poker" / "table.png") as source:
        return source.convert("RGBA").resize((1000, 500), Image.Resampling.LANCZOS)


def render_table(players, *, game=None, stake=1000, dealer_avatar=None, cancelled=False):
    """Public board: reveal hole cards ONLY at showdown, excluding folded hands."""
    canvas = Image.new("RGBA", (1200, 820), "#0d1519")
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((16, 16, 1183, 803), radius=26, outline="#243d38", width=2)
    label(draw, (45, 53), "TEXAS HOLD’EM", 30, MINT, anchor="lm", bold=True)
    label(draw, (45, 87), "Uma mão · No limit · DarkMoney", 16, MUTED, anchor="lm")
    label(draw, (1155, 53), f"Entrada  {stake:,} D$", 24, anchor="rm", width=360, bold=True)
    stage = "Cancelada" if cancelled else STREETS[game.street] if game else "Lobby aberto"
    label(draw, (1155, 86), stage.upper(), 16, MINT, anchor="rm")
    canvas.alpha_composite(table_image(), (100, 170))

    # The dealer is the bot's actual profile picture, fetched by the cog.
    if dealer_avatar:
        with Image.open(BytesIO(dealer_avatar)) as source:
            avatar = ImageOps.fit(source.convert("RGBA"), (104, 104), method=Image.Resampling.LANCZOS)
        mask = Image.new("L", avatar.size)
        ImageDraw.Draw(mask).ellipse((0, 0, 103, 103), fill=255)
        draw.ellipse((544, 130, 655, 241), outline=MINT, width=3)
        canvas.paste(avatar, (548, 134), mask)
    label(draw, (600, 261), "Ralsei · Dealer", 18, MINT, bold=True)

    board = game.board if game else []
    label(draw, (600, 339), "POTE" if game else "ENTRADA POR PESSOA", 14, MUTED, bold=True)
    label(draw, (600, 369), f"{game.pot if game else stake:,} D$", 28, bold=True)
    for index in range(5):
        x, y = 410 + index * 78, 399
        if index < len(board):
            canvas.alpha_composite(card_image(board[index]), (x, y))
        else:
            draw.rounded_rectangle((x, y, x + 67, y + 98), radius=6, fill="#202725", outline="#56635e")
            label(draw, (x + 34, y + 49), ("F", "F", "F", "T", "R")[index], 22, "#677771")
    if game and not game.done:
        label(draw, (600, 527), f"Vez de {game.actor.name}", 21, MINT, width=510, bold=True)
    elif game and game.done:
        winner_ids = {pid for _, winners in game.pots for pid in winners}
        names = ", ".join(p.name for p in players if p.id in winner_ids)
        label(draw, (600, 527), names, 21, MINT, width=510, bold=True)
    else:
        label(draw, (600, 527), "Entre e aguarde o anfitrião começar", 19, MINT, width=510)

    positions = POSITIONS if len(players) == 6 else (
        POSITIONS[0], POSITIONS[1], POSITIONS[2], (600, 669), POSITIONS[5])
    for index, player in enumerate(players):
        cx, cy = positions[index]
        active = game and not game.done and game.actor.id == player.id
        revealed = bool(game and game.showdown and not player.folded)
        for offset in range(2):
            if player.folded:
                break
            card = player.cards[offset] if revealed else None
            canvas.alpha_composite(card_image(card, (45, 66)), (cx - 48 + offset * 51, cy - 66))
        edge = MINT if active else "#465956" if not player.folded else "#353c3d"
        draw.rounded_rectangle((cx - 112, cy + 7, cx + 112, cy + 88), radius=13,
                               fill="#162323", outline=edge, width=3 if active else 1)
        name = player.name + (" · BOT" if player.bot else "")
        label(draw, (cx, cy + 25), name, 18, MUTED if player.folded else WHITE, width=202, bold=True)
        label(draw, (cx, cy + 51), f"{player.stack:,} D$", 20, MINT, width=202, bold=True)
        status = player.last_action if game else "Pronto para jogar"
        label(draw, (cx, cy + 73), status, 12, MUTED, width=202)
        if game:
            badges = []
            if index == game.button:
                badges.append("D")
            if index == game.sb_index:
                badges.append("SB")
            if index == game.bb_index:
                badges.append("BB")
            if badges:
                label(draw, (cx + 80, cy - 30), "/".join(badges), 14, "#edcd7c", bold=True)
    footer = ("Mesa encerrada · entradas devolvidas" if cancelled else
              "Mão encerrada · fichas finais devolvidas ao saldo" if game and game.done else
              "Suas cartas ficam em ‘Ver minhas cartas’ · 60 segundos por jogada" if game else
              "1 pessoa: +4 bots · 2–6 pessoas: multiplayer · Ralsei distribui as cartas")
    label(draw, (600, 784), footer, 16, MUTED, width=1120)
    return png(canvas)


def render_hand(player):
    canvas = Image.new("RGBA", (680, 400), "#0d1519")
    draw = ImageDraw.Draw(canvas)
    label(draw, (340, 35), "SUAS CARTAS", 24, MINT, bold=True)
    label(draw, (340, 68), player.name, 18, width=600)
    for index, card in enumerate(player.cards):
        canvas.alpha_composite(card_image(card, (170, 247)), (155 + index * 200, 104))
    label(draw, (340, 378), "Somente você pode ver esta mensagem", 16, MUTED)
    return png(canvas)
