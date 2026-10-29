# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Outbound alerts and heartbeat pings. Plain Python: no Odoo imports.

Every call is best effort: a monitoring hiccup must never stop purchase orders
from being processed, so failures are logged and swallowed.
"""

import json
import logging
import urllib.error
import urllib.parse
import urllib.request

_logger = logging.getLogger(__name__)

TIMEOUT = 8


def _post_json(url, payload, opener=urllib.request.urlopen):
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with opener(request, timeout=TIMEOUT) as response:
        return response.status


def send_telegram(token, chat_id, text, opener=urllib.request.urlopen):
    """Send ``text`` to a Telegram chat through a bot. Returns True on success."""
    if not (token and chat_id and text):
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        return (
            _post_json(
                url,
                {"chat_id": chat_id, "text": text[:3500], "disable_web_page_preview": True},
                opener,
            )
            == 200
        )
    except (urllib.error.URLError, OSError, ValueError) as exc:
        # never log the URL: it contains the bot token
        _logger.warning("Orderkoll: Telegram alert failed: %s", type(exc).__name__)
        return False


def send_webhook(url, payload, opener=urllib.request.urlopen):
    """POST a JSON alert to a webhook (e.g. n8n). Returns True on a 2xx answer."""
    if not url or urllib.parse.urlparse(url).scheme not in ("http", "https"):
        return False
    try:
        return 200 <= _post_json(url, payload, opener) < 300
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _logger.warning("Orderkoll: alert webhook failed: %s", type(exc).__name__)
        return False


def ping(url, opener=urllib.request.urlopen):
    """Heartbeat (Healthchecks / Uptime Kuma push style): a GET that says 'still alive'."""
    if not url:
        return False
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    try:
        with opener(urllib.request.Request(url, method="GET"), timeout=TIMEOUT) as response:
            return 200 <= response.status < 300
    except (urllib.error.URLError, OSError, ValueError) as exc:
        _logger.warning("Orderkoll: heartbeat ping failed: %s", type(exc).__name__)
        return False
