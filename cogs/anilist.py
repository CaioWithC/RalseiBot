"""AniList profile lookup and card generator for RalseiBot."""
import asyncio
from io import BytesIO
import logging
import os
from pathlib import Path
import re
from typing import Dict, List, Optional, Tuple

import aiohttp
import nextcord
from nextcord.ext import commands
from PIL import Image, ImageDraw, ImageFont, ImageOps

from db import database, EconomyError
from cogs.command_support import DualCommand

log = logging.getLogger(__name__)

ANILIST_COLOR = 0x02A9FF
ANILIST_API_URL = "https://graphql.anilist.co"

USER_QUERY = """
query ($name: String) {
  User(name: $name) {
    id
    name
    siteUrl
    avatar {
      large
      medium
    }
    statistics {
      anime {
        count
        minutesWatched
        meanScore
        genres(limit: 5, sort: COUNT_DESC) {
          genre
          count
        }
      }
      manga {
        count
      }
    }
    favourites {
      anime {
        nodes {
          id
          coverImage {
            large
            medium
          }
        }
      }
      manga {
        nodes {
          id
          coverImage {
            large
            medium
          }
        }
      }
    }
  }
}
"""

GENRE_COLORS: Dict[str, str] = {
    "Slice of Life": "#55d836",
    "Comedy": "#02a9ff",
    "Romance": "#9256f3",
    "Psychological": "#f779a4",
    "Drama": "#e85d75",
    "Action": "#e85d04",
    "Adventure": "#2ec4b6",
    "Fantasy": "#7b2cbf",
    "Sci-Fi": "#00b4d8",
    "Supernatural": "#8338ec",
    "Mystery": "#3a86ff",
    "Horror": "#b5179e",
    "Sports": "#f3722c",
    "Mecha": "#4a4e69",
    "Music": "#ff006e",
    "Thriller": "#d90429",
    "Ecchi": "#ff70a6",
    "Mahou Shoujo": "#ff99c8",
}
FALLBACK_PALETTE = ["#55d836", "#02a9ff", "#9256f3", "#f779a4", "#e85d75", "#f3722c", "#2ec4b6", "#ff006e"]


def get_genre_color(genre: str, index: int = 0) -> str:
    """Return mapped color for a genre or a bright fallback palette color."""
    return GENRE_COLORS.get(genre, FALLBACK_PALETTE[index % len(FALLBACK_PALETTE)])


def font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    """Return clean modern sans-serif font across Windows and Linux Docker."""
    candidates = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "segoeuib.ttf" if bold else "segoeui.ttf",
        "arialbd.ttf" if bold else "arial.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size, encoding="unic")
        except OSError:
            pass
    return ImageFont.load_default()


def _rounded_cover(source: Image.Image, size: Tuple[int, int], radius: int = 6) -> Image.Image:
    """Crop and resize poster to given size with smooth rounded corners."""
    fit_im = ImageOps.fit(source.convert("RGBA"), size, method=Image.Resampling.LANCZOS)
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    result = Image.new("RGBA", size, (0, 0, 0, 0))
    result.paste(fit_im, (0, 0), mask=mask)
    return result


