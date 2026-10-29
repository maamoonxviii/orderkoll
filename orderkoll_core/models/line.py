# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OrderkollLine(models.Model):
    _name = "orderkoll.line"
    _description = "Orderkoll Document Line"
    _order = "document_id, sequence, id"

    document_id = fields.Many2one(
        "orderkoll.document", required=True, ondelete="cascade", index=True
    )
    company_id = fields.Many2one("res.company", related="document_id.company_id", store=True)
    sequence = fields.Integer(default=10)
    customer_code = fields.Char(help="The code as written on the purchase order.")
    description = fields.Char()
    quantity = fields.Float(default=1.0)
    uom_name = fields.Char(string="Unit (as written)")
    uom_id = fields.Many2one("uom.uom", string="Unit")
    unit_price = fields.Float(digits="Product Price")
    line_total = fields.Float()

    product_id = fields.Many2one("product.product")
    match_method = fields.Selection(
        [
            ("sku_map", "Customer code memory"),
            ("default_code", "Internal reference"),
            ("barcode", "Barcode"),
            ("fuzzy", "Name similarity"),
            ("manual", "Picked manually"),
            ("none", "No match"),
        ],
        default="none",
    )
    match_score = fields.Float()

    pricelist_price = fields.Float(digits="Product Price")
    deviation_pct = fields.Float(string="Deviation (%)")
    price_ok = fields.Boolean(default=True)
    status = fields.Selection(
        [
            ("matched", "Matched"),
            ("needs_mapping", "Unknown product"),
            ("price_mismatch", "Price differs"),
            ("ok", "OK"),
        ],
        default="needs_mapping",
    )

    # Line fields whose manual edit re-runs the document's checks.
    _RECHECK_FIELDS = ("product_id", "quantity", "unit_price", "line_total")

    @api.model
    def _manual_product_vals(self, product_id):
        if product_id:
            return {"match_method": "manual", "match_score": 1.0, "status": "matched"}
        return {"match_method": "none", "match_score": 0.0, "status": "needs_mapping"}

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get("orderkoll_no_recheck"):
            for vals in vals_list:
                if "match_method" not in vals:
                    vals.update(self._manual_product_vals(vals.get("product_id")))
                if "line_total" not in vals and ("quantity" in vals or "unit_price" in vals):
                    qty, price = vals.get("quantity", 1.0), vals.get("unit_price", 0.0)
                    vals["line_total"] = round(qty * price, 2)
        lines = super().create(vals_list)
        if not self.env.context.get("orderkoll_no_recheck"):
            lines.document_id._recheck(_("line added"))
        return lines

    def write(self, vals):
        """A person's edit: a picked product counts as a manual match, a changed
        quantity or price updates the line total, and the document is re-checked."""
        if self.env.context.get("orderkoll_no_recheck") or not set(vals) & set(
            self._RECHECK_FIELDS
        ):
            return super().write(vals)
        vals = dict(vals)
        if "product_id" in vals:
            vals.update(self._manual_product_vals(vals["product_id"]))
        res = super().write(vals)
        if ("quantity" in vals or "unit_price" in vals) and "line_total" not in vals:
            for line in self:
                super(OrderkollLine, line).write(
                    {"line_total": round(line.quantity * line.unit_price, 2)}
                )
        self.document_id._recheck(_("line edited"))
        return res

    def unlink(self):
        documents = self.document_id
        res = super().unlink()
        if not self.env.context.get("orderkoll_no_recheck"):
            documents.exists()._recheck(_("line removed"))
        return res

    def _remember_code(self):
        """Store customer code → product in the customer's code memory."""
        self.ensure_one()
        doc = self.document_id
        code = (self.customer_code or "").strip().upper()
        if not (code and doc.partner_id and self.product_id):
            return False
        partner = doc.partner_id.commercial_partner_id
        SkuMap = self.env["orderkoll.sku_map"]
        row = SkuMap.search(
            [("partner_id", "=", partner.id), ("customer_code", "=", code)], limit=1
        )
        if row:
            row.write({"product_id": self.product_id.id, "confirmed_by": self.env.user.id})
        else:
            SkuMap.create(
                {"partner_id": partner.id, "customer_code": code, "product_id": self.product_id.id}
            )
        return True

    def action_open_map_sku(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Map product"),
            "res_model": "orderkoll.map_sku",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_line_id": self.id,
                "default_product_id": self.product_id.id,
            },
        }

    def action_remember_mapping(self):
        """Store customer code → product in the customer's code memory and mark the
        line matched. Needs the product set on the line first."""
        for line in self:
            doc = line.document_id
            if not line.product_id:
                raise UserError(_("Pick a product on the line first."))
            if not doc.partner_id:
                raise UserError(_("Pick the customer first; code memory is per customer."))
            if line._remember_code():
                doc._log_check(
                    "products",
                    f"{line.customer_code.strip().upper()} mapped to "
                    f"{line.product_id.display_name} by {self.env.user.name}",
                )
            line.with_context(orderkoll_no_recheck=True).write(
                {"match_method": "manual", "match_score": 1.0, "status": "matched"}
            )
            doc._recheck(_("mapping remembered"))
        return True
