# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Customer resolution: sender email → sender domain (never webmail) → manual pick."""

from odoo.tests import TransactionCase, tagged

from ..services.imap import FetchedMail


def _mail(uid, sender, body="PO 1\n10 x OK-1001 Ball valve @ 1.00"):
    return FetchedMail(
        uid=uid,
        message_id=f"<partner-{uid}@t>",
        sender_email=sender,
        sender_name="Someone",
        subject="PO",
        date=None,
        body_text=body,
        body_html="",
        attachments=[],
    )


@tagged("post_install", "-at_install")
class TestPartnerResolution(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_param("orderkoll.api_key", "")
        cls.inbox = cls.env["orderkoll.inbox"].create({"name": "Partner inbox"})
        Partner = cls.env["res.partner"]
        cls.nordic = Partner.create(
            {
                "name": "Nordic T AB",
                "is_company": True,
                "website": "https://www.nordic-t.example",
                "email": "info@nordic-t.example",
            }
        )
        cls.anna = Partner.create(
            {
                "name": "Anna Lind",
                "email": "Anna.Lind@Nordic-T.example",
                "parent_id": cls.nordic.id,
            }
        )
        cls.harbor = Partner.create(
            {"name": "Harbor T Co.", "is_company": True, "website": "harbor-t.example"}
        )
        cls.lakeside = Partner.create({"name": "Lakeside T", "is_company": True})
        Partner.create(
            {
                "name": "Dana (private)",
                "email": "dana.known@gmail.com",
                "parent_id": cls.lakeside.id,
            }
        )

    def _doc(self, uid, sender):
        doc = self.inbox._ingest_mail(_mail(uid, sender))
        doc.action_process()
        return doc

    def test_contact_email_resolves_to_the_company(self):
        doc = self._doc(1, "anna.lind@nordic-t.example")
        self.assertEqual(doc.partner_id, self.nordic)
        self.assertEqual(doc.partner_resolution, "email")
        self.assertIn("customer: email anna.lind@nordic-t.example → Nordic T AB", doc.checks_log)

    def test_unknown_address_on_known_domain_resolves_by_website(self):
        doc = self._doc(2, "new.buyer@harbor-t.example")
        self.assertEqual(doc.partner_id, self.harbor)
        self.assertEqual(doc.partner_resolution, "domain")

    def test_domain_matches_company_email_domain_too(self):
        doc = self._doc(3, "someone@nordic-t.example")
        self.assertEqual(doc.partner_id, self.nordic)
        self.assertEqual(doc.partner_resolution, "domain")

    def test_unknown_webmail_sender_stops_for_manual_pick(self):
        doc = self._doc(4, "dana.orders@gmail.com")
        self.assertFalse(doc.partner_id)
        self.assertEqual(doc.partner_resolution, "none")
        self.assertEqual(doc.state, "needs_review")
        self.assertIn("customer: not resolved (webmail domain gmail.com)", doc.checks_log)
        activities = doc.activity_ids.filtered(lambda a: a.summary == "Pick customer")
        self.assertEqual(len(activities), 1)

    def test_known_webmail_contact_resolves_by_exact_email(self):
        doc = self._doc(10, "Dana.Known@gmail.com")
        self.assertEqual(doc.partner_id, self.lakeside)
        self.assertEqual(doc.partner_resolution, "email")

    def test_unknown_domain_stops_for_manual_pick(self):
        doc = self._doc(5, "buyer@unknown-company.example")
        self.assertFalse(doc.partner_id)
        self.assertEqual(doc.partner_resolution, "none")
        self.assertTrue(doc.activity_ids.filtered(lambda a: a.summary == "Pick customer"))

    def test_pick_customer_wizard_sets_partner_and_remembers_the_sender(self):
        doc = self._doc(6, "buyer@unknown-company.example")
        wizard = self.env["orderkoll.pick_partner"].create(
            {"document_id": doc.id, "partner_id": self.lakeside.id, "remember_sender": True}
        )
        wizard.action_pick()
        self.assertEqual(doc.partner_id, self.lakeside)
        self.assertEqual(doc.partner_resolution, "manual")
        self.assertFalse(doc.activity_ids.filtered(lambda a: a.summary == "Pick customer"))
        contact = self.env["res.partner"].search([("email", "=", "buyer@unknown-company.example")])
        self.assertEqual(contact.commercial_partner_id, self.lakeside)
        # the next mail from that address resolves by email on its own
        again = self._doc(7, "buyer@unknown-company.example")
        self.assertEqual(again.partner_id, self.lakeside)
        self.assertEqual(again.partner_resolution, "email")

    def test_pick_customer_without_remember_does_not_create_a_contact(self):
        doc = self._doc(8, "once@unknown-company.example")
        self.env["orderkoll.pick_partner"].create(
            {"document_id": doc.id, "partner_id": self.harbor.id, "remember_sender": False}
        ).action_pick()
        self.assertEqual(doc.partner_id, self.harbor)
        self.assertFalse(
            self.env["res.partner"].search([("email", "=", "once@unknown-company.example")])
        )

    def test_wildcards_in_a_sender_address_never_match(self):
        self.env["res.partner"].create(
            {"name": "AB", "email": "ab@nordic-t.example", "parent_id": self.nordic.id}
        )
        doc = self._doc(11, "a%@nordic-t.example")  # not a valid address: no email match
        self.assertNotEqual(doc.partner_resolution, "email")
        doc = self._doc(12, "x@nordic_asteners.example")  # "_" must not act as a wildcard
        self.assertFalse(doc.partner_id)

    def test_other_companys_partner_is_never_matched(self):
        other = self.env["res.company"].create({"name": "Other Co"})
        self.env["res.partner"].create(
            {
                "name": "Elsewhere AB",
                "is_company": True,
                "email": "info@elsewhere.example",
                "company_id": other.id,
            }
        )
        doc = self._doc(13, "buyer@elsewhere.example")
        self.assertFalse(doc.partner_id)

    def test_two_customers_on_one_domain_is_ambiguous_and_stops(self):
        self.env["res.partner"].create(
            {
                "name": "Nordic T Sister AB",
                "is_company": True,
                "website": "https://nordic-t.example/sister",
            }
        )
        doc = self._doc(14, "someone-new@nordic-t.example")
        self.assertFalse(doc.partner_id)
        self.assertIn("2 customers share the domain", doc.checks_log)

    def test_custom_ignored_domains_setting(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "orderkoll.ignored_domains", "nordic-t.example"
        )
        doc = self._doc(9, "someone-else@nordic-t.example")
        self.assertFalse(doc.partner_id)
        self.assertEqual(doc.partner_resolution, "none")
