# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Ready document → draft quotation; errors → task (+ alert); the ready hook."""

from unittest import mock

from odoo.exceptions import UserError
from odoo.tests import TransactionCase, tagged

from ..services.imap import Attachment, FetchedMail
from ._services import DATA


@tagged("post_install", "-at_install")
class TestQuotation(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_str("orderkoll.api_key", "")
        cls.inbox = cls.env["orderkoll.inbox"].create({"name": "Quotation inbox"})
        cls.partner = cls.env["res.partner"].create(
            {"name": "Quote T AB", "is_company": True, "email": "info@quote-t.example"}
        )
        cls.env["res.partner"].create(
            {"name": "Buyer", "email": "buyer@quote-t.example", "parent_id": cls.partner.id}
        )
        Product = cls.env["product.product"]
        cls.valve = Product.create(
            {"name": "Quote valve", "default_code": "QT-1", "sale_ok": True, "list_price": 10.0}
        )
        cls.bolt = Product.create(
            {"name": "Quote bolt", "default_code": "QT-2", "sale_ok": True, "list_price": 2.0}
        )

    def _doc(self, uid, lines, po="PO-QT-1", with_file=False):
        attachments = (
            [Attachment("po.pdf", (DATA / "pdf-L01-1.pdf").read_bytes(), "application/pdf")]
            if with_file
            else []
        )
        doc = self.inbox._ingest_mail(
            FetchedMail(
                uid=uid,
                message_id=f"<quote-{uid}@t>",
                sender_email="buyer@quote-t.example",
                sender_name="B",
                subject="PO",
                date=None,
                body_text="PO\n",
                body_html="",
                attachments=attachments,
            )
        )
        doc.raw_text = "PO"
        doc._resolve_partner()
        doc.write(
            {
                "po_number": po,
                "requested_date": "2026-11-20",
                "line_ids": [
                    (
                        0,
                        0,
                        {
                            "customer_code": code,
                            "description": code,
                            "quantity": qty,
                            "unit_price": price,
                            "line_total": qty * price,
                        },
                    )
                    for code, qty, price in lines
                ],
            }
        )
        doc._after_lines_extracted()
        return doc

    def test_a_ready_document_becomes_a_draft_quotation(self):
        doc = self._doc(1, [("QT-1", 3, 10.0), ("QT-2", 5, 2.0)], with_file=True)
        self.assertEqual(doc.state, "ready")
        doc.action_create_quotation()
        order = doc.sale_order_id
        self.assertTrue(order)
        self.assertEqual(order.state, "draft")  # never confirmed automatically
        self.assertEqual(order.partner_id, self.partner)
        self.assertEqual(order.client_order_ref, "PO-QT-1")
        self.assertEqual(order.orderkoll_document_id, doc)
        self.assertEqual(str(order.commitment_date.date()), "2026-11-20")
        self.assertEqual(
            [(ln.product_id, ln.product_uom_qty) for ln in order.order_line],
            [(self.valve, 3.0), (self.bolt, 5.0)],
        )
        self.assertEqual(doc.state, "created")
        copies = self.env["ir.attachment"].search(
            [("res_model", "=", "sale.order"), ("res_id", "=", order.id)]
        )
        self.assertEqual(copies.mapped("name"), ["po.pdf"])
        note = order.message_ids.filtered(lambda m: "Created by Orderkoll" in (m.body or ""))
        self.assertTrue(note)
        self.assertIn("[OK] products", note.body)

    def test_price_source_pricelist_or_po(self):
        doc = self._doc(2, [("QT-1", 1, 9.9)], po="PO-QT-2")
        self.inbox.price_source = "po"
        doc.action_create_quotation()
        self.assertEqual(doc.sale_order_id.order_line.price_unit, 9.9)
        self.inbox.price_source = "pricelist"
        doc2 = self._doc(3, [("QT-1", 1, 9.9)], po="PO-QT-3")
        doc2.action_create_quotation()
        self.assertEqual(doc2.sale_order_id.order_line.price_unit, 10.0)

    def test_a_unit_on_the_line_reaches_the_quotation(self):
        doc = self._doc(9, [("QT-1", 2, 10.0)], po="PO-QT-9")
        doc.line_ids.uom_id = self.valve.uom_id
        doc.action_create_quotation()
        self.assertEqual(doc.sale_order_id.order_line.product_uom_id, self.valve.uom_id)

    def test_only_a_ready_document_can_become_a_quotation(self):
        doc = self._doc(4, [("NOPE-1", 1, 1.0)], po="PO-QT-4")
        self.assertEqual(doc.state, "needs_review")
        with self.assertRaises(UserError):
            doc.action_create_quotation()
        self.assertFalse(doc.sale_order_id)

    def test_auto_create_when_clean_on_processing(self):
        self.inbox.auto_create_when_clean = True
        try:
            doc = self._doc(5, [("QT-1", 1, 10.0)], po="PO-QT-5")
            with mock.patch.object(
                type(doc), "_run_pipeline", lambda d: d._after_lines_extracted()
            ):
                doc.action_process()
            self.assertEqual(doc.state, "created")
            self.assertEqual(doc.sale_order_id.state, "draft")
        finally:
            self.inbox.auto_create_when_clean = False

    def test_a_forced_failure_creates_a_task_and_an_alert(self):
        doc = self._doc(6, [("QT-1", 1, 10.0)], po="PO-QT-6")
        doc.with_context(orderkoll_no_recheck=True).state = "new"
        Doc = type(doc)
        boom = mock.patch.object(Doc, "_run_pipeline", side_effect=RuntimeError("forced failure"))
        with boom, mock.patch.object(Doc, "_send_alert", return_value=True) as alert:
            doc.action_process()
        self.assertEqual(doc.state, "error")
        self.assertIn("forced failure", doc.error_message)
        task = doc.activity_ids.filtered(lambda a: a.summary == "Processing failed")
        self.assertEqual(len(task), 1)
        self.assertIn("forced failure", task.note)
        self.assertFalse(task.user_id._is_superuser())
        alert.assert_called_once()
        self.assertIn(f"#{doc.id}", alert.call_args[0][0])
        self.assertNotIn("forced failure", alert.call_args[0][0])  # no content in the alert

    def test_a_later_successful_run_closes_the_failure_task(self):
        doc = self._doc(8, [("QT-1", 1, 10.0)], po="PO-QT-8")
        doc.with_context(orderkoll_no_recheck=True).state = "new"
        Doc = type(doc)
        boom = mock.patch.object(Doc, "_run_pipeline", side_effect=RuntimeError("AI limit"))
        with boom, mock.patch.object(Doc, "_send_alert", return_value=True):
            doc.action_process()
        self.assertEqual(
            len(doc.activity_ids.filtered(lambda a: a.summary == "Processing failed")), 1
        )
        with mock.patch.object(Doc, "_run_pipeline", lambda d: d._after_lines_extracted()):
            doc.action_process()
        self.assertEqual(doc.state, "ready")
        self.assertFalse(doc.activity_ids.filtered(lambda a: a.summary == "Processing failed"))
        self.assertTrue(
            doc.message_ids.filtered(
                lambda m: "Processed successfully on a later run" in (m.body or "")
            )
        )

    def test_the_ready_hook_runs_once_per_entry(self):
        Doc = type(self.env["orderkoll.document"])
        with mock.patch.object(Doc, "_orderkoll_on_ready") as hook:
            doc = self._doc(7, [("QT-1", 1, 10.0)], po="PO-QT-7")
            self.assertEqual(doc.state, "ready")
            doc.action_recheck()  # still ready: no second call
            self.assertEqual(hook.call_count, 1)

    def test_the_cron_pings_the_heartbeat(self):
        Doc = type(self.env["orderkoll.document"])
        with mock.patch.object(Doc, "_ping_heartbeat") as ping:
            self.env["orderkoll.document"]._cron_process_pending(limit=1)
        ping.assert_called_once()


class TestPricelistFeature(TransactionCase):
    def test_installing_orderkoll_turns_the_pricelists_feature_on(self):
        # From Odoo 19 a customer's pricelist is ignored while the feature is off
        self.assertTrue(
            self.env["res.groups"]._is_feature_enabled("product.group_product_pricelist")
        )
