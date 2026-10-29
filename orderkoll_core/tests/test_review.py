# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Review screen actions: what a person does to clear a stopped document."""

from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..services.imap import FetchedMail


@tagged("post_install", "-at_install")
class TestReview(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("orderkoll.api_key", "")
        cls.inbox = cls.env["orderkoll.inbox"].create({"name": "Review inbox"})
        cls.partner = cls.env["res.partner"].create(
            {"name": "Review T AB", "is_company": True, "email": "info@review-t.example"}
        )
        cls.env["res.partner"].create(
            {"name": "Buyer", "email": "buyer@review-t.example", "parent_id": cls.partner.id}
        )
        Product = cls.env["product.product"]
        cls.valve = Product.create(
            {
                "name": "Ball valve 32 mm",
                "default_code": "RV-1001",
                "sale_ok": True,
                "list_price": 2.0,
            }
        )
        cls.bolt = Product.create(
            {"name": "Hex bolt M8", "default_code": "RV-1002", "sale_ok": True, "list_price": 2.0}
        )

    def _doc(self, uid, lines, sender="buyer@review-t.example"):
        doc = self.inbox._ingest_mail(
            FetchedMail(
                uid=uid,
                message_id=f"<review-{uid}@t>",
                sender_email=sender,
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
                "line_ids": [
                    (0, 0, dict({"quantity": 1.0, "unit_price": 2.0, "line_total": 2.0}, **ln))
                    for ln in lines
                ]
            }
        )
        doc._after_lines_extracted()
        return doc

    def _map(self, line, product, remember=True):
        wizard = (
            self.env["orderkoll.map_sku"]
            .with_context(default_line_id=line.id)
            .create({"product_id": product.id, "remember": remember})
        )
        wizard.action_map()

    def test_the_po_file_is_the_main_attachment(self):
        from ..services.imap import Attachment
        from ._services import DATA

        doc = self.inbox._ingest_mail(
            FetchedMail(
                uid=99,
                message_id="<review-99@t>",
                sender_email="buyer@review-t.example",
                sender_name="B",
                subject="PO",
                date=None,
                body_text="",
                body_html="",
                attachments=[
                    Attachment("po.pdf", (DATA / "pdf-L01-1.pdf").read_bytes(), "application/pdf")
                ],
            )
        )
        self.assertTrue(doc.attachment_id)
        self.assertEqual(doc.message_main_attachment_id, doc.attachment_id)

    def test_map_wizard_maps_remembers_and_makes_ready(self):
        doc = self._doc(1, [{"customer_code": "XX-9", "description": "bolt"}])
        self.assertEqual(doc.state, "needs_review")
        self.assertIn("Map 1 line(s)", doc.review_todo)
        self._map(doc.line_ids, self.bolt)
        self.assertEqual(doc.line_ids.product_id, self.bolt)
        self.assertEqual(doc.line_ids.match_method, "manual")
        self.assertEqual(doc.state, "ready")
        self.assertFalse(doc.review_todo)
        row = self.env["orderkoll.sku_map"].search(
            [("partner_id", "=", self.partner.id), ("customer_code", "=", "XX-9")]
        )
        self.assertEqual(row.product_id, self.bolt)
        self.assertIn("remembered for Review T AB", doc.checks_log)

    def test_map_without_remember_stores_nothing(self):
        doc = self._doc(2, [{"customer_code": "XX-8", "description": "bolt"}])
        self._map(doc.line_ids, self.bolt, remember=False)
        self.assertEqual(doc.state, "ready")
        self.assertFalse(self.env["orderkoll.sku_map"].search([("customer_code", "=", "XX-8")]))
        self.assertIn("for this document", doc.checks_log)

    def test_editing_the_product_inline_counts_as_a_manual_match(self):
        doc = self._doc(3, [{"customer_code": "XX-7", "description": "bolt"}])
        doc.write({"line_ids": [(1, doc.line_ids.id, {"product_id": self.bolt.id})]})
        self.assertEqual(doc.line_ids.match_method, "manual")
        self.assertEqual(doc.state, "ready")

    def test_quantity_edit_updates_the_line_total(self):
        doc = self._doc(4, [{"customer_code": "RV-1001", "description": "valve"}])
        doc.line_ids.quantity = 3
        self.assertEqual(doc.line_ids.line_total, 6.0)

    def test_manual_pick_survives_picking_the_customer(self):
        doc = self._doc(5, [{"customer_code": "XX-6", "description": "bolt"}], "a@nobody-t.example")
        self.assertFalse(doc.partner_id)
        self.assertIn("Pick the customer", doc.review_todo)
        self._map(doc.line_ids, self.bolt)  # no customer yet: cannot be remembered
        self.assertEqual(doc.state, "needs_review")
        self.env["orderkoll.pick_partner"].create(
            {"document_id": doc.id, "partner_id": self.partner.id, "remember_sender": False}
        ).action_pick()
        self.assertEqual(doc.partner_id, self.partner)
        self.assertEqual(doc.line_ids.product_id, self.bolt)
        self.assertEqual(doc.state, "ready")

    def test_reject_needs_a_reason_and_is_recorded(self):
        doc = self._doc(6, [{"customer_code": "XX-5", "description": "bolt"}])
        with self.assertRaises(UserError):
            doc._reject("   ")
        self.env["orderkoll.reject"].create(
            {"document_ids": [(6, 0, doc.ids)], "reason": "Ordered by phone already"}
        ).action_reject()
        self.assertEqual(doc.state, "rejected")
        self.assertEqual(doc.reject_reason, "Ordered by phone already")
        self.assertTrue(
            doc.message_ids.filtered(lambda m: "Ordered by phone already" in (m.body or ""))
        )

    def test_a_created_document_cannot_be_rejected_or_rechecked(self):
        doc = self._doc(7, [{"customer_code": "RV-1001", "description": "valve"}])
        doc.with_context(orderkoll_no_recheck=True).state = "created"
        with self.assertRaises(UserError):
            doc._reject("too late")
        doc.line_ids.quantity = 5  # an edit after creation never changes the state
        self.assertEqual(doc.state, "created")

    def test_marking_a_scan_checked_clears_the_ocr_stop(self):
        doc = self._doc(8, [{"customer_code": "RV-1001", "description": "valve"}])
        doc.with_context(orderkoll_no_recheck=True).extraction_method = "ocr"
        doc.action_recheck()
        self.assertEqual(doc.state, "needs_review")
        self.assertIn("scanned PDF", doc.review_todo)
        doc.action_mark_scan_checked()
        self.assertEqual(doc.state, "ready")
        self.assertIn("compared with the file by a person", doc.checks_log)

    def test_a_scan_without_ocr_says_so(self):
        from odoo.addons.orderkoll_core.services import extract

        doc = self._doc(10, [])
        doc.with_context(orderkoll_no_recheck=True).write(
            {"source_type": "pdf", "raw_text": False, "state": "needs_review"}
        )
        with mock.patch.object(extract, "ocr_available", return_value=False):
            doc.invalidate_recordset(["review_todo"])
            self.assertIn("OCR", doc.review_todo)

    def test_each_recheck_posts_one_summary_of_its_own_checks(self):
        doc = self._doc(9, [{"customer_code": "XX-4", "description": "bolt"}])
        before = len(doc.message_ids)
        self._map(doc.line_ids, self.bolt)
        new = doc.message_ids[: len(doc.message_ids) - before]
        summaries = new.filtered(lambda m: "Re-check" in (m.body or ""))
        self.assertEqual(len(summaries), 1)
        self.assertIn("product mapped", summaries.body)
        self.assertNotIn("text extraction", summaries.body)

    def test_an_order_desk_user_without_contact_rights_can_pick_and_remember(self):
        desk = self.env["res.users"].create(
            {
                "name": "Desk T",
                "login": "desk-review-t",
                "groups_id": [(6, 0, [self.env.ref("orderkoll_core.group_orderkoll_user").id])],
            }
        )
        self.assertFalse(desk.has_group("base.group_partner_manager"))
        doc = self._doc(
            10, [{"customer_code": "RV-1001", "description": "valve"}], "x@new-t.example"
        )
        self.env["orderkoll.pick_partner"].with_user(desk).create(
            {"document_id": doc.id, "partner_id": self.partner.id}
        ).action_pick()
        contact = self.env["res.partner"].search([("email_normalized", "=", "x@new-t.example")])
        self.assertEqual(contact.parent_id, self.partner)
        self.assertEqual(doc.state, "ready")
