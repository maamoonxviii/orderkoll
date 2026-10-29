# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Ready document → draft quotation. Written here from scratch (no OCA code).

Nothing is confirmed: the quotation stays a draft for a person to send or confirm.
"""

from markupsafe import Markup

from odoo import _, fields, models
from odoo.exceptions import UserError


class OrderkollDocument(models.Model):
    _inherit = "orderkoll.document"

    def action_create_quotation(self):
        orders = self.env["sale.order"]
        for doc in self:
            if doc.state != "ready":
                raise UserError(
                    _(
                        "%(doc)s cannot become a quotation yet: it is '%(state)s'. "
                        "Fix what the To-do box lists first.",
                        doc=doc.name,
                        state=dict(doc._fields["state"].selection).get(doc.state),
                    )
                )
            orders |= doc._create_quotation()
        if len(orders) == 1:
            return {
                "type": "ir.actions.act_window",
                "res_model": "sale.order",
                "res_id": orders.id,
                "view_mode": "form",
            }
        return True

    def _create_quotation(self):
        """Draft sale.order with the checked lines, the PO number as customer reference,
        the original file attached and the checks log in its chatter."""
        self.ensure_one()
        order = self.env["sale.order"].create(self._quotation_values())
        self._copy_po_file_to(order)
        self.with_context(orderkoll_no_recheck=True).write(
            {"state": "created", "sale_order_id": order.id}
        )
        order.message_post(
            body=self._quotation_note(),
            message_type="notification",
            author_id=self.env.ref("base.partner_root").id,
        )
        self._post_system_note(
            _(
                "Quotation %(order)s created by %(user)s.",
                order=order.name,
                user=self.env.user.name,
            )
        )
        return order

    def _quotation_values(self):
        partner = self.partner_id.commercial_partner_id
        pricelist = partner.property_product_pricelist
        values = {
            "partner_id": partner.id,
            "client_order_ref": self.po_number or False,
            "origin": _("Orderkoll %s", self.name),
            "company_id": self.company_id.id,
            "orderkoll_document_id": self.id,
        }
        if pricelist:
            values["pricelist_id"] = pricelist.id
        if self.requested_date:
            values["commitment_date"] = fields.Datetime.to_datetime(self.requested_date)
        values["order_line"] = [
            (0, 0, self._quotation_line_values(line, pricelist)) for line in self.line_ids
        ]
        return values

    def _quotation_line_values(self, line, pricelist):
        values = {"product_id": line.product_id.id, "product_uom_qty": line.quantity}
        if line.uom_id:
            values["product_uom"] = line.uom_id.id
        if self.inbox_id.price_source == "po":
            values["price_unit"] = self._price_in_order_currency(line.unit_price, pricelist)
        return values

    def _price_in_order_currency(self, price, pricelist):
        order_currency = pricelist.currency_id or self.company_id.currency_id
        po_currency = self.currency_id or order_currency
        if po_currency == order_currency:
            return price
        date = self.po_date or fields.Date.today()
        return po_currency._convert(price, order_currency, self.company_id, date)

    def _copy_po_file_to(self, order):
        if self.attachment_id:
            self.attachment_id.copy({"res_model": "sale.order", "res_id": order.id})

    def _quotation_note(self):
        items = Markup("").join(Markup("<li>%s</li>") % line for line in self._check_lines())
        source = (
            self.inbox_id.price_source == "po"
            and _("the purchase order")
            or _("the customer's pricelist")
        )
        return Markup("<p><b>%s</b></p><p>%s</p><ul>%s</ul>") % (
            _("Created by Orderkoll from document %s", self.name),
            _("Unit prices from %(origin)s. Checks that ran:", origin=source),
            items,
        )
