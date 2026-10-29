#!/usr/bin/env python3
"""Run the synthetic corpus through a live Orderkoll instance and score it.

    ODOO_PASSWORD=... python tools/score.py --corpus tools/corpus --db orderkoll

For every document in the corpus index: create an Orderkoll document (attachment
or email body) in a dedicated inbox over XML-RPC, process it, and compare what
came back with the ground truth JSON. Prints per-layout line accuracy, header
accuracy, stop/flag correctness and latency. Documents already created by an
earlier run are re-processed, not duplicated.
"""

from __future__ import annotations

import argparse
import base64
import email
import email.policy
import json
import os
import sys
import xmlrpc.client
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


class Odoo:
    def __init__(self, url, db, user, password):
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(db, user, password, {})
        if not self.uid:
            raise SystemExit("authentication failed")
        self.db, self.password = db, password
        self.models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)

    def call(self, model, method, *args, **kwargs):
        return self.models.execute_kw(
            self.db, self.uid, self.password, model, method, list(args), kwargs
        )


def norm_code(code):
    return " ".join((code or "").split()).upper() or None


def norm_text(text):
    return " ".join((text or "").split()).casefold()


def close(a, b, tol=0.011):
    return a is not None and b is not None and abs(float(a) - float(b)) <= tol


def ensure_inbox(odoo, name):
    ids = odoo.call("orderkoll.inbox", "search", [("name", "=", name)], limit=1)
    return (
        ids[0]
        if ids
        else odoo.call("orderkoll.inbox", "create", {"name": name, "imap_enabled": False})
    )


def eml_parts(path: Path):
    msg = email.message_from_bytes(path.read_bytes(), policy=email.policy.default)
    body = msg.get_body(preferencelist=("plain",))
    return str(msg.get("Subject") or ""), (body.get_content() if body else "")


