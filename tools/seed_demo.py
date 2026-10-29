#!/usr/bin/env python3
"""Seed a demo database with the synthetic catalogue over XML-RPC.

    ODOO_PASSWORD=... python tools/seed_demo.py --db orderkoll

Creates (idempotently): active currencies with fixed rates, 8 partner companies
with contacts, one percentage pricelist per partner, 200 products with internal
reference and barcode. If the orderkoll.sku_map model exists, the customer code
map is loaded too; otherwise it is skipped and reported.

Environment: ODOO_URL (default http://127.0.0.1:8069), ODOO_DB (default orderkoll),
ODOO_USER (default admin), ODOO_PASSWORD (required).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import xmlrpc.client
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import demo_data  # noqa: E402

log = logging.getLogger("seed_demo")
WEBMAIL = {"gmail.com", "outlook.com", "hotmail.com", "yahoo.com", "icloud.com", "live.com"}


class Odoo:
    def __init__(self, url: str, db: str, user: str, password: str):
        common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common", allow_none=True)
        self.uid = common.authenticate(db, user, password, {})
        if not self.uid:
            raise SystemExit("authentication failed")
        self.db, self.password = db, password
        self.models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object", allow_none=True)

    def call(self, model: str, method: str, *args, **kwargs):
        return self.models.execute_kw(
            self.db, self.uid, self.password, model, method, list(args), kwargs
        )

    def search(self, model: str, domain: list, **kwargs) -> list[int]:
        return self.call(model, "search", domain, **kwargs)

    def ensure(self, model: str, domain: list, values: dict) -> int:
        """Return the id of the record matching domain, creating it if absent."""
        ids = self.search(model, domain, limit=1)
        if ids:
            self.call(model, "write", ids, values)
            return ids[0]
        return self.call(model, "create", values)

    def model_exists(self, model: str) -> bool:
        return bool(self.search("ir.model", [("model", "=", model)], limit=1))


def seed_currencies(odoo: Odoo, catalog: dict) -> dict[str, int]:
    ids = {}
    for code, rate in catalog["currency_rates"].items():
        cur = odoo.search(
            "res.currency", [("name", "=", code), ("active", "in", [True, False])], limit=1
        )
        if not cur:
            raise SystemExit(f"currency {code} missing in Odoo")
        odoo.call("res.currency", "write", cur, {"active": True})
        ids[code] = cur[0]
        if code != catalog["company"]["currency"]:
            odoo.ensure(
                "res.currency.rate",
                [("currency_id", "=", cur[0]), ("name", "=", "2026-01-01")],
                {"currency_id": cur[0], "name": "2026-01-01", "rate": rate},
            )
    log.info("currencies: %s", ", ".join(ids))
    return ids


def seed_pricelist(odoo: Odoo, partner: dict, currency_ids: dict) -> int:
    name = f"{partner['name']} pricelist"
    pl_id = odoo.ensure(
        "product.pricelist",
        [("name", "=", name)],
        {"name": name, "currency_id": currency_ids[partner["currency"]]},
    )
    odoo.ensure(
        "product.pricelist.item",
        [("pricelist_id", "=", pl_id), ("applied_on", "=", "3_global")],
        {
            "pricelist_id": pl_id,
            "applied_on": "3_global",
            "compute_price": "percentage",
            "percent_price": partner["pricelist_discount"],
        },
    )
    return pl_id


def seed_partners(odoo: Odoo, catalog: dict, currency_ids: dict) -> dict[str, int]:
    ids = {}
    for partner in catalog["partners"]:
        country = odoo.search("res.country", [("code", "=", partner["country"])], limit=1)
        pl_id = seed_pricelist(odoo, partner, currency_ids)
        values = {
            "name": partner["name"],
            "is_company": True,
            "website": f"https://www.{partner['domain']}",
            "email": "info@" + partner["domain"],
            "street": partner["street"],
            "zip": partner["zip"],
            "city": partner["city"],
            "country_id": country[0] if country else False,
            "vat": partner["vat"] or False,
            "property_product_pricelist": pl_id,
            "ref": partner["key"],
        }
        pid = odoo.ensure(
            "res.partner", [("ref", "=", partner["key"]), ("is_company", "=", True)], values
        )
        ids[partner["key"]] = pid
        for contact in partner["contacts"]:
            if contact["email"].rsplit("@", 1)[-1] in WEBMAIL:
                continue  # a webmail sender must stay unknown: it is the manual-pick trap
            odoo.ensure(
                "res.partner",
                [("email", "=", contact["email"])],
                {
                    "name": contact["name"],
                    "email": contact["email"],
                    "parent_id": pid,
                    "type": "contact",
                },
            )
    log.info("partners: %d", len(ids))
    return ids


def seed_products(odoo: Odoo, catalog: dict) -> dict[str, int]:
    uoms = {}
    for name in {p["uom"] for p in catalog["products"]}:
        uom = odoo.search("uom.uom", [("name", "=", name)], limit=1)
        if not uom:
            # Odoo ships Units, Pack, kg, m; "Box" may be missing in a bare install.
            if odoo.search("ir.model", [("model", "=", "uom.category")], limit=1):  # Odoo 18
                category = odoo.search("uom.category", [("name", "=", "Unit")], limit=1)
                values = {"category_id": category[0], "uom_type": "bigger", "factor_inv": 1.0}
            else:  # Odoo 19: no categories; a unit is defined relative to another
                units = odoo.search("uom.uom", [("name", "=", "Units")], limit=1)
                values = {"relative_uom_id": units[0], "relative_factor": 1.0}
            uom = [odoo.call("uom.uom", "create", {"name": name, **values})]
        uoms[name] = uom[0]
    categories = {}
    for cat in {p["category"] for p in catalog["products"]}:
        categories[cat] = odoo.ensure("product.category", [("name", "=", cat)], {"name": cat})
    ids = {}
    for product in catalog["products"]:
        values = {
            "name": product["name"],
            "default_code": product["default_code"],
            "barcode": product["barcode"],
            "list_price": product["list_price"],
            "type": "consu",
            "sale_ok": True,
            "purchase_ok": False,
            "categ_id": categories[product["category"]],
            "uom_id": uoms[product["uom"]],
        }
        ids[product["default_code"]] = odoo.ensure(
            "product.product", [("default_code", "=", product["default_code"])], values
        )
    log.info("products: %d", len(ids))
    return ids


def seed_sku_map(odoo: Odoo, catalog: dict, partner_ids: dict, product_ids: dict) -> int:
    if not odoo.model_exists("orderkoll.sku_map"):
        log.warning("orderkoll.sku_map not installed; SKU map skipped")
        return 0
    n = 0
    for row in catalog["sku_map"]:
        odoo.ensure(
            "orderkoll.sku_map",
            [
                ("partner_id", "=", partner_ids[row["partner"]]),
                ("customer_code", "=", row["customer_code"]),
            ],
            {
                "partner_id": partner_ids[row["partner"]],
                "customer_code": row["customer_code"],
                "product_id": product_ids[row["product_code"]],
            },
        )
        n += 1
    log.info("sku map rows: %d", n)
    return n


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--url", default=os.environ.get("ODOO_URL", "http://127.0.0.1:8069"))
    ap.add_argument("--db", default=os.environ.get("ODOO_DB", "orderkoll"))
    ap.add_argument("--user", default=os.environ.get("ODOO_USER", "admin"))
    ap.add_argument("--dry-run", action="store_true", help="print what would be seeded")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    catalog = demo_data.build_catalog()
    if args.dry_run:
        print(
            f"{len(catalog['partners'])} partners, {len(catalog['products'])} products, "
            f"{len(catalog['sku_map'])} sku map rows, currencies {list(catalog['currency_rates'])}"
        )
        return
    password = os.environ.get("ODOO_PASSWORD")
    if not password:
        raise SystemExit("set ODOO_PASSWORD")
    odoo = Odoo(args.url, args.db, args.user, password)
    currency_ids = seed_currencies(odoo, catalog)
    partner_ids = seed_partners(odoo, catalog, currency_ids)
    product_ids = seed_products(odoo, catalog)
    seed_sku_map(odoo, catalog, partner_ids, product_ids)
    print(f"seeded {args.db}: {len(partner_ids)} partners, {len(product_ids)} products")


if __name__ == "__main__":
    main()
