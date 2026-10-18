"""Data loader, deck management and interpretation engine for Tarot readings."""
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import random
from typing import Dict, List, Optional, Tuple

DECK_PATH = Path(__file__).resolve().parent.parent / "assets" / "tarot_deck.json"


@lru_cache(maxsize=1)
def load_deck() -> List[Dict]:
    """Load the complete 78-card Rider-Waite-Smith deck from JSON."""
    with open(DECK_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_card(card_id: str) -> Optional[Dict]:
    """Retrieve a card by its identifier."""
    for card in load_deck():
        if card["id"] == card_id:
            return card
    return None


def get_daily_seed(user_id: int) -> int:
    """Generate a deterministic daily seed per user based on UTC date."""
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    raw = f"tarot-daily-{user_id}-{today_str}"
    return int(hashlib.sha256(raw.encode()).hexdigest(), 16) % (2**31)


def draw_cards(count: int = 1, *, seed: Optional[int] = None) -> List[Tuple[Dict, bool]]:
    """
    Draw `count` unique cards from the deck.
    Returns a list of tuples: (card_dict, is_reversed).
    """
    deck = load_deck()
    rng = random.Random(seed) if seed is not None else random.Random()
    chosen_cards = rng.sample(deck, count)

    result = []
    for card in chosen_cards:
        # Classical ~30% probability of reversed orientation
        is_reversed = rng.random() < 0.30
        result.append((card, is_reversed))
    return result


def get_daily_card(user_id: int) -> Tuple[Dict, bool]:
    """Get the deterministic Carta do Dia for a specific user."""
    seed = get_daily_seed(user_id)
    return draw_cards(count=1, seed=seed)[0]


def format_card_reading(card: Dict, is_reversed: bool) -> Dict[str, str]:
    """Return formatted reading strings for display in embeds."""
    orientation_name = "Invertida 🔄" if is_reversed else "Em pé ☀️"
    keywords = card["keywords_reversed"] if is_reversed else card["keywords_upright"]
    waite_raw = card["div_mean_rev_en"] if is_reversed else card["div_mean_en"]
    add_raw = card["add_mean_rev_en"] if is_reversed else card["add_mean_en"]

    return {
        "name_pt": card["name_pt"],
        "name_en": card["name_en"],
        "orientation": orientation_name,
        "is_reversed": is_reversed,
        "symbol": card.get("symbol", "✨"),
        "suit_pt": card["suit_pt"],
        "element": card["element"],
        "keywords": keywords,
        "waite_meaning": waite_raw,
        "additional_meaning": add_raw,
    }

