# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Product matching chain: customer code memory → internal reference → barcode → name."""

from odoo.tests import TransactionCase, tagged

from ..services.imap import FetchedMail


@tagged("post_install", "-at_install")
class TestProductMatching(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env["ir.config_parameter"].sudo().set_str("orderkoll.api_key", "")
        cls.inbox = cls.env["orderkoll.inbox"].create({"name": "Matching inbox"})
        cls.partner = cls.env["res.partner"].create(
            {"name": "Match T AB", "is_company": True, "email": "info@match-t.example"}
        )
        cls.env["res.partner"].create(
            {"name": "Buyer", "email": "buyer@match-t.example", "parent_id": cls.partner.id}
        )
        Product = cls.env["product.product"]
        cls.valve32 = Product.create(
            {
                "name": "Ball valve 32 mm grey",
                "default_code": "MT-1001",
                "barcode": "7300000000017",
                "sale_ok": True,
                "list_price": 1.0,
            }
        )
        cls.valve40 = Product.create(
            {
                "name": "Ball valve 40 mm grey",
                "default_code": "MT-1002",
                "barcode": "7300000000024",
                "sale_ok": True,
                "list_price": 1.0,
            }
        )
        cls.bolt = Product.create(
            {
                "name": "Hex bolt M8x40 zinc",
                "default_code": "MT-1003",
                "sale_ok": True,
                "list_price": 1.0,
            }
        )
        cls.env["orderkoll.sku_map"].create(
            {"partner_id": cls.partner.id, "customer_code": "CUST-77", "product_id": cls.bolt.id}
        )

    def _doc(self, uid, lines, sender="buyer@match-t.example"):
        doc = self.inbox._ingest_mail(
            FetchedMail(
                uid=uid,
                message_id=f"<match-{uid}@t>",
                sender_email=sender,
                sender_name="B",
                subject="PO",
                date=None,
                body_text="PO\n",
                body_html="",
                attachments=[],
            )
        )
        doc._resolve_partner()
        doc.write(
            {"line_ids": [(0, 0, dict({"quantity": 1.0, "unit_price": 1.0}, **ln)) for ln in lines]}
        )
        return doc

    def test_customer_code_memory_wins_and_counts_hits(self):
        doc = self._doc(1, [{"customer_code": "cust-77", "description": "whatever the PO says"}])
        doc._match_lines()
        line = doc.line_ids
        self.assertEqual(line.product_id, self.bolt)
        self.assertEqual(line.match_method, "sku_map")
        self.assertIn(line.status, ("matched", "ok"))
        row = self.env["orderkoll.sku_map"].search(
            [("partner_id", "=", self.partner.id), ("customer_code", "=", "CUST-77")]
        )
        self.assertEqual(row.hit_count, 1)

    def test_internal_reference_then_barcode(self):
        doc = self._doc(
            2,
            [
                {"customer_code": " mt-1001 ", "description": "Ball valve"},
                {"customer_code": "7300000000024", "description": "Ball valve"},
                {"customer_code": "MT 1003", "description": "bolts"},  # separators ignored
            ],
        )
        doc._match_lines()
        a, b, c = doc.line_ids.sorted("id")
        self.assertEqual((a.product_id, a.match_method), (self.valve32, "default_code"))
        self.assertEqual((b.product_id, b.match_method), (self.valve40, "barcode"))
        self.assertEqual((c.product_id, c.match_method), (self.bolt, "default_code"))

    def test_name_similarity_when_no_code(self):
        doc = self._doc(3, [{"customer_code": False, "description": "ball valve 32mm grey"}])
        doc._match_lines()
        line = doc.line_ids
        self.assertEqual(line.product_id, self.valve32)
        self.assertEqual(line.match_method, "fuzzy")
        self.assertGreaterEqual(line.match_score, 0.88)

    def test_unknown_code_stops_the_document(self):
        doc = self._doc(
            4,
            [
                {"customer_code": "MT-1001", "description": "Ball valve 32 mm grey"},
                {"customer_code": "ZZ-99999", "description": "Flux capacitor special"},
            ],
        )
        doc._after_lines_extracted()
        unknown = doc.line_ids.filtered(lambda ln: ln.customer_code == "ZZ-99999")
        self.assertFalse(unknown.product_id)
        self.assertEqual((unknown.match_method, unknown.status), ("none", "needs_mapping"))
        self.assertEqual(doc.state, "needs_review")
        self.assertIn("products: 1/2 matched; unknown: ZZ-99999", doc.checks_log)

    def test_all_matched_is_ready(self):
        doc = self._doc(5, [{"customer_code": "MT-1001", "description": "x"}])
        doc._after_lines_extracted()
        self.assertEqual(doc.state, "ready")
        self.assertIn("products: 1/1 matched", doc.checks_log)

    def test_mapped_code_resolves_on_the_second_document(self):
        first = self._doc(
            6,
            [{"customer_code": "NEW-500", "description": "Hex bolt M8x40 zinc (customer wording)"}],
        )
        first._after_lines_extracted()
        line = first.line_ids
        self.assertEqual(line.status, "needs_mapping")
        line.write({"product_id": self.bolt.id})
        line.action_remember_mapping()
        self.assertEqual(line.match_method, "manual")
        self.assertIn(line.status, ("matched", "ok"))
        row = self.env["orderkoll.sku_map"].search(
            [("partner_id", "=", self.partner.id), ("customer_code", "=", "NEW-500")]
        )
        self.assertEqual(row.product_id, self.bolt)
        second = self._doc(7, [{"customer_code": "new-500", "description": "anything"}])
        second._after_lines_extracted()
        self.assertEqual(second.line_ids.product_id, self.bolt)
        self.assertEqual(second.line_ids.match_method, "sku_map")
        self.assertEqual(row.hit_count, 1)
        self.assertEqual(second.state, "ready")

    def test_no_partner_means_no_code_memory_but_references_still_match(self):
        doc = self._doc(
            8,
            [
                {"customer_code": "CUST-77", "description": "x"},
                {"customer_code": "MT-1001", "description": "y"},
            ],
            sender="nobody@unknown-t.example",
        )
        doc._match_lines()
        a, b = doc.line_ids.sorted("id")
        self.assertEqual(a.status, "needs_mapping")  # memory is per customer; none known here
        self.assertEqual(b.product_id, self.valve32)

    def test_recent_products_of_the_customer_win_ties(self):
        Product = self.env["product.product"]
        twin = Product.create(
            {
                "name": "Ball valve 32 mm grey (bulk)",
                "default_code": "MT-1009",
                "sale_ok": True,
                "list_price": 1.0,
            }
        )
        order = self.env["sale.order"].create({"partner_id": self.partner.id})
        self.env["sale.order.line"].create(
            {"order_id": order.id, "product_id": twin.id, "product_uom_qty": 1}
        )
        doc = self._doc(9, [{"customer_code": False, "description": "Ball valve 32 mm grey"}])
        doc._match_lines()
        self.assertEqual(
            doc.line_ids.product_id, twin
        )  # recent for this customer beats the exact-name twin
        self.assertEqual(doc.line_ids.match_method, "fuzzy")

    def test_rematch_after_customer_is_picked(self):
        doc = self._doc(
            10,
            [{"customer_code": "CUST-77", "description": "x"}],
            sender="nobody@unknown-t.example",
        )
        doc._after_lines_extracted()
        self.assertEqual(doc.line_ids.status, "needs_mapping")
        self.env["orderkoll.pick_partner"].create(
            {"document_id": doc.id, "partner_id": self.partner.id, "remember_sender": False}
        ).action_pick()
        self.assertEqual(doc.line_ids.product_id, self.bolt)
        self.assertEqual(doc.state, "ready")

    def test_other_companys_products_and_memory_are_invisible(self):
        other = self.env["res.company"].create({"name": "Other Co"})
        self.env["product.product"].create(
            {
                "name": "Ball valve 50 mm grey",
                "default_code": "OC-5000",
                "sale_ok": True,
                "list_price": 1.0,
                "company_id": other.id,
            }
        )
        doc = self._doc(11, [{"customer_code": "OC-5000", "description": "Ball valve 50 mm grey"}])
        doc._match_lines()
        self.assertFalse(doc.line_ids.product_id)
        self.assertEqual(doc.line_ids.status, "needs_mapping")

    def test_ocr_documents_always_need_review(self):
        doc = self._doc(12, [{"customer_code": "MT-1001", "description": "x"}])
        doc.extraction_method = "ocr"
        doc._after_lines_extracted()
        self.assertEqual(doc.state, "needs_review")
        self.assertIn("scanned PDF read by OCR", doc.checks_log)
