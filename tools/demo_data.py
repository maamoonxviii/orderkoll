"""Deterministic synthetic catalogue shared by gen_corpus.py and seed_demo.py.

Everything here is invented. No real company, person, product or price.
The same seed always yields the same catalogue, so corpus documents and the
seeded Odoo database agree on codes, barcodes and pricelist prices.
"""

from __future__ import annotations

import random

SEED = 20261022

COMPANY = {
    "name": "Orderkoll Demo Supplier AB",
    "email": "orders@orderkoll-demo.example",
    "street": "Industrivägen 14",
    "zip": "417 05",
    "city": "Göteborg",
    "country": "SE",
    "vat": "SE559900123401",
    "currency": "USD",
}

# All domains use the reserved .example TLD (RFC 2606): nothing here can reach a real host.
# Units of the currency per 1 USD (company currency). Fixed so prices are predictable.
CURRENCY_RATES = {"USD": 1.0, "EUR": 0.92, "SEK": 10.50, "GBP": 0.78}
VAT_RATES = {"SE": 0.25, "DE": 0.19, "GB": 0.20, "US": 0.0, "NL": 0.21, "DK": 0.25}

# numbers: how the partner writes amounts — us 1,234.56 · eu 1.234,56 · se 1 234,56
PARTNERS = [
    {
        "key": "nordic_fasteners",
        "name": "Nordic Fasteners AB",
        "domain": "nordicfasteners.example",
        "country": "SE",
        "street": "Fabriksgatan 3",
        "zip": "503 38",
        "city": "Borås",
        "vat": "SE556677889901",
        "currency": "SEK",
        "pricelist_discount": 12.0,
        "own_codes": "NF",
        "numbers": "se",
        "po_style": "PO-{y}-{n:05d}",
        "contacts": [("Anna Lind", "anna.lind"), ("Inköp", "inkop")],
    },
    {
        "key": "harbor_supply",
        "name": "Harbor Supply Co.",
        "domain": "harborsupply.example",
        "country": "US",
        "street": "1200 Port Road",
        "zip": "98421",
        "city": "Tacoma, WA",
        "vat": "",
        "currency": "USD",
        "pricelist_discount": 8.0,
        "own_codes": "HS",
        "numbers": "us",
        "po_style": "HS{n:06d}",
        "contacts": [("Mike Rowan", "mike.rowan"), ("Purchasing", "purchasing")],
    },
    {
        "key": "rheinwerk",
        "name": "Rheinwerk Technik GmbH",
        "domain": "rheinwerk-technik.example",
        "country": "DE",
        "street": "Hafenstraße 22",
        "zip": "47119",
        "city": "Duisburg",
        "vat": "DE811223344",
        "currency": "EUR",
        "pricelist_discount": 10.0,
        "own_codes": None,
        "numbers": "eu",
        "po_style": "45{n:08d}",
        "contacts": [("Katrin Vogel", "k.vogel"), ("Einkauf", "einkauf")],
    },
    {
        "key": "albion_tools",
        "name": "Albion Tools Ltd",
        "domain": "albiontools.example",
        "country": "GB",
        "street": "14 Foundry Lane",
        "zip": "S9 3TY",
        "city": "Sheffield",
        "vat": "GB123456789",
        "currency": "GBP",
        "pricelist_discount": 5.0,
        "own_codes": "AT",
        "numbers": "us",
        "po_style": "AT/{y}/{n:04d}",
        "contacts": [("James Hartley", "j.hartley"), ("Orders", "orders")],
    },
    {
        "key": "midwest_distribution",
        "name": "Midwest Distribution LLC",
        "domain": "midwestdist.example",
        "country": "US",
        "street": "4800 Commerce Drive",
        "zip": "60446",
        "city": "Romeoville, IL",
        "vat": "",
        "currency": "USD",
        "pricelist_discount": 15.0,
        "own_codes": None,
        "numbers": "us",
        "po_style": "MD-{n:07d}",
        "contacts": [("Sarah Kim", "skim"), ("Accounts Payable", "ap")],
    },
    {
        "key": "van_der_berg",
        "name": "Van der Berg Groothandel BV",
        "domain": "vdb-groothandel.example",
        "country": "NL",
        "street": "Havenweg 8",
        "zip": "3089 JH",
        "city": "Rotterdam",
        "vat": "NL001234567B01",
        "currency": "EUR",
        "pricelist_discount": 7.5,
        "own_codes": "VDB",
        "numbers": "eu",
        "po_style": "IO{y}{n:05d}",
        "contacts": [("Pieter de Vries", "p.devries"), ("Inkoop", "inkoop")],
    },
    {
        "key": "kobenhavn_el",
        "name": "København El-Engros ApS",
        "domain": "kbh-elengros.example",
        "country": "DK",
        "street": "Refshalevej 110",
        "zip": "1432",
        "city": "København K",
        "vat": "DK12345678",
        "currency": "EUR",
        "pricelist_discount": 9.0,
        "own_codes": None,
        "numbers": "eu",
        "po_style": "KE-{n:06d}",
        "contacts": [("Mads Jensen", "mj"), ("Ordre", "ordre")],
    },
    {
        "key": "lakeside_industrial",
        "name": "Lakeside Industrial Supply",
        "domain": "lakesideindustrial.example",
        "country": "US",
        "street": "77 Harbor View Blvd",
        "zip": "53204",
        "city": "Milwaukee, WI",
        "vat": "",
        "currency": "USD",
        "pricelist_discount": 6.0,
        "own_codes": "LK",
        "numbers": "us",
        "po_style": "LKS-{y}-{n:04d}",
        "contacts": [
            ("Dana Whitfield", "dana.whitfield"),
            ("Orders", "orders"),
            # Personal webmail address: the ignored-domain trap (manual pick).
            ("Dana Whitfield", "dana.whitfield.orders", "gmail.com"),
        ],
    },
]

