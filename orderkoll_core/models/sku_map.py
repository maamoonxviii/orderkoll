# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models


class OrderkollSkuMap(models.Model):
    _name = "orderkoll.sku_map"
    _description = "Orderkoll Customer Code Memory"
    _order = "partner_id, customer_code"
    _rec_name = "customer_code"

    partner_id = fields.Many2one("res.partner", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    customer_code = fields.Char(required=True, index=True, help="Stored upper-cased.")
    product_id = fields.Many2one("product.product", required=True, ondelete="cascade")
    confirmed_by = fields.Many2one("res.users", default=lambda self: self.env.user)
    confirmed_on = fields.Datetime(default=fields.Datetime.now)
    hit_count = fields.Integer(default=0)

    _partner_code_unique = models.Constraint(
        "unique(partner_id, customer_code)",
        "This customer code is already mapped.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("customer_code"):
                vals["customer_code"] = vals["customer_code"].strip().upper()
        return super().create(vals_list)

    def write(self, vals):
        if vals.get("customer_code"):
            vals["customer_code"] = vals["customer_code"].strip().upper()
        return super().write(vals)
