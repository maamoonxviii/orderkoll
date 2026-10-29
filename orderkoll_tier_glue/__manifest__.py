# Copyright 2026 Maamoon Mara
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Orderkoll Tier Glue",
    "summary": "Checked purchase orders become quotations that wait for OCA tier validation",
    "version": "19.0.1.0.0",
    "category": "Sales",
    "author": "Maamoon Mara",
    "website": "https://maamoonmara.com",
    "license": "AGPL-3",
    "depends": ["orderkoll_core", "sale_tier_validation"],
    "data": [
        "security/ir.model.access.csv",
        "views/inbox_views.xml",
    ],
    # OCA base_tier_validation / sale_tier_validation have no 19.0 release yet (2026-10-26):
    # installable again once they do.
    "installable": False,
    "auto_install": False,
}