def render_anilist_overview(
    anime_covers: List[Image.Image],
    manga_covers: List[Image.Image],
    genres_stats: List[dict],
) -> BytesIO:
    """Render the 3 cards (Anime, Manga, Genre Overview) as an attached PNG."""
    card_w = 490
    outer_bg = "#0b1622"  # AniList dark container
    inner_bg = "#151f2e"  # AniList card surface
    title_color = "#9fadbd"  # AniList muted bluish-grey text
    border_color = "#151f2e"

    card1_h = 196
    card2_h = 196
    card3_h = 124
    gap = 16

    total_h = card1_h + gap + card2_h + gap + card3_h
    # Transparent canvas so the Discord dark embed background fills between cards
    canvas = Image.new("RGBA", (card_w, total_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    f_title = font(14, bold=True)
    f_badge = font(11, bold=True)
    f_entry_num = font(11, bold=True)
    f_entry_txt = font(11, bold=False)
    f_empty = font(13, bold=False)

    def draw_card_base(y: int, height: int, title: str) -> Tuple[int, int]:
        draw.rounded_rectangle((0, y, card_w - 1, y + height - 1), radius=8, fill=outer_bg, outline=border_color, width=1)
        draw.text((18, y + 10), title, font=f_title, fill=title_color)
        inner_y = y + 33
        inner_h = height - 43
        draw.rounded_rectangle((10, inner_y, card_w - 11, inner_y + inner_h - 1), radius=6, fill=inner_bg)
        return inner_y, inner_h

    # Card 1: Anime
    c1_inner_y, c1_inner_h = draw_card_base(0, card1_h, "Anime")
    if anime_covers:
        cover_w, cover_h = 85, 118
        start_x = 22
        cover_gap = 21
        top_y = c1_inner_y + (c1_inner_h - cover_h) // 2
        for i, c_img in enumerate(anime_covers[:4]):
            x = start_x + i * (cover_w + cover_gap)
            c_rounded = _rounded_cover(c_img, (cover_w, cover_h), radius=6)
            canvas.paste(c_rounded, (x, top_y), mask=c_rounded)
    else:
        draw.text((card_w // 2, c1_inner_y + c1_inner_h // 2), "Nenhum anime favorito", font=f_empty, fill="#5c728a", anchor="mm")

    # Card 2: Manga
    c2_y = card1_h + gap
    c2_inner_y, c2_inner_h = draw_card_base(c2_y, card2_h, "Manga")
    if manga_covers:
        cover_w, cover_h = 85, 118
        start_x = 22
        cover_gap = 21
        top_y = c2_inner_y + (c2_inner_h - cover_h) // 2
        for i, c_img in enumerate(manga_covers[:4]):
            x = start_x + i * (cover_w + cover_gap)
            c_rounded = _rounded_cover(c_img, (cover_w, cover_h), radius=6)
            canvas.paste(c_rounded, (x, top_y), mask=c_rounded)
    else:
        draw.text((card_w // 2, c2_inner_y + c2_inner_h // 2), "Nenhum mangá favorito", font=f_empty, fill="#5c728a", anchor="mm")

    # Card 3: Genre Overview
    c3_y = card1_h + gap + card2_h + gap
    c3_inner_y, c3_inner_h = draw_card_base(c3_y, card3_h, "Genre Overview")

    if genres_stats:
        top_genres = genres_stats[:5]
        badge_h = 22
        badge_y = c3_inner_y + 11
        padding_h = 10

        badge_widths = []
        for g_data in top_genres:
            g_name = g_data["genre"]
            w = int(draw.textlength(g_name, font=f_badge)) + padding_h * 2
            badge_widths.append(w)

        inner_w = card_w - 22
        num_badges = len(top_genres)
        total_badges_w = sum(badge_widths)
        available_space = inner_w - 20 - total_badges_w
        badge_gap = max(6, available_space // (num_badges - 1)) if num_badges > 1 else 0

        cur_x = 10 + 10 + (available_space - badge_gap * (num_badges - 1)) // 2 if available_space > 0 else 20

        for i, g_data in enumerate(top_genres):
            g_name = g_data["genre"]
            count = g_data["count"]
            color = get_genre_color(g_name, i)
            b_w = badge_widths[i]

            draw.rounded_rectangle((cur_x, badge_y, cur_x + b_w, badge_y + badge_h), radius=4, fill=color)
            draw.text((cur_x + b_w // 2, badge_y + badge_h // 2), g_name, font=f_badge, fill="#ffffff", anchor="mm")

            sub_y = badge_y + badge_h + 8
            count_str = str(count)
            entries_str = " Entries"
            w_cnt = draw.textlength(count_str, font=f_entry_num)
            w_ent = draw.textlength(entries_str, font=f_entry_txt)
            total_sub_w = w_cnt + w_ent

            sub_start_x = cur_x + (b_w - total_sub_w) / 2
            draw.text((sub_start_x, sub_y), count_str, font=f_entry_num, fill=color, anchor="la")
            draw.text((sub_start_x + w_cnt, sub_y), entries_str, font=f_entry_txt, fill="#5c728a", anchor="la")

            cur_x += b_w + badge_gap

        bar_x = 22
        bar_w = card_w - 44
        bar_y = c3_inner_y + c3_inner_h - 16
        bar_h = 8
        bar_radius = 4

        total_entries = sum(g["count"] for g in top_genres) or 1
        bar_img = Image.new("RGBA", (bar_w, bar_h), (0, 0, 0, 0))
        bar_draw = ImageDraw.Draw(bar_img)

        seg_x = 0
        for i, g_data in enumerate(top_genres):
            color = get_genre_color(g_data["genre"], i)
            if i == len(top_genres) - 1:
                seg_w = bar_w - seg_x
            else:
                seg_w = max(2, int(bar_w * (g_data["count"] / total_entries)))
            bar_draw.rectangle((seg_x, 0, seg_x + seg_w, bar_h), fill=color)
            seg_x += seg_w

        bar_mask = Image.new("L", (bar_w, bar_h), 0)
        ImageDraw.Draw(bar_mask).rounded_rectangle((0, 0, bar_w - 1, bar_h - 1), radius=bar_radius, fill=255)
        canvas.paste(bar_img, (bar_x, bar_y), mask=bar_mask)
    else:
        draw.text((card_w // 2, c3_inner_y + c3_inner_h // 2), "Nenhum dado de gênero disponível", font=f_empty, fill="#5c728a", anchor="mm")

    out = BytesIO()
    canvas.save(out, format="PNG", optimize=True)
    out.seek(0)
    return out


async def fetch_anilist_data(username: str) -> dict:
    """Fetch profile data from AniList GraphQL API."""
    payload = {"query": USER_QUERY, "variables": {"name": username}}
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "RalseiBot/1.0",
    }
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        try:
            async with session.post(ANILIST_API_URL, json=payload, headers=headers) as resp:
                if resp.status == 404:
                    raise EconomyError(f"Usuário **{username}** não foi encontrado no AniList.")
                if resp.status != 200:
                    text = await resp.text()
                    log.warning("AniList API returned %d: %s", resp.status, text[:200])
                    raise EconomyError("Não foi possível consultar o AniList no momento. Tente novamente mais tarde.")
                data = await resp.json()
        except asyncio.TimeoutError as error:
            raise EconomyError("O AniList demorou muito para responder. Tente novamente.") from error
        except aiohttp.ClientError as error:
            raise EconomyError("Erro ao conectar à API do AniList. Verifique sua conexão.") from error

    user = data.get("data", {}).get("User")
    if not user:
        raise EconomyError(f"Usuário **{username}** não foi encontrado no AniList.")
    return user


async def download_image(session: aiohttp.ClientSession, url: str) -> Optional[Image.Image]:
    """Download single image asynchronously and open as PIL Image."""
    if not url:
        return None
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=8)) as resp:
            if resp.status == 200:
                raw = await resp.read()
                return Image.open(BytesIO(raw))
    except Exception:
        pass
    return None


async def download_covers(urls: List[str]) -> List[Image.Image]:
    """Download list of image URLs concurrently."""
    if not urls:
        return []
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        tasks = [download_image(session, u) for u in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, Image.Image)]


class AniList(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.storage = database

    @commands.command(
        cls=DualCommand,
        name="anilist",
        aliases=["al"],
        help="Veja o perfil e estatísticas do AniList: r.anilist [usuário ou @membro]. Use 'set <usuário>' para vincular ou 'unlink' para desvincular.",
    )
    @commands.cooldown(1, 4, lambda message: message.author.id)
    async def anilist(
        self,
        ctx,
        usuario: str = None,
        membro: nextcord.User = None,
        acao: str = None,
    ):
        target_user = membro
        target_user_id = membro.id if membro else None
        target_username = usuario
        selected_action = acao

        if target_username:
            cleaned = target_username.strip()
            # Clean up URLs like https://anilist.co/user/CaioWithC/
            if url_match := re.match(r"^https?://(?:www\.)?anilist\.co/user/([^/?#]+)/?.*$", cleaned, re.IGNORECASE):
                cleaned = url_match.group(1).strip()

            if cleaned.lower() in {"unlink", "desvincular", "reset", "remover"}:
                selected_action = "desvincular"
                target_username = None
            elif mention_match := re.match(r"^<@!?(\d+)>$", cleaned):
                target_user_id = int(mention_match.group(1))
                target_user = (ctx.guild.get_member(target_user_id) if ctx.guild else None) or self.bot.get_user(target_user_id)
                target_username = None
            elif cleaned.isdigit() and len(cleaned) >= 17:
                target_user_id = int(cleaned)
                target_user = (ctx.guild.get_member(target_user_id) if ctx.guild else None) or self.bot.get_user(target_user_id)
                target_username = None
            elif cleaned.lower().startswith(("set ", "link ", "vincular ")):
                parts = cleaned.split(maxsplit=1)
                selected_action = "vincular"
                target_username = parts[1].strip() if len(parts) > 1 else None
            else:
                target_username = cleaned

        # Action: unlink
        if selected_action in {"desvincular", "unlink"}:
            data = self.storage.profile(ctx.author.id)
            if not data.get("anilist"):
                raise EconomyError("Você não possui uma conta do AniList vinculada.")
            self.storage.update_profile(ctx.author.id, anilist=None)
            await ctx.send("Sua conta do AniList foi desvinculada com sucesso.")
            return

        # Target member's profile
        if target_user_id and target_user_id != ctx.author.id:
            data = self.storage.profile(target_user_id)
            linked_name = data.get("anilist")
            if not linked_name:
                name = target_user.display_name if target_user else f"UID {target_user_id}"
                raise EconomyError(f"**{name}** ainda não vinculou uma conta do AniList.")
            target_username = linked_name

        # No user specified: check author's linked account
        if not target_username:
            data = self.storage.profile(ctx.author.id)
            target_username = data.get("anilist")
            if not target_username:
                raise EconomyError(
                    "Informe um usuário do AniList: `r.anilist <usuario>` ou vincule sua conta com `r.anilist set <usuario>`."
                )

        # Action: link
        if selected_action in {"vincular", "link", "set"}:
            if not target_username:
                raise EconomyError("Informe o nome de usuário do AniList para vincular: `r.anilist set <usuario>`.")
            user_data = await fetch_anilist_data(target_username)
            real_username = user_data["name"]
            self.storage.update_profile(ctx.author.id, anilist=real_username)
            prefix_msg = f"Sua conta do AniList foi vinculada como **{real_username}**!\n"
        else:
            user_data = await fetch_anilist_data(target_username)
            prefix_msg = ""

        # Extract stats
        name = user_data["name"]
        site_url = user_data.get("siteUrl") or f"https://anilist.co/user/{name}"
        avatar_url = (user_data.get("avatar") or {}).get("large")

        stats = (user_data.get("statistics") or {}).get("anime") or {}
        anime_count = stats.get("count", 0)
        minutes_watched = stats.get("minutesWatched", 0)
        days_watched = round(minutes_watched / 1440, 1)
        mean_score = round(stats.get("meanScore", 0) or 0.0, 1)
        genres = stats.get("genres", []) or []

        # Extract favorite covers
        fav_anime_nodes = ((user_data.get("favourites") or {}).get("anime") or {}).get("nodes") or []
        fav_manga_nodes = ((user_data.get("favourites") or {}).get("manga") or {}).get("nodes") or []

        anime_urls = [
            (n.get("coverImage") or {}).get("large") or (n.get("coverImage") or {}).get("medium")
            for n in fav_anime_nodes[:4]
            if n.get("coverImage")
        ]
        manga_urls = [
            (n.get("coverImage") or {}).get("large") or (n.get("coverImage") or {}).get("medium")
            for n in fav_manga_nodes[:4]
            if n.get("coverImage")
        ]

        # Download cover images concurrently
        anime_covers = await download_covers(anime_urls)
        manga_covers = await download_covers(manga_urls)

        # Render 3-card image asynchronously
        image_bytes = await asyncio.to_thread(
            render_anilist_overview,
            anime_covers,
            manga_covers,
            genres,
        )

        # Build Discord Embed matching reference
        desc = (
            f"**Nome: {name}**\n\n"
            f"Total Anime: {anime_count}\n"
            f"Days Watched: {days_watched:.1f}\n"
            f"Mean Score: {mean_score:.1f}"
        )

        embed = nextcord.Embed(
            title="AniList",
            url=site_url,
            description=desc,
            color=ANILIST_COLOR,
        )
        if avatar_url:
            embed.set_thumbnail(url=avatar_url)
        embed.set_image(url="attachment://anilist_overview.png")

        file = nextcord.File(fp=image_bytes, filename="anilist_overview.png")
        await ctx.send(content=prefix_msg if prefix_msg else None, embed=embed, file=file)


def setup(bot):
    bot.add_cog(AniList(bot))