# (category, base names, size variants, finish variants, uom, price range USD)
PRODUCT_FAMILIES = [
    (
        "Fasteners",
        ["Hex bolt", "Hex nut", "Flat washer", "Socket cap screw", "Threaded rod"],
        ["M5", "M6", "M8", "M10", "M12", "M16"],
        ["zinc", "A2 stainless", "A4 stainless", "black oxide"],
        "Units",
        (0.08, 6.5),
    ),
    (
        "Pipes & fittings",
        ["PVC pipe", "PP elbow 90°", "Ball valve", "Hose clamp", "Pipe coupling"],
        ["20 mm", "25 mm", "32 mm", "40 mm", "50 mm"],
        ["PN10", "PN16", "grey", "white"],
        "Units",
        (0.9, 48.0),
    ),
    (
        "Electrical",
        ["Installation cable", "Cable tie", "Junction box", "Circuit breaker", "Cable gland"],
        ["3G1.5", "3G2.5", "5G1.5", "M20", "16 A", "25 A"],
        ["grey", "black", "halogen-free", "IP65"],
        "m",
        (0.4, 85.0),
    ),
    (
        "Packaging",
        ["Stretch film", "Corrugated box", "Packing tape", "Pallet wrap", "Bubble wrap"],
        ["300 mm", "400 mm", "500 mm", "600 mm", "1200 mm"],
        ["clear", "black", "23 µm", "17 µm"],
        "Pack",
        (3.5, 120.0),
    ),
    (
        "Tools & abrasives",
        ["Torx bit", "Cutting disc", "Flap disc", "Drill bit HSS", "Work gloves"],
        ["T20", "T25", "T30", "115 mm", "125 mm", "8 mm", "10 mm", "size 9", "size 10"],
        ["grade 40", "grade 60", "cobalt", "nitrile", "pro"],
        "Box",
        (1.2, 450.0),
    ),
]


def ean13_check_digit(first12: str) -> str:
    total = sum(int(d) * (3 if i % 2 else 1) for i, d in enumerate(first12))
    return str((10 - total % 10) % 10)


def _products(rng: random.Random) -> list[dict]:
    products = []
    seen_names = set()
    per_family = 200 // len(PRODUCT_FAMILIES)
    idx = 0
    for cat, bases, sizes, finishes, uom, (lo, hi) in PRODUCT_FAMILIES:
        made = 0
        while made < per_family:
            name = f"{rng.choice(bases)} {rng.choice(sizes)} {rng.choice(finishes)}"
            if name in seen_names:
                continue
            seen_names.add(name)
            idx += 1
            code = f"OK-{1000 + idx:04d}"
            first12 = f"73{idx:010d}"
            price = round(rng.uniform(lo, hi), 2)
            products.append(
                {
                    "default_code": code,
                    "barcode": first12 + ean13_check_digit(first12),
                    "name": name,
                    "category": cat,
                    "uom": uom,
                    "list_price": price,
                }
            )
            made += 1
    return products


def _contacts(partner: dict) -> list[dict]:
    out = []
    for entry in partner["contacts"]:
        name, local = entry[0], entry[1]
        domain = entry[2] if len(entry) > 2 else partner["domain"]
        out.append({"name": name, "email": f"{local}@{domain}"})
    return out


def _sku_map(rng: random.Random, partners: list[dict], products: list[dict]) -> list[dict]:
    """Customer-specific codes for ~45 products per partner that uses its own codes."""
    rows = []
    for partner in partners:
        prefix = partner["own_codes"]
        if not prefix:
            continue
        chosen = rng.sample(products, 45)
        used = set()
        for product in chosen:
            while True:
                code = f"{prefix}-{rng.randint(10000, 99999)}"
                if code not in used:
                    used.add(code)
                    break
            rows.append(
                {
                    "partner": partner["key"],
                    "customer_code": code,
                    "product_code": product["default_code"],
                }
            )
    return rows


def pricelist_price(product: dict, partner: dict) -> float:
    """What Odoo's pricelist should return: list price in the partner's currency
    minus the partner's percentage discount, rounded to cents."""
    rate = CURRENCY_RATES[partner["currency"]]
    price = product["list_price"] * rate * (1 - partner["pricelist_discount"] / 100)
    return round(price, 2)


def build_catalog(seed: int = SEED) -> dict:
    rng = random.Random(seed)
    products = _products(rng)
    partners = []
    for p in PARTNERS:
        partner = {k: v for k, v in p.items() if k != "contacts"}
        partner["contacts"] = _contacts(p)
        partner["vat_rate"] = VAT_RATES[p["country"]]
        partners.append(partner)
    return {
        "seed": seed,
        "company": COMPANY,
        "currency_rates": CURRENCY_RATES,
        "partners": partners,
        "products": products,
        "sku_map": _sku_map(rng, partners, products),
    }