def push_document(odoo, inbox_id, corpus: Path, doc: dict) -> int:
    message_id = f"<score-{doc['doc_id']}@corpus>"
    existing = odoo.call(
        "orderkoll.document",
        "search",
        [("inbox_id", "=", inbox_id), ("email_message_id", "=", message_id)],
        limit=1,
    )
    if existing:
        return existing[0]
    source_type = "pdf" if doc["source_type"] == "scan" else doc["source_type"]
    values = {
        "inbox_id": inbox_id,
        "sender_email": doc["sender_email"],
        "sender_domain": doc["sender_email"].rsplit("@", 1)[-1],
        "email_message_id": message_id,
        "email_subject": f"corpus {doc['doc_id']}",
        "source_type": source_type if source_type != "eml" else "email_body",
    }
    if doc["source_type"] == "eml":
        subject, body = eml_parts(corpus / doc["file"])
        values.update({"email_subject": subject, "email_body": body, "source_type": "email_body"})
        return odoo.call("orderkoll.document", "create", values)
    doc_id = odoo.call("orderkoll.document", "create", values)
    data = (corpus / doc["file"]).read_bytes()
    mimetype = {
        "pdf": "application/pdf",
        "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }[source_type]
    att_id = odoo.call(
        "ir.attachment",
        "create",
        {
            "name": doc["file"],
            "raw": base64.b64encode(data).decode(),  # Odoo 20: no datas; RPC strings are base64
            "mimetype": mimetype,
            "res_model": "orderkoll.document",
            "res_id": doc_id,
        },
    )
    odoo.call("orderkoll.document", "write", [doc_id], {"attachment_id": att_id})
    return doc_id


def score_products(truth_expected_lines, truth_lines, got_lines, product_refs):
    """Per truth line: the product Orderkoll matched vs the ground truth product code.
    Returns (correct, unknown_expected, unknown_stopped)."""
    remaining = list(got_lines)
    correct = unknown_expected = unknown_stopped = 0
    for t, e in zip(truth_lines, truth_expected_lines, strict=False):
        hit = None
        for g in remaining:
            same = (
                norm_code(g["customer_code"]) == norm_code(t["customer_code"])
                if t["customer_code"]
                else norm_text(g["description"]) == norm_text(t["description"])
            )
            if same:
                hit = g
                break
        if hit is None:
            continue
        remaining.remove(hit)
        got_code = product_refs.get(hit["product_id"][0]) if hit["product_id"] else None
        if e["product_code"] is None:
            unknown_expected += 1
            if not hit["product_id"] and hit["status"] == "needs_mapping":
                unknown_stopped += 1
        elif got_code == e["product_code"]:
            correct += 1
    return correct, unknown_expected, unknown_stopped


def score_prices(truth_expected_lines, truth_lines, got_lines):
    """(flags expected, flags raised on the right lines, false flags on clean lines)."""
    remaining = list(got_lines)
    expected = caught = false_flags = 0
    for t, e in zip(truth_lines, truth_expected_lines, strict=False):
        hit = None
        for g in remaining:
            same = (
                norm_code(g["customer_code"]) == norm_code(t["customer_code"])
                if t["customer_code"]
                else norm_text(g["description"]) == norm_text(t["description"])
            )
            if same:
                hit = g
                break
        if hit is None:
            continue
        remaining.remove(hit)
        if not e["product_code"]:
            continue  # unknown products are stopped by matching, not by the price check
        if e["price_flag"]:
            expected += 1
            caught += int(not hit["price_ok"])
        elif not hit["price_ok"]:
            false_flags += 1
    return expected, caught, false_flags


def score_lines(truth_lines, got_lines):
    """Each truth line must be found once by code (or description when the PO has no
    codes) with the same quantity and unit price."""
    remaining = list(got_lines)
    correct = found = 0
    for t in truth_lines:
        match = None
        for g in remaining:
            same = (
                norm_code(g["customer_code"]) == norm_code(t["customer_code"])
                if t["customer_code"]
                else norm_text(g["description"]) == norm_text(t["description"])
            )
            if same:
                match = g
                break
        if match is None:
            continue
        remaining.remove(match)
        found += 1
        if close(match["quantity"], t["quantity"], 1e-6) and close(
            match["unit_price"], t["unit_price"]
        ):
            correct += 1
    return correct, found, len(remaining)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--corpus", default=str(HERE / "corpus"))
    ap.add_argument("--url", default=os.environ.get("ODOO_URL", "http://127.0.0.1:8069"))
    ap.add_argument("--db", default=os.environ.get("ODOO_DB", "orderkoll"))
    ap.add_argument("--user", default=os.environ.get("ODOO_USER", "admin"))
    ap.add_argument("--inbox", default="Corpus scoring")
    ap.add_argument(
        "--types", default="pdf,xlsx,eml,scan", help="comma list of source types to run"
    )
    ap.add_argument("--only", default="", help="comma list of doc ids")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", default="", help="write per-document results to this file")
    args = ap.parse_args()
    password = os.environ.get("ODOO_PASSWORD")
    if not password:
        raise SystemExit("set ODOO_PASSWORD")
    corpus = Path(args.corpus)
    index = json.loads((corpus / "index.json").read_text())
    wanted_types = set(args.types.split(","))
    only = {d for d in args.only.split(",") if d}
    docs = [
        d
        for d in index["documents"]
        if d["source_type"] in wanted_types and (not only or d["doc_id"] in only)
    ]
    if args.limit:
        docs = docs[: args.limit]

    odoo = Odoo(args.url, args.db, args.user, password)
    inbox_id = ensure_inbox(odoo, args.inbox)
    results = []
    for entry in docs:
        truth = json.loads((corpus / f"{entry['doc_id']}.json").read_text())
        doc_id = push_document(odoo, inbox_id, corpus, truth)
        odoo.call("orderkoll.document", "action_process", [doc_id])
        got = odoo.call(
            "orderkoll.document",
            "read",
            [doc_id],
            fields=[
                "state",
                "po_number",
                "document_total",
                "totals_ok",
                "extraction_ms",
                "error_message",
                "checks_log",
                "currency_id",
                "partner_id",
                "partner_resolution",
                "duplicate_of_id",
                "totals_checked",
            ],
        )[0]
        lines = odoo.call(
            "orderkoll.line",
            "search_read",
            [("document_id", "=", doc_id)],
            fields=[
                "customer_code",
                "description",
                "quantity",
                "unit_price",
                "product_id",
                "status",
                "price_ok",
                "deviation_pct",
            ],
        )
        t = truth["parsed"]
        correct, found, extra = score_lines(t["lines"], lines)
        product_ids = sorted({ln["product_id"][0] for ln in lines if ln["product_id"]})
        product_refs = (
            {
                p["id"]: p["default_code"]
                for p in odoo.call("product.product", "read", product_ids, fields=["default_code"])
            }
            if product_ids
            else {}
        )
        prod_ok, unk_exp, unk_stop = score_products(
            truth["expected"]["lines"], t["lines"], lines, product_refs
        )
        known_lines = sum(1 for e in truth["expected"]["lines"] if e["product_code"])
        pf_exp, pf_caught, pf_false = score_prices(truth["expected"]["lines"], t["lines"], lines)
        dup_expected = truth["expected"]["duplicate_of"]
        dup_got = bool(got["duplicate_of_id"])
        expected_partner = truth["expected"]["partner"]
        got_partner_ref = (
            odoo.call("res.partner", "read", [got["partner_id"][0]], fields=["ref"])[0]["ref"]
            if got["partner_id"]
            else None
        )
        partner_ok = (got_partner_ref or None) == (expected_partner or None)
        result = {
            "doc_id": entry["doc_id"],
            "type": entry["source_type"],
            "layout": entry["layout"],
            "odoo_id": doc_id,
            "state": got["state"],
            "error": got["error_message"] or "",
            "lines_truth": len(t["lines"]),
            "lines_got": len(lines),
            "lines_correct": correct,
            "lines_found": found,
            "lines_extra": extra,
            "po_ok": norm_text(got["po_number"]) == norm_text(t["po_number"]),
            "total_ok": close(got["document_total"], t["total"]),
            "currency_ok": (got["currency_id"] and got["currency_id"][1] == t["currency"])
            or (not t["currency"] and not got["currency_id"]),
            "price_flags_expected": pf_exp,
            "price_flags_caught": pf_caught,
            "price_false_flags": pf_false,
            "duplicate_expected": bool(dup_expected),
            "duplicate_flagged": dup_got,
            "totals_checked": got["totals_checked"],
            "products_correct": prod_ok,
            "products_known": known_lines,
            "unknown_expected": unk_exp,
            "unknown_stopped": unk_stop,
            "stopped": got["state"] in ("needs_review", "error"),
            "stop_expected": truth["expected"]["stop_expected"],
            "partner_expected": expected_partner,
            "partner_got": got_partner_ref,
            "partner_how": got["partner_resolution"],
            "partner_ok": partner_ok,
            "mismatch_expected": truth["expected"]["totals_mismatch"],
            "mismatch_flagged": got["state"] != "error"
            and got["totals_checked"]
            and not got["totals_ok"],
            "ms": got["extraction_ms"] or 0,
        }
        results.append(result)
        print(
            f"{entry['doc_id']:<12} {got['state']:<13} lines {correct:>2}/{len(t['lines']):<2} "
            f"po {'ok ' if result['po_ok'] else 'BAD'} "
            f"total {'ok ' if result['total_ok'] else 'BAD'} "
            f"customer {'ok ' if partner_ok else 'BAD'}({got['partner_resolution']}) "
            f"products {prod_ok}/{known_lines}"
            f"{(' unknown stopped ' + str(unk_stop) + '/' + str(unk_exp)) if unk_exp else ''} "
            f"{result['ms']:>6} ms {('ERROR: ' + result['error'][:70]) if result['error'] else ''}"
        )

    print()
    print(
        f"{'layout':<8}{'docs':>5}{'lines':>7}{'line acc':>10}{'po#':>6}{'total':>7}{'avg ms':>8}"
    )
    groups = defaultdict(list)
    for r in results:
        # scans share a layout with a text PDF; keep them apart in the table
        groups[("scan " + r["layout"]) if r["type"] == "scan" else r["layout"]].append(r)
    groups["ALL pdf"] = [r for r in results if r["type"] == "pdf"]
    groups["ALL xlsx"] = [r for r in results if r["type"] == "xlsx"]
    groups["ALL eml"] = [r for r in results if r["type"] == "eml"]
    groups["ALL scan"] = [r for r in results if r["type"] == "scan"]
    groups["ALL"] = results
    for name, rs in groups.items():
        if not rs:
            continue
        lines = sum(r["lines_truth"] for r in rs)
        correct = sum(r["lines_correct"] for r in rs)
        po = sum(r["po_ok"] for r in rs)
        total = sum(r["total_ok"] for r in rs)
        ms = sum(r["ms"] for r in rs) / len(rs)
        acc = 100 * correct / lines if lines else 0
        print(
            f"{name:<9}{len(rs):>5}{lines:>7}{acc:>9.1f}%{po:>4}/{len(rs):<2}"
            f"{total:>4}/{len(rs):<2}{ms:>8.0f}"
        )
    resolved = [r for r in results if r["partner_expected"]]
    stops = [r for r in results if not r["partner_expected"]]
    by_email = sum(r["partner_how"] == "email" for r in resolved)
    by_domain = sum(r["partner_how"] == "domain" for r in resolved)
    print(
        f"\ncustomer resolved correctly: {sum(r['partner_ok'] for r in resolved)}/{len(resolved)}"
        f" | unknown/webmail sender stopped for manual pick: {sum(r['partner_ok'] for r in stops)}"
        f"/{len(stops)} | by email {by_email}, by domain {by_domain}"
    )
    pk = sum(r["products_known"] for r in results)
    pc = sum(r["products_correct"] for r in results)
    ue = sum(r["unknown_expected"] for r in results)
    us = sum(r["unknown_stopped"] for r in results)
    docs_unknown = [r for r in results if r["unknown_expected"]]
    print(
        f"products matched correctly: {pc}/{pk} ({100 * pc / pk if pk else 0:.1f}%)"
        f" | unknown codes left unmatched: {us}/{ue}"
        f" | documents with an unknown code stopped: "
        f"{sum(r['stopped'] for r in docs_unknown)}/{len(docs_unknown)}"
    )
    pfe = sum(r["price_flags_expected"] for r in results)
    pfc = sum(r["price_flags_caught"] for r in results)
    pff = sum(r["price_false_flags"] for r in results)
    dups = [r for r in results if r["duplicate_expected"]]
    dup_false = sum(1 for r in results if r["duplicate_flagged"] and not r["duplicate_expected"])
    print(
        f"price deviations over tolerance flagged: {pfc}/{pfe} | false price flags: {pff}"
        f" | duplicate PO flagged: {sum(r['duplicate_flagged'] for r in dups)}/{len(dups)}"
        f" | false duplicates: {dup_false}"
    )
    mismatch = [r for r in results if r["mismatch_expected"]]
    if mismatch:
        caught = sum(r["mismatch_flagged"] for r in mismatch)
        print(f"totals mismatch flagged: {caught}/{len(mismatch)}")
    expected_stops = [r for r in results if r["stop_expected"]]
    clean = [r for r in results if not r["stop_expected"] and r["type"] != "scan"]
    stopped = sum(r["stopped"] for r in expected_stops)
    ready = sum(r["state"] == "ready" for r in clean)
    print(
        f"documents that must stop: {stopped}/{len(expected_stops)}"
        f" | clean documents reaching ready: {ready}/{len(clean)}"
    )
    errors = [r for r in results if r["error"]]
    if errors:
        print(f"errors: {len(errors)} documents in error state")
    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
