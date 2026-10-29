# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Alert and heartbeat helpers: plain unittest, no network."""

import json
import unittest
import urllib.error

try:
    from ..services import alerts
except ImportError:  # plain unittest discovery rooted at tests/
    import importlib.util
    import pathlib

    _spec = importlib.util.spec_from_file_location(
        "alerts", pathlib.Path(__file__).parent.parent / "services" / "alerts.py"
    )
    alerts = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(alerts)


class _Resp:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    def __init__(self, status=200, fail=False):
        self.calls, self.status, self.fail = [], status, fail

    def __call__(self, request, timeout=None):
        self.calls.append(request)
        if self.fail:
            raise urllib.error.URLError("down")
        return _Resp(self.status)


class TestAlerts(unittest.TestCase):
    def test_telegram_posts_chat_and_text(self):
        opener = FakeOpener()
        self.assertTrue(alerts.send_telegram("123:abc", "42", "hello", opener))
        request = opener.calls[0]
        self.assertTrue(request.full_url.endswith("/bot123:abc/sendMessage"))
        body = json.loads(request.data)
        self.assertEqual(body["chat_id"], "42")
        self.assertEqual(body["text"], "hello")

    def test_telegram_without_settings_does_nothing(self):
        opener = FakeOpener()
        self.assertFalse(alerts.send_telegram("", "42", "hello", opener))
        self.assertFalse(opener.calls)

    def test_failures_are_swallowed(self):
        self.assertFalse(alerts.send_telegram("t", "c", "x", FakeOpener(fail=True)))
        self.assertFalse(alerts.send_webhook("https://n8n.example/h", {}, FakeOpener(fail=True)))
        self.assertFalse(alerts.ping("https://hc.example/x", FakeOpener(fail=True)))

    def test_webhook_needs_a_2xx(self):
        self.assertTrue(alerts.send_webhook("https://n8n.example/h", {"a": 1}, FakeOpener(204)))
        self.assertFalse(alerts.send_webhook("https://n8n.example/h", {"a": 1}, FakeOpener(500)))

    def test_ping_is_a_get_and_only_http(self):
        opener = FakeOpener()
        self.assertTrue(alerts.ping("https://hc.example/abc", opener))
        self.assertEqual(opener.calls[0].get_method(), "GET")
        self.assertFalse(alerts.ping("file:///etc/passwd", opener))
        self.assertEqual(len(opener.calls), 1)


if __name__ == "__main__":
    unittest.main()
