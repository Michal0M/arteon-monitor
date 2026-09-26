"""Testy pre notify.py - mock Discord API, žiadne skutočné HTTP volania."""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import notify


def make_listing(**overrides):
    base = {
        "title": "VW Arteon R-Line 2.0 TSI",
        "description_raw": "Pekné auto, 2.0 TSI, nehavarované.",
        "url": "https://example.com/1",
        "source": "bazos_sk",
        "current_price": 24000,
        "currency": "EUR",
        "price_eur_est": 24000,
        "year_built": 2022,
        "km": 45000,
        "color_guess": "strieborn",
        "is_secondary_color": False,
        "main_photo_url": "https://example.com/photo.jpg",
    }
    base.update(overrides)
    return base


class KindForTests(unittest.TestCase):
    def test_new(self):
        self.assertEqual(notify.kind_for("new", None, 24000), "new")

    def test_reappeared_has_priority(self):
        self.assertEqual(notify.kind_for("reappeared", 20000, 24000), "reappeared")

    def test_price_drop(self):
        self.assertEqual(notify.kind_for("price_changed", 26000, 24000), "price_drop")

    def test_price_up(self):
        self.assertEqual(notify.kind_for("price_changed", 22000, 24000), "price_up")

    def test_unchanged_is_none(self):
        self.assertIsNone(notify.kind_for("unchanged", 24000, 24000))

    def test_skipped_criteria_is_none(self):
        self.assertIsNone(notify.kind_for("skipped_criteria", None, None))


class GuessEngineTests(unittest.TestCase):
    def test_finds_2_0_tsi(self):
        self.assertEqual(notify.guess_engine(make_listing()), "2.0 TSI")

    def test_missing_engine_returns_none(self):
        listing = make_listing(title="VW Arteon R-Line", description_raw="bez údajov o motore")
        self.assertIsNone(notify.guess_engine(listing))


class BuildEmbedTests(unittest.TestCase):
    def test_new_listing_embed(self):
        item = {"kind": "new", "listing": make_listing(), "old_price": None}
        embed = notify.build_embed(item)
        self.assertIn("24 000 EUR", embed["description"])
        self.assertIn("2022", embed["description"])
        self.assertIn("45 000 km", embed["description"])
        self.assertEqual(embed["thumbnail"]["url"], "https://example.com/photo.jpg")

    def test_price_drop_shows_both_prices(self):
        item = {"kind": "price_drop", "listing": make_listing(current_price=23000, price_eur_est=23000),
                "old_price": 24000}
        embed = notify.build_embed(item)
        self.assertIn("24 000", embed["description"])
        self.assertIn("23 000", embed["description"])

    def test_secondary_color_badge(self):
        item = {"kind": "new", "listing": make_listing(color_guess="cerven", is_secondary_color=True),
                "old_price": None}
        embed = notify.build_embed(item)
        self.assertIn("červená/modrá", embed["description"])

    def test_no_photo_omits_thumbnail(self):
        item = {"kind": "new", "listing": make_listing(main_photo_url=None), "old_price": None}
        embed = notify.build_embed(item)
        self.assertNotIn("thumbnail", embed)


class SendNotificationsTests(unittest.TestCase):
    def test_no_webhook_skips_without_error(self):
        sent = notify.send_notifications([{"kind": "new", "listing": make_listing(), "old_price": None}],
                                          webhook=None)
        self.assertEqual(sent, 0)

    def test_empty_items_does_not_call_requests(self):
        with patch("notify.requests.post") as mock_post:
            notify.send_notifications([], webhook="https://discord.example/webhook")
            mock_post.assert_not_called()

    @patch("notify.time.sleep", return_value=None)  # netreba naozaj čakať v testoch
    @patch("notify.requests.post")
    def test_sends_and_reports_success(self, mock_post, _mock_sleep):
        mock_post.return_value = MagicMock(status_code=204)
        items = [{"kind": "new", "listing": make_listing(), "old_price": None}]
        sent = notify.send_notifications(items, webhook="https://discord.example/webhook")
        self.assertEqual(sent, 1)
        mock_post.assert_called_once()

    @patch("notify.time.sleep", return_value=None)
    @patch("notify.requests.post")
    def test_retries_on_429(self, mock_post, _mock_sleep):
        rate_limited = MagicMock(status_code=429)
        rate_limited.json.return_value = {"retry_after": 0.1}
        ok = MagicMock(status_code=204)
        mock_post.side_effect = [rate_limited, ok]
        items = [{"kind": "new", "listing": make_listing(), "old_price": None}]
        sent = notify.send_notifications(items, webhook="https://discord.example/webhook")
        self.assertEqual(sent, 1)
        self.assertEqual(mock_post.call_count, 2)


if __name__ == "__main__":
    unittest.main()
