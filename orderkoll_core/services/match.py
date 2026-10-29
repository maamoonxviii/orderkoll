# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Pure helpers for customer and product matching (no Odoo imports)."""

from __future__ import annotations

import re

DEFAULT_IGNORED_DOMAINS = "gmail.com,outlook.com,hotmail.com,yahoo.com,icloud.com,live.com"


def domain_of(email: str | None) -> str | None:
    """'Anna <ANNA@Nordic.se>' → 'nordic.se'; None when there is no @."""
    if not email or "@" not in email:
        return None
    address = email.strip().rsplit("<", 1)[-1].rstrip("> ").strip()
    return address.rsplit("@", 1)[-1].lower() or None


def parse_ignored_domains(setting: str | None) -> set[str]:
    """Comma/space/newline separated list → lower-cased set (default list when empty)."""
    raw = setting if setting and setting.strip() else DEFAULT_IGNORED_DOMAINS
    return {
        d.strip().lower().lstrip("@")
        for d in raw.replace("\n", ",").replace(" ", ",").split(",")
        if d.strip()
    }


def is_ignored_domain(domain: str | None, ignored: set[str]) -> bool:
    """gmail.com and its sub-domains (mail.gmail.com) never identify a customer."""
    if not domain:
        return True
    domain = domain.lower()
    return any(domain == d or domain.endswith("." + d) for d in ignored)


_PLAIN_DOMAIN = re.compile(
    r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$"
)


def is_plain_domain(domain: str | None) -> bool:
    """Letters, digits, dots and dashes only: safe to put into a LIKE pattern."""
    return bool(domain) and bool(_PLAIN_DOMAIN.match(domain))


def website_domain(website: str | None) -> str | None:
    """'https://www.Nordic.se/shop' → 'nordic.se' (www. dropped)."""
    if not website:
        return None
    host = website.strip().lower()
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    host = host.split("/", 1)[0].split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


# ---------------------------------------------------------------- products
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_code(code: str | None) -> str | None:
    """Trimmed, single-spaced, upper-cased — the form stored in the code memory."""
    if not code:
        return None
    return " ".join(code.split()).upper() or None


def compact_code(code: str | None) -> str | None:
    """Letters and digits only, upper-cased: 'MT 1003' and 'mt-1003.' both → 'MT1003'."""
    if not code:
        return None
    return re.sub(r"[^A-Z0-9]", "", code.upper()) or None


_DIGIT_LETTER = re.compile(r"(?<=\d)(?=[a-z])|(?<=[a-z])(?=\d)")


def _name_tokens(text: str) -> list[str]:
    """lower-cased words; '32mm' becomes '32 mm' so sizes compare as numbers."""
    text = _DIGIT_LETTER.sub(" ", (text or "").lower())
    return [t for t in _NON_ALNUM.sub(" ", text).split() if t]


def _numbers(tokens: list[str]) -> set[str]:
    return {t.lstrip("0") or "0" for t in tokens if t.isdigit()}


MAX_NAME_CHARS = 200  # a product name never needs more; bounds the matching cost


def name_similarity(a: str, b: str) -> float:
    """0..1: the better of a character-level ratio and a token-sorted ratio, after
    lower-casing and dropping punctuation (so '32mm' and '32 mm' are close).
    Inputs are cut to MAX_NAME_CHARS and a cheap upper bound is checked first."""
    from difflib import SequenceMatcher

    ta, tb = _name_tokens((a or "")[:MAX_NAME_CHARS]), _name_tokens((b or "")[:MAX_NAME_CHARS])
    if not ta or not tb:
        return 0.0
    joined_a, joined_b = " ".join(ta), " ".join(tb)
    matcher = SequenceMatcher(None, joined_a, joined_b)
    if matcher.quick_ratio() < 0.5:  # cannot reach any useful score; skip the expensive part
        return 0.0
    compact_a, compact_b = "".join(ta), "".join(tb)
    sorted_a, sorted_b = " ".join(sorted(ta)), " ".join(sorted(tb))
    score = max(
        matcher.ratio(),
        SequenceMatcher(None, compact_a, compact_b).ratio(),
        SequenceMatcher(None, sorted_a, sorted_b).ratio(),
    )
    # A size, length or gauge that differs is a different product, however close the
    # words are: "valve 50 mm" must never pass as "valve 40 mm".
    if _numbers(ta) != _numbers(tb):
        score = min(score, 0.5)
    return score


def best_name_match(description: str, catalogue, threshold: float):
    """(product_id, score) of the best name in ``catalogue`` ([(id, name), …]) when its
    score reaches ``threshold``; (None, best_score) otherwise."""
    best_id, best_score = None, 0.0
    for product_id, name in catalogue:
        score = name_similarity(description, name)
        if score > best_score:
            best_id, best_score = product_id, score
    if best_score >= threshold:
        return best_id, best_score
    return None, best_score
