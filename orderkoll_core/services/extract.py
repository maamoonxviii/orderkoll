# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
"""Text extraction for purchase-order documents.

Order inside the modules: pdfplumber (with tables) → pypdf fallback →
empty text means a scan (OCR is optional and lives in a later step). Excel via
openpyxl as CSV text. Email bodies: quoted replies and signatures stripped with
a plain heuristic. No Docling, no PyTorch here.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from html.parser import HTMLParser

_logger = logging.getLogger(__name__)

# Caps: a purchase order is a few pages and a few hundred rows; anything beyond is cut.
MAX_PAGES = 50
MAX_ROWS = 5000
MAX_CHARS = 300_000
MAX_UNZIPPED = 50 * 1024 * 1024  # an .xlsx is a zip: refuse "zip bombs"
MAX_ZIP_RATIO = 100

SOURCE_TYPES = ("pdf", "xlsx", "csv", "email_body")
_PDF_MIMES = {"application/pdf", "application/x-pdf"}
_XLSX_MIMES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "application/vnd.ms-excel.sheet.macroenabled.12",
}
_CSV_MIMES = {"text/csv", "application/csv"}

_QUOTE_MARKERS = (
    # "Forwarded message" is deliberately NOT a marker: buyers forward their internal
    # PO mail to the supplier, and the order is below that line.
    re.compile(r"^-{2,}\s*original message\s*-{2,}\s*$", re.I),
    re.compile(r"^_{5,}\s*$"),
    re.compile(r"^on .+ wrote:\s*$", re.I),
    re.compile(r"^(den|på) .+ skrev( .+)?:\s*$", re.I),
    re.compile(r"^am .+ schrieb( .+)?:\s*$", re.I),
    re.compile(r"^le .+ a écrit\s*:\s*$", re.I),
    re.compile(r"^>"),
)
_SIGNOFFS = re.compile(
    r"^(best regards|kind regards|warm regards|regards|best|thanks|thank you|many thanks|cheers|"
    r"sincerely|yours sincerely|br|mvh|vänliga hälsningar|med vänliga? hälsningar|hälsningar|"
    r"mit freundlichen grüßen|freundliche grüße|viele grüße|met vriendelijke groet(en)?|"
    r"cordialement|bien cordialement|saludos|un saludo|venlig hilsen|med venlig hilsen)[,.!\s]*$",
    re.I,
)


# ------------------------------------------------------------------ detection
def detect_source_type(filename: str, mimetype: str | None = None) -> str | None:
    """pdf / xlsx / csv from the file name, else from the mimetype; None if neither."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext == "pdf":
        return "pdf"
    if ext in ("xlsx", "xlsm", "xls"):
        return "xlsx"
    if ext == "csv":
        return "csv"
    if mimetype in _PDF_MIMES:
        return "pdf"
    if mimetype in _XLSX_MIMES:
        return "xlsx"
    if mimetype in _CSV_MIMES:
        return "csv"
    return None


# ------------------------------------------------------------------------ pdf
def _pdfplumber_text(data: bytes) -> str:
    import pdfplumber

    parts = []
    # Only the first MAX_PAGES pages are ever parsed; the rest is never built.
    with pdfplumber.open(io.BytesIO(data), pages=list(range(1, MAX_PAGES + 1))) as pdf:
        for number, page in enumerate(pdf.pages, 1):
            parts.append(f"=== page {number} ===")
            parts.append(page.extract_text() or "")
            for table in page.extract_tables():
                rows = [
                    " | ".join((cell or "").replace("\n", " ").strip() for cell in row)
                    for row in table
                ]
                parts.append("[table]\n" + "\n".join(rows) + "\n[/table]")
    return "\n".join(parts)


def _pypdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(
        f"=== page {number} ===\n{page.extract_text() or ''}"
        for number, page in enumerate(reader.pages[:MAX_PAGES], 1)
    )


OCR_LANGS = "eng+swe+deu"
OCR_DPI = 250
OCR_MAX_PIXELS = 20_000_000  # per page (~A3 at 250 dpi); bigger pages are downscaled
OCR_PAGE_TIMEOUT = 60  # seconds of Tesseract per page
OCR_TOTAL_TIMEOUT = 300  # seconds for the whole document


def ocr_available() -> bool:
    """pytesseract importable and the tesseract binary on PATH (both optional)."""
    try:
        import pytesseract

        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 - absence of either means no OCR, nothing more
        return False
    return True


