# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
import io
import unittest
import zipfile
from unittest import mock

try:
    from ._services import DATA, extract
except ImportError:  # unittest discovery rooted at tests/ (no Odoo)
    from _services import DATA, extract


class TestDetectSourceType(unittest.TestCase):
    def test_by_extension(self):
        self.assertEqual(extract.detect_source_type("PO 4711.pdf"), "pdf")
        self.assertEqual(extract.detect_source_type("order.XLSX"), "xlsx")
        self.assertEqual(extract.detect_source_type("order.xls"), "xlsx")
        self.assertEqual(extract.detect_source_type("lines.csv"), "csv")
        self.assertIsNone(extract.detect_source_type("logo.png"))
        self.assertIsNone(extract.detect_source_type("signature.jpg", "image/jpeg"))

    def test_by_mimetype_when_extension_is_useless(self):
        self.assertEqual(extract.detect_source_type("attachment", "application/pdf"), "pdf")
        self.assertEqual(
            extract.detect_source_type(
                "x", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            "xlsx",
        )
        self.assertEqual(extract.detect_source_type("x", "text/csv"), "csv")


class TestPdfText(unittest.TestCase):
    def test_classic_layout_keeps_codes_and_descriptions(self):
        text, method = extract.extract_pdf_text((DATA / "pdf-L01-1.pdf").read_bytes())
        self.assertEqual(method, "pdfplumber")
        self.assertIn("PO-2026-00364", text)
        self.assertIn("NF-42611", text)
        self.assertIn("Ball valve 32 mm grey", text)

    def test_swedish_serif_layout(self):
        text, _ = extract.extract_pdf_text((DATA / "pdf-L03-1.pdf").read_bytes())
        self.assertIn("PO-2026-00367", text)
        self.assertIn("NF-96589", text)
        self.assertIn("Inköpsorder".upper(), text.upper())

    def test_pypdf_fallback_when_pdfplumber_fails(self):
        data = (DATA / "pdf-L01-1.pdf").read_bytes()
        with mock.patch.object(extract, "_pdfplumber_text", side_effect=RuntimeError("boom")):
            text, method = extract.extract_pdf_text(data)
        self.assertEqual(method, "pypdf")
        self.assertIn("PO-2026-00364", text)

    def test_scanned_pdf_without_ocr_yields_empty_text_and_method_none(self):
        with mock.patch.object(extract, "_pdfplumber_text", return_value=""):
            with mock.patch.object(extract, "_pypdf_text", return_value="  \n "):
                with mock.patch.object(extract, "ocr_available", return_value=False):
                    text, method = extract.extract_pdf_text(b"%PDF-1.4 fake")
        self.assertEqual((text, method), ("", "none"))

    def test_scanned_pdf_with_ocr_uses_it(self):
        with mock.patch.object(extract, "_pdfplumber_text", return_value=""):
            with mock.patch.object(extract, "_pypdf_text", return_value=""):
                with mock.patch.object(extract, "ocr_available", return_value=True):
                    with mock.patch.object(
                        extract, "_ocr_pdf_text", return_value="=== page 1 ===\nPO 4711\n10 x A-1"
                    ):
                        text, method = extract.extract_pdf_text(b"%PDF-1.4 fake")
        self.assertEqual(method, "ocr")
        self.assertIn("PO 4711", text)

    def test_ocr_failure_degrades_to_none(self):
        with mock.patch.object(extract, "_pdfplumber_text", return_value=""):
            with mock.patch.object(extract, "_pypdf_text", return_value=""):
                with mock.patch.object(extract, "ocr_available", return_value=True):
                    with mock.patch.object(
                        extract, "_ocr_pdf_text", side_effect=RuntimeError("tesseract crashed")
                    ):
                        text, method = extract.extract_pdf_text(b"%PDF-1.4 fake")
        self.assertEqual((text, method), ("", "none"))

    def test_text_pdf_never_goes_through_ocr(self):
        with mock.patch.object(
            extract, "_ocr_pdf_text", side_effect=AssertionError("must not run")
        ):
            text, method = extract.extract_pdf_text((DATA / "pdf-L01-1.pdf").read_bytes())
        self.assertEqual(method, "pdfplumber")


class TestSpreadsheetText(unittest.TestCase):
    def test_xlsx_becomes_csv_rows(self):
        text = extract.extract_xlsx_text((DATA / "xlsx-1.xlsx").read_bytes())
        self.assertIn("HS000401", text)
        self.assertIn("OK-1179,Torx bit 8 mm pro,250,", text)
        self.assertIn("380.59", text)

    def test_xlsx_with_title_rows_and_description_first(self):
        text = extract.extract_xlsx_text((DATA / "xlsx-3.xlsx").read_bytes())
        self.assertIn("PURCHASE ORDER PO-2026-00385", text)
        self.assertIn("Description,Our code,Qty,Unit price,Line total", text)
        self.assertIn("Cutting disc T30 grade 40,NF-40524,50,1103.9,55195", text)
        self.assertIn(",,,,Total,429169.74", text)

    def test_xlsx_zip_bomb_is_refused(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("[Content_Types].xml", "<Types/>")
            zf.writestr("xl/worksheets/sheet1.xml", b"0" * 5_000_000)  # ~5 kB zipped
        with self.assertRaisesRegex(ValueError, "zip bomb"):
            extract.extract_xlsx_text(buf.getvalue())

    def test_xlsx_over_the_size_cap_is_refused(self):
        data = (DATA / "xlsx-1.xlsx").read_bytes()
        with mock.patch.object(extract, "MAX_UNZIPPED", 1000):
            with self.assertRaisesRegex(ValueError, "zip bomb"):
                extract.extract_xlsx_text(data)

    def test_not_a_zip_is_refused(self):
        with self.assertRaisesRegex(ValueError, "not a valid .xlsx"):
            extract.extract_xlsx_text(b"not a spreadsheet")

    def test_csv_is_decoded_and_normalised(self):
        self.assertEqual(extract.extract_csv_text(b"code;qty\r\nA-1;5\r\n"), "code;qty\nA-1;5")
        self.assertEqual(extract.extract_csv_text("ö,1\n".encode("latin-1")), "ö,1")


class TestEmailBody(unittest.TestCase):
    BODY = (
        "Hello,\n\nPlease find our purchase order AT/2026/0318 below.\n\n"
        "- 20 Units AT-24286 PP elbow 90° 40 mm grey @ 1.20 GBP\n"
        "- 5 Box AT-10001 Torx bit T25 pro @ 12.00 GBP\n\n"
        "Total incl. VAT: 100.00 GBP\n\nBest regards,\nJames Hartley\nAlbion Tools Ltd\n\n"
        "-----Original Message-----\nFrom: orders@orderkoll-demo.example\n"
        "> Thanks for the updated price list\n> Regards\n"
    )

    def test_quotes_and_signature_are_stripped_but_order_lines_kept(self):
        cleaned = extract.clean_email_body(self.BODY)
        self.assertIn("AT/2026/0318", cleaned)
        self.assertIn("AT-24286", cleaned)
        self.assertIn("Total incl. VAT: 100.00 GBP", cleaned)
        self.assertNotIn("Original Message", cleaned)
        self.assertNotIn("> Thanks", cleaned)
        self.assertNotIn("James Hartley", cleaned)
        self.assertNotIn("Best regards", cleaned)

    def test_on_wrote_quote_and_swedish_signoff(self):
        body = (
            "Beställning 12\n10 st ABC-1\n\nMed vänliga hälsningar\nAnna\n\n"
            "On Mon, Anna wrote:\n> old"
        )
        cleaned = extract.clean_email_body(body)
        self.assertEqual(cleaned, "Beställning 12\n10 st ABC-1")

    def test_forwarded_po_keeps_the_forwarded_content(self):
        body = (
            "Hi, please process the order below.\n\n---------- Forwarded message ---------\n"
            "From: purchasing@buyer.example\nSubject: PO 4711\n\nPO 4711\n10 x A-1 @ 2.00\n"
        )
        cleaned = extract.clean_email_body(body)
        self.assertIn("PO 4711", cleaned)
        self.assertIn("10 x A-1 @ 2.00", cleaned)

    def test_signoff_word_on_the_first_line_does_not_wipe_the_body(self):
        self.assertEqual(
            extract.clean_email_body("Thanks\nPO 12\n3 x B-2 @ 1.00\n"),
            "Thanks\nPO 12\n3 x B-2 @ 1.00",
        )

    def test_falls_back_to_the_full_text_when_nothing_with_a_number_is_left(self):
        body = "Hello\n> PO 99\n> 2 x C-3 @ 5.00\n"
        cleaned = extract.clean_email_body(body)
        self.assertIn("2 x C-3 @ 5.00", cleaned)

    def test_signature_without_signoff_is_kept(self):
        body = "PO 99\n2 x THING-1 @ 3.00\n"
        self.assertEqual(extract.clean_email_body(body), "PO 99\n2 x THING-1 @ 3.00")

    def test_html_to_text(self):
        html = "<html><body><p>PO <b>12</b></p><p>10 x A-1</p><br><div>end</div></body></html>"
        self.assertEqual(extract.html_to_text(html), "PO 12\n10 x A-1\nend")


class TestDispatch(unittest.TestCase):
    def test_extract_text_routes_by_source_type(self):
        text, method = extract.extract_text("pdf", (DATA / "pdf-L01-1.pdf").read_bytes())
        self.assertEqual(method, "pdfplumber")
        self.assertIn("PO-2026-00364", text)
        text, method = extract.extract_text("xlsx", (DATA / "xlsx-1.xlsx").read_bytes())
        self.assertEqual(method, "openpyxl")
        self.assertIn("HS000401", text)
        text, method = extract.extract_text("csv", b"a,b\n1,2")
        self.assertEqual((text, method), ("a,b\n1,2", "csv"))
        with self.assertRaises(ValueError):
            extract.extract_text("docx", b"")
