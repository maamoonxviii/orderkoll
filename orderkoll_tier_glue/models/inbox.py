# Copyright 2026 Maamoon Mara
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import fields, models


class OrderkollInbox(models.Model):
    _inherit = "orderkoll.inbox"

    tier_validation_on_ready = fields.Boolean(
        string="Quotation + tier validation when ready",
        help="When a purchase order passes every check, create the draft quotation at once "
        "and request tier validation on it. It cannot be confirmed until the reviewers "
        "defined under Settings > Technical > Tier Validation have approved it.",
    )