def _ocr_pdf_text(data: bytes) -> str:
    """Rasterise each page and run Tesseract on it (pages capped like the parsers)."""
    import pypdfium2 as pdfium
    import pytesseract

    try:
        available = set(pytesseract.get_languages())
        langs = "+".join(code for code in OCR_LANGS.split("+") if code in available) or "eng"
    except Exception:  # noqa: BLE001 - language listing is a nicety
        langs = "eng"
    import time

    pdf = pdfium.PdfDocument(data)
    parts = []
    started = time.monotonic()
    for number, page in enumerate(pdf, 1):
        if number > MAX_PAGES or time.monotonic() - started > OCR_TOTAL_TIMEOUT:
            parts.append(f"[OCR stopped at page {number}: page or time budget reached]")
            break
        width, height = page.get_size()  # points
        scale = OCR_DPI / 72
        pixels = width * height * scale * scale
        if pixels > OCR_MAX_PIXELS:
            scale = scale * (OCR_MAX_PIXELS / pixels) ** 0.5  # keep the page under the budget
        image = page.render(scale=scale).to_pil().convert("L")
        text = pytesseract.image_to_string(
            image, lang=langs, config="--psm 6", timeout=OCR_PAGE_TIMEOUT
        )
        parts.append(f"=== page {number} ===\n{text}")
    return "\n".join(parts)


def extract_pdf_text(data: bytes) -> tuple[str, str]:
    """Return (text, method). method is pdfplumber, pypdf, ocr (scan with Tesseract
    installed) or none (scan without OCR, or OCR found nothing)."""
    for method, func in (("pdfplumber", _pdfplumber_text), ("pypdf", _pypdf_text)):
        try:
            text = func(data)
        except Exception as exc:  # noqa: BLE001 - any parser failure falls through to the next
            _logger.info("%s failed, falling back: %s", method, exc)
            continue
        if _has_words(text):
            return text.strip(), method
    if ocr_available():
        try:
            text = _ocr_pdf_text(data)
        except Exception as exc:  # noqa: BLE001 - OCR trouble must not break intake
            _logger.warning("OCR failed: %s", exc)
            text = ""
        if _has_words(text):
            return text.strip(), "ocr"
    return "", "none"


def _has_words(text: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9]{2,}", re.sub(r"=== page \d+ ===", "", text or "")))


# ---------------------------------------------------------------- xlsx / csv
def _cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def check_zip_size(data: bytes) -> None:
    """ValueError for a "zip bomb": a tiny file that unzips to an enormous one.
    The sizes in the zip directory are a hard limit: Python's zipfile never returns more."""
    import zipfile

    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            unzipped = sum(info.file_size for info in zf.infolist())
    except zipfile.BadZipFile as exc:
        raise ValueError("not a valid .xlsx file") from exc
    if unzipped > MAX_UNZIPPED or unzipped > max(len(data), 1) * MAX_ZIP_RATIO:
        raise ValueError(
            f"spreadsheet refused: {len(data)} bytes unzip to {unzipped} bytes (zip bomb)"
        )


def extract_xlsx_text(data: bytes) -> str:
    """All sheets as CSV text, empty rows dropped, one '## Sheet:' header per sheet."""
    import openpyxl

    check_zip_size(data)
    workbook = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    budget = MAX_ROWS  # total rows iterated across all sheets, empty ones included
    for sheet in workbook.worksheets:
        out.write(f"## Sheet: {sheet.title}\n")
        if budget <= 0:
            break
        for row in sheet.iter_rows(values_only=True, max_row=budget, max_col=64):
            budget -= 1
            cells = [_cell(v) for v in row]
            if any(cells):
                writer.writerow(cells)
    if budget <= 0:
        out.write(f"[truncated after {MAX_ROWS} rows]\n")
    return out.getvalue().strip()


def extract_csv_text(data: bytes) -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


# ---------------------------------------------------------------- email body
class _HtmlText(HTMLParser):
    _BLOCK = {"p", "div", "br", "li", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol"}

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("style", "script"):
            self._skip += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")
        elif tag == "td":
            self.parts.append(" ")

    def handle_endtag(self, tag):
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def html_to_text(html: str) -> str:
    parser = _HtmlText()
    parser.feed(html)
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def clean_email_body(text: str) -> str:
    """Keep the order; drop quoted earlier mails and the signature after a sign-off.

    A sign-off only ends the body once something was kept (a mail may start with
    "Thanks"), and if the cut leaves nothing with a digit in it, the whole text is
    returned: better a longer prompt than a lost order.
    """
    text = text.replace("\r\n", "\n")
    kept: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if any(marker.search(stripped) for marker in _QUOTE_MARKERS):
            break
        if _SIGNOFFS.match(stripped) and any(k.strip() for k in kept):
            break
        kept.append(line.rstrip())
    cleaned = "\n".join(kept).strip()
    if not re.search(r"\d", cleaned):
        return text.strip()
    return cleaned


# ---------------------------------------------------------------- dispatcher
def extract_text(source_type: str, data: bytes) -> tuple[str, str]:
    """(text, method) for a source type; ValueError for anything unsupported."""
    if source_type == "pdf":
        text, method = extract_pdf_text(data)
    elif source_type == "xlsx":
        text, method = extract_xlsx_text(data), "openpyxl"
    elif source_type == "csv":
        text, method = extract_csv_text(data), "csv"
    elif source_type == "email_body":
        text, method = clean_email_body(data.decode("utf-8", errors="replace")), "email"
    else:
        raise ValueError(f"unsupported source type: {source_type}")
    return text[:MAX_CHARS], method
