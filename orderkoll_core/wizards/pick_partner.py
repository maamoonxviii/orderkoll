# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import api, fields, models
from odoo.tools import email_normalize


class OrderkollPickPartner(models.TransientModel):
    _name = "orderkoll.pick_partner"
    _description = "Orderkoll: pick the customer of a document"

    document_id = fields.Many2one("orderkoll.document", required=True, ondelete="cascade")
    sender_email = fields.Char(related="document_id.sender_email")
    partner_id = fields.Many2one("res.partner", string="Customer", required=True)
    remember_sender = fields.Boolean(
        default=True,
        help="Store the sender address as a contact of this customer, so the next "
        "purchase order from it is recognised without a click.",
    )

    @api.onchange("partner_id")
    def _onchange_partner_id(self):
        if self.partner_id and self.partner_id != self.partner_id.commercial_partner_id:
            self.partner_id = self.partner_id.commercial_partner_id

    def action_pick(self):
        self.ensure_one()
        doc = self.document_id
        company = self.partner_id.commercial_partner_id
        doc.with_context(orderkoll_no_recheck=True).write(
            {"partner_id": company.id, "partner_resolution": "manual"}
        )
        doc._log_check("customer", f"picked by {self.env.user.name} → {company.display_name}")
        doc.activity_ids.filtered(lambda a: a.summary == "Pick customer").unlink()
        email = email_normalize(doc.sender_email or "", strict=True) or ""
        if self.remember_sender and email:
            # Order-desk users usually may not create contacts. Remembering the sender is
            # part of Orderkoll's job, so this one narrow contact (name + email under the
            # chosen company) is created by Orderkoll itself for its users.
            Partner = self.env["res.partner"].sudo()
            if not Partner.search_count([("email_normalized", "=", email)]):
                Partner.create(
                    {
                        "name": doc.sender_name or email,
                        "email": email,
                        "parent_id": company.id,
                        "type": "contact",
                        "company_id": company.company_id.id,
                    }
                )
                doc._log_check(
                    "customer", f"sender {email} remembered as a contact of {company.display_name}"
                )
        doc._after_partner_picked()
        return {"type": "ir.actions.act_window_close"}
