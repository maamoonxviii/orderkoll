# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Mail alias intake: an email to the inbox's alias creates a document."""

import contextlib

from odoo.tests import TransactionCase, tagged

from ._services import DATA

RAW_WITH_PDF = b"""From: Anna Lind <anna.lind@nordic-a.example>
To: po@alias-t.example
Subject: Purchase order PO-A-1
Message-ID: <alias-1@nordic-a.example>
Date: Sun, 04 Oct 2026 09:30:00 +0200
MIME-Version: 1.0
Content-Type: multipart/mixed; boundary="b1"

--b1
Content-Type: text/plain; charset="utf-8"

Please find our purchase order attached.

--b1
Content-Type: application/pdf; name="PO-A-1.pdf"
Content-Disposition: attachment; filename="PO-A-1.pdf"
Content-Transfer-Encoding: base64

%s
--b1--
"""


@tagged("post_install", "-at_install")
class TestAliasIntake(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("orderkoll.api_key", "")
        cls.domain = cls.env["mail.alias.domain"].create({"name": "alias-t.example"})
        cls.inbox = cls.env["orderkoll.inbox"].create(
            {"name": "Alias inbox", "alias_name": "po", "alias_domain_id": cls.domain.id}
        )

    def _raw(self):
        import base64

        pdf = base64.encodebytes((DATA / "pdf-L01-1.pdf").read_bytes())
        return RAW_WITH_PDF % pdf

    def test_alias_is_created_on_the_document_model(self):
        alias = self.inbox.alias_id
        self.assertEqual(alias.alias_name, "po")
        self.assertEqual(alias.alias_model_id.model, "orderkoll.document")
        self.assertIn("inbox_id", alias.alias_defaults)

    def test_mail_to_the_alias_creates_a_document(self):
        before = self.env["orderkoll.document"].search_count([("inbox_id", "=", self.inbox.id)])
        self.env["mail.thread"].message_process("orderkoll.document", self._raw())
        docs = self.env["orderkoll.document"].search([("inbox_id", "=", self.inbox.id)])
        self.assertEqual(len(docs), before + 1)
        doc = docs.sorted("id")[-1]
        self.assertEqual(doc.sender_email, "anna.lind@nordic-a.example")
        self.assertEqual(doc.source_type, "pdf")
        self.assertEqual(doc.attachment_id.name, "PO-A-1.pdf")
        self.assertEqual(doc.email_message_id, "<alias-1@nordic-a.example>")
        self.assertEqual(doc.state, "new")
        doc.action_process()
        self.assertIn("PO-2026-00364", doc.raw_text)

    def test_same_mail_twice_is_one_document(self):
        self.env["mail.thread"].message_process("orderkoll.document", self._raw())
        self.env["mail.thread"].message_process("orderkoll.document", self._raw())
        docs = self.env["orderkoll.document"].search(
            [
                ("inbox_id", "=", self.inbox.id),
                ("email_message_id", "=", "<alias-1@nordic-a.example>"),
            ]
        )
        self.assertEqual(len(docs), 1)

    def test_body_only_mail_via_alias(self):
        raw = (
            b"From: buyer@nordic-a.example\r\nTo: po@alias-t.example\r\nSubject: order\r\n"
            b"Message-ID: <alias-2@nordic-a.example>\r\n\r\n"
            b"PO 77\r\n10 x OK-1001 Ball valve @ 2.00\r\n"
        )
        self.env["mail.thread"].message_process("orderkoll.document", raw)
        doc = self.env["orderkoll.document"].search(
            [("email_message_id", "=", "<alias-2@nordic-a.example>")]
        )
        self.assertEqual(doc.source_type, "email_body")
        self.assertIn("10 x OK-1001", doc.email_body)

    def test_configured_default_cannot_redirect_mail_to_another_inbox(self):
        other = self.env["orderkoll.inbox"].create({"name": "Other inbox"})
        raw = (
            b"From: buyer@nordic-a.example\r\nTo: po@alias-t.example\r\nSubject: order\r\n"
            b"Message-ID: <alias-3@nordic-a.example>\r\n\r\nPO 78\r\n1 x OK-1001\r\n"
        )
        self.env["mail.thread"].message_process(
            "orderkoll.document", raw, custom_values={"inbox_id": other.id}
        )
        doc = self.env["orderkoll.document"].search(
            [("email_message_id", "=", "<alias-3@nordic-a.example>")]
        )
        self.assertEqual(doc.inbox_id, self.inbox)  # the alias owner, not the injected default

    def test_html_attachment_is_stored_neutralised(self):
        raw = (
            b"From: buyer@nordic-a.example\r\nTo: po@alias-t.example\r\nSubject: order\r\n"
            b"Message-ID: <alias-4@nordic-a.example>\r\nMIME-Version: 1.0\r\n"
            b'Content-Type: multipart/mixed; boundary="b2"\r\n\r\n--b2\r\n'
            b"Content-Type: text/plain\r\n\r\nPO 79\r\n--b2\r\n"
            b'Content-Type: text/html; name="evil.html"\r\n'
            b'Content-Disposition: attachment; filename="evil.html"\r\n\r\n'
            b"<script>alert(1)</script>\r\n--b2--\r\n"
        )
        self.env["mail.thread"].message_process("orderkoll.document", raw)
        doc = self.env["orderkoll.document"].search(
            [("email_message_id", "=", "<alias-4@nordic-a.example>")]
        )
        # our allowlist hands Odoo a generic binary; Odoo sniffs the HTML and, with the
        # plainxml flag we set, stores it as text/plain. Never anything a browser renders.
        self.assertEqual(doc.extra_attachment_ids.mapped("mimetype"), ["text/plain"])
        stored = self.env["ir.attachment"].search(
            [("res_model", "=", "orderkoll.document"), ("res_id", "=", doc.id)]
        )
        self.assertEqual(stored, doc.extra_attachment_ids)  # no gateway copy of the original

    def test_duplicate_message_id_from_another_sender_never_reaches_the_document(self):
        self.env["mail.thread"].message_process("orderkoll.document", self._raw())
        forged = self._raw().replace(b"anna.lind@nordic-a.example", b"mallory@elsewhere.example")
        # Odoo's gateway drops an already-processed Message-ID; if one ever got through,
        # message_new refuses every duplicate (ValueError). Either way: nothing changes.
        with contextlib.suppress(ValueError):
            self.env["mail.thread"].message_process("orderkoll.document", forged)
        docs = self.env["orderkoll.document"].search(
            [("email_message_id", "=", "<alias-1@nordic-a.example>")]
        )
        self.assertEqual(len(docs), 1)
        self.assertEqual(docs.sender_email, "anna.lind@nordic-a.example")
        self.assertFalse(docs.message_ids.filtered(lambda m: "mallory" in (m.email_from or "")))

    def test_message_new_refuses_a_duplicate_from_another_sender(self):
        self.env["mail.thread"].message_process("orderkoll.document", self._raw())
        with self.assertRaises(ValueError):
            self.env["orderkoll.document"].message_new(
                {
                    "message_id": "<alias-1@nordic-a.example>",
                    "from": "mallory@elsewhere.example",
                    "subject": "x",
                    "body": "<p>x</p>",
                    "attachments": [],
                },
                {"inbox_id": self.inbox.id},
            )

    def test_review_activity_is_never_assigned_to_the_system_user(self):
        self.inbox.user_id = False
        raw = (
            b"From: someone@unknown-co.example\r\nTo: po@alias-t.example\r\nSubject: order\r\n"
            b"Message-ID: <alias-5@nordic-a.example>\r\n\r\nPO 80\r\n1 x OK-1001\r\n"
        )
        self.env["mail.thread"].with_user(self.env.ref("base.user_root")).message_process(
            "orderkoll.document", raw
        )
        doc = self.env["orderkoll.document"].search(
            [("email_message_id", "=", "<alias-5@nordic-a.example>")]
        )
        doc.with_user(self.env.ref("base.user_root")).action_process()
        act = doc.activity_ids.filtered(lambda a: a.summary == "Pick customer")
        self.assertTrue(act)
        self.assertFalse(act.user_id._is_superuser())
