# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import _, api, fields, models


class OrderkollMapSku(models.TransientModel):
    _name = "orderkoll.map_sku"
    _description = "Orderkoll: pick the product a purchase-order line means"

    line_id = fields.Many2one("orderkoll.line", required=True, ondelete="cascade")
    document_id = fields.Many2one(related="line_id.document_id")
    partner_id = fields.Many2one(related="line_id.document_id.partner_id", string="Customer")
    customer_code = fields.Char(related="line_id.customer_code", string="Customer's code")
    description = fields.Char(related="line_id.description")
    quantity = fields.Float(related="line_id.quantity")
    unit_price = fields.Float(related="line_id.unit_price", string="Price on the PO")
    product_id = fields.Many2one(
        "product.product", string="Product", required=True, domain=[("sale_ok", "=", True)]
    )
    remember = fields.Boolean(
        string="Remember for this customer",
        default=True,
        help="Next time this customer writes this code, the product is found automatically.",
    )
    can_remember = fields.Boolean(compute="_compute_can_remember")

    @api.depends("partner_id", "customer_code")
    def _compute_can_remember(self):
        for wizard in self:
            wizard.can_remember = bool(wizard.partner_id and (wizard.customer_code or "").strip())

    def action_map(self):
        self.ensure_one()
        line = self.line_id
        doc = line.document_id
        line.with_context(orderkoll_no_recheck=True).write(
            {
                "product_id": self.product_id.id,
                "match_method": "manual",
                "match_score": 1.0,
                "status": "matched",
            }
        )
        label = line.customer_code or line.description or "?"
        if self.remember and self.can_remember and line._remember_code():
            note = (
                f"{label} mapped to {self.product_id.display_name} and remembered for "
                f"{doc.partner_id.commercial_partner_id.display_name} by {self.env.user.name}"
            )
        else:
            note = (
                f"{label} mapped to {self.product_id.display_name} for this document "
                f"by {self.env.user.name}"
            )
        doc.with_context(orderkoll_no_recheck=True)._log_check("products", note)
        doc._recheck(_("product mapped"))
        return {"type": "ir.actions.act_window_close"}
