"""Invariants of the synthetic catalogue and test corpus."""

import json
import sys
from pathlib import Path

import pdfplumber
import pytest

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))

import demo_data  # noqa: E402
import gen_corpus  # noqa: E402


@pytest.fixture(scope="session")
def catalog():
    return demo_data.build_catalog()


@pytest.fixture(scope="session")
def corpus(tmp_path_factory):
    out = tmp_path_factory.mktemp("corpus")
    docs = gen_corpus.generate(out)
    return out, docs


def test_catalog_shape(catalog):
    assert len(catalog["partners"]) == 8
    assert len(catalog["products"]) == 200
    codes = [p["default_code"] for p in catalog["products"]]
    barcodes = [p["barcode"] for p in catalog["products"]]
    assert len(set(codes)) == 200
    assert len(set(barcodes)) == 200
    for b in barcodes:
        assert len(b) == 13 and demo_data.ean13_check_digit(b[:12]) == b[-1]
    for partner in catalog["partners"]:
        assert partner["pricelist_discount"] > 0
        assert all("@" in c["email"] for c in partner["contacts"])
    gmail = [
        c for p in catalog["partners"] for c in p["contacts"] if c["email"].endswith("@gmail.com")
    ]
    assert len(gmail) == 1, "one webmail contact for the ignored-domain trap"


def test_sku_map_refers_to_real_products(catalog):
    codes = {p["default_code"] for p in catalog["products"]}
    keys = {p["key"] for p in catalog["partners"]}
    pairs = set()
    for m in catalog["sku_map"]:
        assert m["product_code"] in codes
        assert m["partner"] in keys
        pairs.add((m["partner"], m["customer_code"]))
    assert len(pairs) == len(catalog["sku_map"]), "unique (partner, customer_code)"


def test_corpus_counts(corpus):
    out, docs = corpus
    by_type = {}
    for d in docs:
        by_type.setdefault(d["source_type"], []).append(d)
    assert len(by_type["pdf"]) == 30
    assert len({d["layout"] for d in by_type["pdf"]}) == 10
    assert len(by_type["xlsx"]) == 5
    assert len(by_type["eml"]) == 5
    assert len(by_type["scan"]) == 5
    for d in docs:
        assert (out / d["file"]).is_file(), d["file"]
        assert (out / f"{d['doc_id']}.json").is_file()
    assert json.loads((out / "index.json").read_text())["count"] == 45
    assert (out / "catalog.json").is_file()


def test_totals_arithmetic(corpus):
    _, docs = corpus
    mismatches = []
    for d in docs:
        parsed = d["parsed"]
        lines_total = round(sum(ln["line_total"] for ln in parsed["lines"]), 2)
        assert abs(lines_total - parsed["subtotal"]) < 0.011, d["doc_id"]
        if d["expected"]["totals_mismatch"]:
            mismatches.append(d["doc_id"])
            gap = abs(parsed["subtotal"] + parsed["tax"] - parsed["total"])
            assert gap > max(parsed["total"] * 0.005, 1.0) * 2, "must exceed the tolerance clearly"
        else:
            assert abs(parsed["subtotal"] + parsed["tax"] - parsed["total"]) < 0.011
    assert len(mismatches) == 1


def test_traps_present(corpus):
    _, docs = corpus
    unknown_docs = [d for d in docs if d["expected"]["unknown_codes"] > 0]
    price_docs = [d for d in docs if d["expected"]["price_flags"] > 0]
    dup_docs = [d for d in docs if d["expected"]["duplicate_of"]]
    no_partner = [d for d in docs if d["expected"]["partner"] is None]
    assert len(unknown_docs) >= 3
    assert len(price_docs) >= 3
    assert len(dup_docs) == 1
    assert len(no_partner) == 1 and no_partner[0]["source_type"] == "eml"
    by_id = {d["doc_id"]: d for d in docs}
    dup, orig = dup_docs[0], by_id[dup_docs[0]["expected"]["duplicate_of"]]
    assert dup["expected"]["stop_expected"] and not orig["expected"]["stop_expected"]
    assert dup["parsed"]["po_number"] == orig["parsed"]["po_number"]
    assert dup["expected"]["partner"] == orig["expected"]["partner"]
    for d in price_docs:
        flagged = [ln for ln in d["expected"]["lines"] if ln["price_flag"]]
        assert all(abs(ln["deviation_pct"]) > 2.0 for ln in flagged)
    within = [
        ln
        for d in docs
        for ln in d["expected"]["lines"]
        if ln["deviation_pct"] and 0 < abs(ln["deviation_pct"]) <= 2.0
    ]
    assert within, "at least one deviation inside the 2% tolerance"
    assert all(not ln["price_flag"] for ln in within)


def test_every_line_is_resolvable_or_unknown(corpus, catalog):
    _, docs = corpus
    codes = {p["default_code"] for p in catalog["products"]}
    for d in docs:
        for ln in d["expected"]["lines"]:
            if ln["match_method"] == "none":
                assert ln["product_code"] is None
            else:
                assert ln["product_code"] in codes
                assert ln["match_method"] in {"sku_map", "default_code", "fuzzy"}


def test_text_pdfs_have_text_and_scans_do_not(corpus):
    out, docs = corpus
    for d in docs:
        if d["source_type"] not in {"pdf", "scan"}:
            continue
        with pdfplumber.open(out / d["file"]) as pdf:
            text = "\n".join((p.extract_text() or "") for p in pdf.pages)
            pages = len(pdf.pages)
        if d["source_type"] == "pdf":
            assert d["parsed"]["po_number"] in text, d["doc_id"]
            if d["layout"] == "L07":
                assert pages >= 2, "L07 is the multi-page layout"
        else:
            assert text.strip() == "", d["doc_id"]


def test_xlsx_and_eml_carry_the_order(corpus):
    import email
    from email import policy

    import openpyxl

    out, docs = corpus
    for d in docs:
        if d["source_type"] == "xlsx":
            wb = openpyxl.load_workbook(out / d["file"], read_only=True)
            cells = [
                str(c)
                for ws in wb.worksheets
                for row in ws.iter_rows(values_only=True)
                for c in row
                if c is not None
            ]
            assert d["parsed"]["po_number"] in " ".join(cells), d["doc_id"]
        if d["source_type"] == "eml":
            msg = email.message_from_bytes((out / d["file"]).read_bytes(), policy=policy.default)
            assert d["sender_email"] in msg["From"]
            body = msg.get_body(preferencelist=("plain",)).get_content()
            assert d["parsed"]["po_number"] in body
