# Copyright 2026 Maamoon Mara
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import _, models


class OrderkollDocument(models.Model):
    _inherit = "orderkoll.document"

    def _orderkoll_on_ready(self):
        """Core's hook: a document passed every check. With the inbox switch on, the
        quotation is created now and waits for tier validation instead of a click.
        Acts before the other subscribers, so they see the document already created."""
        if self.inbox_id.tier_validation_on_ready and not self.sale_order_id:
            order = self._create_quotation()
            order.request_validation()
            if order.review_ids:
                note = _(
                    "Quotation %(order)s created and sent for tier validation "
                    "(%(n)s review(s) requested).",
                    order=order.name,
                    n=len(order.review_ids),
                )
            else:
                note = _(
                    "Quotation %s created. No tier definition applies to it, so no review "
                    "was requested.",
                    order.name,
                )
            self._post_system_note(note)
        return super()._orderkoll_on_ready()
