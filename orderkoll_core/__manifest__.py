# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
{
    "name": "Orderkoll",
    "summary": "Emailed purchase orders into draft sales orders, checked and approved by a human",
    "version": "18.0.1.0.1",
    "category": "Sales",
    "author": "Maamoon Mara",
    "website": "https://maamoonmara.com",
    "license": "LGPL-3",
    "depends": ["mail", "sale_management"],
    "external_dependencies": {"python": ["pdfplumber", "pypdf", "openpyxl"]},
    "data": [
        "security/orderkoll_security.xml",
        "security/ir.model.access.csv",
        "views/inbox_views.xml",
        "views/document_views.xml",
        "views/pick_partner_views.xml",
        "views/map_sku_views.xml",
        "views/reject_views.xml",
        "views/sale_order_views.xml",
        "views/sku_map_views.xml",
        "views/res_config_settings_views.xml",
        "views/menus.xml",
        "data/cron.xml",
    ],
    "assets": {
        "web.assets_backend": ["orderkoll_core/static/src/scss/review.scss"],
    },
    "images": ["static/description/banner.png", "static/description/review_screenshot.png"],
    "installable": True,
    "application": True,
}
