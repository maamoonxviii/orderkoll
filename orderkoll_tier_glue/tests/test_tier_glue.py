# Copyright 2026 Maamoon Mara
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""A ready document becomes a quotation that waits for tier validation."""

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.orderkoll_core.services.imap import FetchedMail


@tagged("post_install", "-at_install")
class TestTierGlue(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("orderkoll.api_key", "")
        cls.inbox = cls.env["orderkoll.inbox"].create(
            {"name": "Tier inbox", "tier_validation_on_ready": True}
        )
        cls.partner = cls.env["res.partner"].create(
            {"name": "Tier T AB", "is_company": True, "email": "info@tier-t.example"}
        )
        cls.env["res.partner"].create(
            {"name": "Buyer", "email": "buyer@tier-t.example", "parent_id": cls.partner.id}
        )
        cls.product = cls.env["product.product"].create(
            {"name": "Tier item", "default_code": "TG-1", "sale_ok": True, "list_price": 10.0}
        )
        cls.reviewer = cls.env["res.users"].create(
            {
                "name": "Tier reviewer",
                "login": "tier-reviewer-t",
                "email": "reviewer@tier-t.example",
                "group_ids": [(6, 0, [cls.env.ref("sales_team.group_sale_salesman").id])],
            }
        )
        # only this test's rule applies (a database may already have its own)
        cls.env["tier.definition"].search([("model", "=", "sale.order")]).write({"active": False})
        cls.env["tier.definition"].create(
            {
                "model_id": cls.env["ir.model"]._get("sale.order").id,
                "review_type": "individual",
                "reviewer_id": cls.reviewer.id,
                "definition_domain": "[('orderkoll_document_id', '!=', False)]",
            }
        )

    def _ready_doc(self, uid, inbox=None):
        doc = (inbox or self.inbox)._ingest_mail(
            FetchedMail(
                uid=uid,
                message_id=f"<tier-{uid}@t>",
                sender_email="buyer@tier-t.example",
                sender_name="B",
                subject="PO",
                date=None,
                body_text="PO\n",
                body_html="",
                attachments=[],
            )
        )
        doc.raw_text = "PO"
        doc._resolve_partner()
        doc.write(
            {
                "po_number": f"PO-TG-{uid}",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "customer_code": "TG-1",
                            "description": "x",
                            "quantity": 1,
                            "unit_price": 10.0,
                            "line_total": 10.0,
                        },
                    )
                ],
            }
        )
        doc._after_lines_extracted()
        return doc

    def test_ready_creates_a_quotation_waiting_for_review(self):
        doc = self._ready_doc(1)
        self.assertEqual(doc.state, "created")
        order = doc.sale_order_id
        self.assertTrue(order)
        self.assertEqual(order.state, "draft")
        self.assertTrue(order.review_ids)
        self.assertEqual(order.review_ids.mapped("reviewer_ids"), self.reviewer)
        with self.assertRaises(ValidationError):
            order.action_confirm()  # not before the reviewer validated it
        self.assertIn("sent for tier validation", " ".join(doc.message_ids.mapped("body")))

    def test_the_reviewer_validates_then_the_quotation_can_be_confirmed(self):
        order = self._ready_doc(2).sale_order_id
        order.with_user(self.reviewer).validate_tier()
        self.env.invalidate_all()  # the review was written as another user
        self.assertEqual(order.validation_status, "validated")
        order.action_confirm()
        self.assertEqual(order.state, "sale")

    def test_without_the_switch_nothing_happens_on_ready(self):
        plain = self.env["orderkoll.inbox"].create({"name": "Plain inbox"})
        doc = self._ready_doc(3, inbox=plain)
        self.assertEqual(doc.state, "ready")
        self.assertFalse(doc.sale_order_id)
