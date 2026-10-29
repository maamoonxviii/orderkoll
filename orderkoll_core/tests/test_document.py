# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Odoo-level tests: a fetched mail becomes a document with its extracted text."""

from datetime import datetime, timezone
from unittest import mock

import psycopg2
from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged
from odoo.tools import mute_logger

from ..services.imap import Attachment, FetchedMail
from ._services import DATA
from .test_imap_service import FakeImap


def _mail(
    uid=1,
    sender="anna.lind@nordicfasteners.example",
    attachments=None,
    body="Please see attached.",
    message_id=None,
):
    return FetchedMail(
        uid=uid,
        message_id=message_id or f"<msg-{uid}@nordicfasteners.example>",
        sender_email=sender,
        sender_name="Anna Lind",
        subject=f"PO {uid}",
        date=datetime(2026, 10, 4, 9, 30, tzinfo=timezone.utc),
        body_text=body,
        body_html="",
        attachments=attachments or [],
    )


@tagged("post_install", "-at_install")
class TestDocumentIntake(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Core's tests describe the flow without an extraction engine. If Orderkoll
        # Pro is installed on the test database with a key, it must stay out.
        cls.env["ir.config_parameter"].sudo().set_param("orderkoll.api_key", "")
        cls.inbox = cls.env["orderkoll.inbox"].create({"name": "Test inbox"})
        cls.pdf = (DATA / "pdf-L01-1.pdf").read_bytes()
        cls.xlsx = (DATA / "xlsx-1.xlsx").read_bytes()

    def test_pdf_mail_becomes_document_with_raw_text(self):
        mail = _mail(
            attachments=[
                Attachment("PO-2026-00364.pdf", self.pdf, "application/pdf"),
                Attachment("logo.png", b"\x89PNG", "image/png"),
            ]
        )
        doc = self.inbox._ingest_mail(mail)
        self.assertEqual(doc.state, "new")
        self.assertEqual(doc.source_type, "pdf")
        self.assertEqual(doc.sender_email, "anna.lind@nordicfasteners.example")
        self.assertEqual(doc.sender_domain, "nordicfasteners.example")
        self.assertEqual(doc.attachment_id.name, "PO-2026-00364.pdf")
        self.assertEqual(doc.extra_attachment_ids.mapped("name"), ["logo.png"])
        self.assertEqual(doc.imap_uid, 1)

        doc.action_process()
        self.assertEqual(doc.extraction_method, "pdfplumber")
        self.assertIn("PO-2026-00364", doc.raw_text)
        self.assertIn("NF-42611", doc.raw_text)
        self.assertEqual(doc.state, "needs_review")  # core has no extraction engine
        self.assertIn("extraction engine", doc.checks_log)
        self.assertIn("text extraction: pdfplumber", doc.checks_log)
        self.assertEqual(doc.name, "PO-2026-00364.pdf")

    def test_xlsx_attachment(self):
        doc = self.inbox._ingest_mail(
            _mail(
                uid=2, attachments=[Attachment("order.xlsx", self.xlsx, "application/octet-stream")]
            )
        )
        self.assertEqual(doc.source_type, "xlsx")
        doc.action_process()
        self.assertEqual(doc.extraction_method, "openpyxl")
        self.assertIn("HS000401", doc.raw_text)

    def test_body_only_mail_is_cleaned(self):
        body = "Hi,\n10 x NF-42611 Ball valve @ 294.20\n\nBest regards,\nAnna\n\n> old quoted mail"
        doc = self.inbox._ingest_mail(_mail(uid=3, body=body))
        self.assertEqual(doc.source_type, "email_body")
        self.assertFalse(doc.attachment_id)
        doc.action_process()
        self.assertEqual(doc.extraction_method, "email")
        self.assertIn("NF-42611", doc.raw_text)
        self.assertNotIn("old quoted mail", doc.raw_text)
        self.assertNotIn("Best regards", doc.raw_text)

    def test_same_message_id_is_ingested_once(self):
        first = self.inbox._ingest_mail(_mail(uid=4, message_id="<dup@x>"))
        second = self.inbox._ingest_mail(_mail(uid=5, message_id="<dup@x>"))
        self.assertTrue(first)
        self.assertFalse(second)

    def test_state_changes_are_posted_in_chatter(self):
        doc = self.inbox._ingest_mail(
            _mail(uid=6, attachments=[Attachment("po.pdf", self.pdf, "application/pdf")])
        )
        before = len(doc.message_ids)
        doc.action_process()
        bodies = " ".join(doc.message_ids.mapped("body"))
        self.assertGreater(len(doc.message_ids), before)
        self.assertIn("Needs review", bodies)

    def test_fetch_mail_with_fake_imap_advances_last_uid(self):
        self.inbox.write(
            {
                "imap_enabled": True,
                "imap_host": "imap.test",
                "imap_user": "u",
                "imap_password": "p",
                "imap_last_uid": 1,
            }
        )
        docs = self.inbox.fetch_mail(client_factory=FakeImap)
        self.assertEqual(len(docs), 3)
        self.assertEqual(self.inbox.imap_last_uid, 12)
        self.assertEqual(self.inbox.imap_uidvalidity, 1700000000)
        self.assertFalse(self.inbox.imap_last_error)
        self.assertEqual(set(docs.mapped("source_type")), {"email_body"})
        again = self.inbox.fetch_mail(client_factory=FakeImap)
        self.assertFalse(again)

    def test_first_activation_starts_at_the_newest_mail(self):
        self.inbox.write(
            {"imap_host": "imap.test", "imap_user": "u", "imap_password": "p", "imap_last_uid": 0}
        )
        docs = self.inbox.fetch_mail(client_factory=FakeImap)
        self.assertFalse(docs)  # history is never imported
        self.assertEqual(self.inbox.imap_last_uid, 12)
        self.assertEqual(self.inbox.imap_uidvalidity, 1700000000)

    def test_uidvalidity_change_restarts_at_the_newest_mail(self):
        self.inbox.write(
            {
                "imap_host": "imap.test",
                "imap_user": "u",
                "imap_password": "p",
                "imap_last_uid": 500,
                "imap_uidvalidity": 1,
            }
        )
        docs = self.inbox.fetch_mail(client_factory=FakeImap)
        self.assertFalse(docs)
        self.assertEqual(self.inbox.imap_last_uid, 12)
        self.assertEqual(self.inbox.imap_uidvalidity, 1700000000)
        self.assertIn("UIDVALIDITY changed", self.inbox.imap_last_error)

    def test_one_bad_mail_does_not_block_the_rest(self):
        self.inbox.write(
            {"imap_host": "imap.test", "imap_user": "u", "imap_password": "p", "imap_last_uid": 1}
        )
        original = type(self.inbox)._ingest_mail

        def flaky(inbox, mail):
            if mail.uid == 9:
                raise ValueError("boom on 9")
            return original(inbox, mail)

        with mock.patch.object(type(self.inbox), "_ingest_mail", flaky):
            docs = self.inbox.fetch_mail(client_factory=FakeImap)
        self.assertEqual(sorted(docs.mapped("imap_uid")), [4, 12])
        self.assertEqual(self.inbox.imap_last_uid, 12)
        self.assertIn("uid 9", self.inbox.imap_last_error)
        self.assertIn("boom on 9", self.inbox.imap_last_error)

    def test_email_date_is_stored_in_utc(self):
        doc = self.inbox._ingest_mail(_mail(uid=20))  # 09:30 UTC in the helper
        self.assertEqual(str(doc.email_date), "2026-10-04 09:30:00")
        from datetime import timedelta
        from datetime import timezone as tz

        cest = _mail(uid=21)
        cest.date = cest.date.astimezone(tz(timedelta(hours=2)))  # same instant, +02:00
        doc2 = self.inbox._ingest_mail(cest)
        self.assertEqual(str(doc2.email_date), "2026-10-04 09:30:00")

    def test_transient_failure_keeps_the_document_new_then_gives_up(self):
        from ..services.errors import TransientProcessingError

        doc = self.inbox._ingest_mail(
            _mail(uid=22, attachments=[Attachment("po.pdf", self.pdf, "application/pdf")])
        )
        with mock.patch.object(
            type(doc), "_extract_lines", side_effect=TransientProcessingError("429 slow down")
        ):
            doc.action_process()
            self.assertEqual((doc.state, doc.retry_count), ("new", 1))
            self.assertIn("will retry", doc.error_message)
            doc.action_process()
            doc.action_process()
        self.assertEqual((doc.state, doc.retry_count), ("error", 3))
        self.assertIn("Gave up", doc.error_message)

    def test_a_concurrent_update_is_raised_for_odoo_to_retry(self):
        doc = self.inbox._ingest_mail(
            _mail(uid=23, attachments=[Attachment("po.pdf", self.pdf, "application/pdf")])
        )
        conflict = psycopg2.errors.SerializationFailure("concurrent update")
        with mock.patch.object(type(doc), "_run_pipeline", side_effect=conflict):
            with self.assertRaises(psycopg2.extensions.TransactionRollbackError):
                doc.action_process()
        self.assertNotEqual(doc.state, "error")

    def test_fetch_failure_is_recorded_not_raised(self):
        self.inbox.write({"imap_host": "imap.test", "imap_user": "u", "imap_password": "p"})

        def broken(host, port):
            raise OSError("connection refused")

        docs = self.inbox.fetch_mail(client_factory=broken)
        self.assertFalse(docs)
        self.assertIn("connection refused", self.inbox.imap_last_error)

    def test_cron_processes_new_documents(self):
        doc = self.inbox._ingest_mail(
            _mail(uid=7, attachments=[Attachment("po.pdf", self.pdf, "application/pdf")])
        )
        self.env["orderkoll.document"]._cron_process_pending()
        self.assertEqual(doc.state, "needs_review")
        self.assertTrue(doc.raw_text)

    def test_sku_map_upper_cases_and_is_unique(self):
        partner = self.env["res.partner"].create({"name": "Nordic Fasteners AB"})
        product = self.env["product.product"].create(
            {"name": "Ball valve", "default_code": "OK-1001"}
        )
        row = self.env["orderkoll.sku_map"].create(
            {"partner_id": partner.id, "customer_code": " nf-42611 ", "product_id": product.id}
        )
        self.assertEqual(row.customer_code, "NF-42611")
        with self.assertRaises(IntegrityError), mute_logger("odoo.sql_db"), self.cr.savepoint():
            self.env["orderkoll.sku_map"].create(
                {"partner_id": partner.id, "customer_code": "NF-42611", "product_id": product.id}
            )

    def test_foreign_attachment_cannot_be_linked(self):
        doc = self.inbox._ingest_mail(_mail(uid=8))
        other = self.env["ir.attachment"].create(
            {"name": "secret.pdf", "datas": b"c2VjcmV0", "res_model": "res.partner", "res_id": 1}
        )
        with self.assertRaises(ValidationError):
            doc.write({"attachment_id": other.id})
        with self.assertRaises(ValidationError):
            doc.write({"extra_attachment_ids": [(4, other.id)]})

    def test_attachment_mimetypes_are_allowlisted(self):
        safe = type(self.inbox)._safe_mimetype
        self.assertEqual(safe("application/pdf", "po.pdf"), "application/pdf")
        self.assertEqual(safe("image/png", "logo.png"), "image/png")
        self.assertEqual(safe("text/html", "x.html"), "application/octet-stream")
        self.assertEqual(safe("image/svg+xml", "x.svg"), "application/octet-stream")
        self.assertEqual(safe("application/xslt+xml", "x.bin"), "application/octet-stream")
        self.assertEqual(safe("application/pdf", "trick.svg"), "application/octet-stream")

    def test_imap_path_attachment_is_neutralised_too(self):
        doc = self.env["orderkoll.document"].create(
            {"inbox_id": self.inbox.id, "sender_email": "x@nordic-t.example", "source_type": "pdf"}
        )
        att = self.inbox._make_attachment(
            doc, Attachment("evil.svg", b"<svg onload=alert(1)></svg>", "image/svg+xml")
        )
        self.assertEqual(att.mimetype, "text/plain")
