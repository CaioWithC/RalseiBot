"""Offline checks for usable deck fallbacks and replaceable card artwork."""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from cogs.uno_render import card_label, render_card, render_hand


def card(uid="first", color="red", value="3"):
    return SimpleNamespace(uid=uid, color=color, value=value)


class UnoRenderTests(unittest.TestCase):
    def test_three_decks_have_distinct_placeholders_in_table_and_hand(self):
        with TemporaryDirectory() as directory:
            tops, hands = set(), set()
            for deck in ("normal", "meme", "overwatch"):
                tops.add(render_card(card(), directory, deck=deck).getvalue())
                hands.add(render_hand([card()], asset_dir=directory, deck=deck).getvalue())
            self.assertEqual(len(tops), 3)
            self.assertEqual(len(hands), 3)

    def test_each_deck_loads_its_own_art_in_every_render(self):
        with TemporaryDirectory() as directory, patch("cogs.uno_render.DEFAULT_ASSET_DIR", Path(directory)):
            colors = {"normal": (10, 20, 30), "meme": (40, 50, 60), "overwatch": (70, 80, 90)}
            for deck, color in colors.items():
                target = Path(directory, deck)
                target.mkdir()
                Image.new("RGB", (300, 450), color).save(target / "red_3.png")
            for deck, color in colors.items():
                with Image.open(render_card(card(), deck=deck)) as image:
                    self.assertEqual(image.getpixel((150, 225))[:3], color)
                with Image.open(render_hand([card()], deck=deck)) as image:
                    self.assertEqual(image.getpixel((75, 115))[:3], color)
            Path(directory, "meme", "red_3.png").unlink()
            with Image.open(render_card(card(), deck="meme")) as image:
                self.assertNotEqual(image.getpixel((150, 225))[:3], colors["normal"])

    def test_unknown_deck_cannot_select_arbitrary_asset_path(self):
        for deck in ("../normal", "custom", ""):
            with self.assertRaises(ValueError):
                render_card(card(), deck=deck)
            with self.assertRaises(ValueError):
                render_hand([card()], deck=deck)

    def test_labels_distinguish_actions_colors_and_wilds(self):
        self.assertEqual(card_label(card(value=3)), "🔴 3 · Vermelho")
        self.assertEqual(card_label(card(color="green", value="skip")), "🟢 Bloqueio · Verde")
        self.assertEqual(card_label(card(color=None, value="wild4")), "🃏 Coringa +4")

    def test_missing_and_corrupt_art_use_the_same_placeholder(self):
        with TemporaryDirectory() as directory:
            with render_card(card(), directory) as missing:
                expected = missing.getvalue()
            Path(directory, "red_3.png").write_bytes(b"partial PNG upload")
            with render_card(card(), directory) as corrupt:
                self.assertEqual(corrupt.getvalue(), expected)
                with Image.open(corrupt) as image:
                    self.assertEqual(image.size, (300, 450))

    def test_actual_art_is_used_and_replacement_is_loaded_without_restart(self):
        with TemporaryDirectory() as directory:
            path = Path(directory, "red_3.png")
            for color in ((12, 34, 56), (98, 76, 54)):
                Image.new("RGB", (100, 150), color).save(path)
                with render_card(card(), directory) as output, Image.open(output) as image:
                    self.assertEqual(image.getpixel((150, 225))[:3], color)

    def test_wild_uses_color_independent_asset(self):
        with TemporaryDirectory() as directory:
            Image.new("RGB", (30, 45), "#123456").save(Path(directory, "wild4.png"))
            with render_card(card(color=None, value="wild4"), directory) as output:
                with Image.open(output) as image:
                    self.assertEqual(image.getpixel((150, 225))[:3], (18, 52, 86))

    def test_selected_duplicate_uses_uid_and_is_raised(self):
        with TemporaryDirectory() as directory:
            cards = [card("one"), card("two")]
            with render_hand(cards, asset_dir=directory) as plain:
                with Image.open(plain) as image:
                    plain_image = image.copy()
            with render_hand(cards, selected_ids=("two",), asset_dir=directory) as selected:
                with Image.open(selected) as image:
                    self.assertEqual(image.getpixel((60, 18)), plain_image.getpixel((60, 18)))
                    self.assertNotEqual(image.getpixel((150, 18)), plain_image.getpixel((150, 18)))
                    self.assertEqual(image.getpixel((117, 40)), (255, 215, 106))

    def test_full_page_remains_discord_sized_and_keeps_last_card(self):
        with TemporaryDirectory() as directory:
            cards = [card(str(n), value=str(n % 10)) for n in range(25)]
            with render_hand(cards, asset_dir=directory) as output:
                with Image.open(output) as image:
                    self.assertEqual(image.size, (770, 940))
                    self.assertNotEqual(image.getpixel((365, 732)), (33, 28, 43))
                self.assertLess(len(output.getvalue()), 2_000_000)
            with self.assertRaises(ValueError):
                render_hand(cards + [card("26")], asset_dir=directory)

    def test_empty_hand_produces_a_valid_image(self):
        with render_hand([]) as output:
            self.assertEqual(output.tell(), 0)
            with Image.open(output) as image:
                self.assertEqual(image.size, (360, 120))


if __name__ == "__main__":
    unittest.main()
