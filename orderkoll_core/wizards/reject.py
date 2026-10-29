# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class OrderkollReject(models.TransientModel):
    _name = "orderkoll.reject"
    _description = "Orderkoll: reject a document with a reason"

    document_ids = fields.Many2many("orderkoll.document", required=True)
    reason = fields.Text(required=True)

    def action_reject(self):
        self.ensure_one()
        self.document_ids._reject(self.reason)
        return {"type": "ir.actions.act_window_close"}
