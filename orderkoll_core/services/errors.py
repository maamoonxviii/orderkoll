# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Exceptions shared between core and the extraction engine (no Odoo imports)."""


class TransientProcessingError(Exception):
    """The step failed for a reason that may pass (rate limit, timeout, provider down).
    The document stays `new` and is retried by the cron a few times before it errors."""
