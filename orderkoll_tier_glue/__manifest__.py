# Copyright 2026 Maamoon Mara
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Orderkoll Tier Glue",
    "summary": "Checked purchase orders become quotations that wait for OCA tier validation",
    "version": "18.0.1.0.0",
    "category": "Sales",
    "author": "Maamoon Mara",
    "website": "https://maamoonmara.com",
    "license": "AGPL-3",
    "depends": ["orderkoll_core", "sale_tier_validation"],
    "data": [
        "security/ir.model.access.csv",
        "views/inbox_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
