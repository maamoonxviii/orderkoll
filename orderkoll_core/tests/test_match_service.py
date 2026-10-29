# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import unittest

try:
    from ._services import match
except ImportError:  # unittest discovery rooted at tests/ (no Odoo)
    from _services import match


class TestDomains(unittest.TestCase):
    def test_domain_of(self):
        self.assertEqual(match.domain_of("Anna <ANNA@Nordic.se>"), "nordic.se")
        self.assertEqual(match.domain_of("inkop@nordicfasteners.se"), "nordicfasteners.se")
        self.assertIsNone(match.domain_of("not-an-address"))
        self.assertIsNone(match.domain_of(None))

    def test_ignored_domains_parse_and_match(self):
        ignored = match.parse_ignored_domains(None)
        self.assertIn("gmail.com", ignored)
        self.assertTrue(match.is_ignored_domain("gmail.com", ignored))
        self.assertTrue(match.is_ignored_domain("mail.gmail.com", ignored))
        self.assertFalse(match.is_ignored_domain("nordicfasteners.se", ignored))
        self.assertTrue(match.is_ignored_domain(None, ignored))
        custom = match.parse_ignored_domains("Example.com, @other.org\nthird.net")
        self.assertEqual(custom, {"example.com", "other.org", "third.net"})

    def test_website_domain(self):
        self.assertEqual(
            match.website_domain("https://www.NordicFasteners.se/shop"), "nordicfasteners.se"
        )
        self.assertEqual(match.website_domain("harborsupply.com"), "harborsupply.com")
        self.assertIsNone(match.website_domain(""))

    def test_plain_domain(self):
        self.assertTrue(match.is_plain_domain("nordic-fasteners.example"))
        self.assertFalse(match.is_plain_domain("nordic%.example"))
        self.assertFalse(match.is_plain_domain("nordic_fasteners.example"))
        self.assertFalse(match.is_plain_domain(None))


class TestCodesAndNames(unittest.TestCase):
    def test_normalise_code_variants(self):
        self.assertEqual(match.normalize_code("  nf-42611 "), "NF-42611")
        self.assertEqual(match.compact_code("NF-42611"), "NF42611")
        self.assertEqual(match.compact_code("ok 1001."), "OK1001")
        self.assertIsNone(match.normalize_code("   "))

    def test_name_similarity(self):
        self.assertGreaterEqual(
            match.name_similarity("Ball valve 32mm grey", "Ball valve 32 mm grey"), 0.9
        )
        self.assertGreaterEqual(
            match.name_similarity("grey ball valve 32 mm", "Ball valve 32 mm grey"), 0.88
        )
        self.assertLess(
            match.name_similarity("Flux capacitor 1.21 GW", "Ball valve 32 mm grey"), 0.5
        )
        self.assertEqual(match.name_similarity("", "x"), 0.0)

    def test_different_numbers_never_match(self):
        self.assertLess(
            match.name_similarity("Ball valve 50 mm grey", "Ball valve 40 mm grey"), 0.88
        )
        self.assertLess(match.name_similarity("Cable 3G1.5 50 m", "Cable 3G2.5 50 m"), 0.88)
        self.assertGreaterEqual(
            match.name_similarity("Hex bolt M8x40 zinc", "Hex bolt M8 x 40 zinc"), 0.9
        )
        self.assertGreaterEqual(
            match.name_similarity("Ball valve 032 mm grey", "Ball valve 32 mm grey"), 0.9
        )

    def test_best_name_match_respects_threshold(self):
        catalogue = [
            (1, "Ball valve 32 mm grey"),
            (2, "Ball valve 40 mm grey"),
            (3, "Hex bolt M8x40 zinc"),
        ]
        pid, score = match.best_name_match("ball valve 32mm grey", catalogue, 0.88)
        self.assertEqual(pid, 1)
        self.assertGreaterEqual(score, 0.88)
        pid, score = match.best_name_match("Hex nut M8", catalogue, 0.88)
        self.assertIsNone(pid)
        self.assertLess(score, 0.88)

    def test_hostile_description_is_bounded(self):
        import time

        catalogue = [(i, f"Product number {i} grey") for i in range(2000)]
        started = time.monotonic()
        pid, _score = match.best_name_match(
            "x" * 100_000 + " Product number 7 grey", catalogue, 0.88
        )
        self.assertLess(time.monotonic() - started, 5.0)
        self.assertIsNone(pid)  # the junk prefix dominates the capped text; no false match
