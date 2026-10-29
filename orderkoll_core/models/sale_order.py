# Copyright 2026 Maamoon Mara
# License LGPL-3.0 or later (https://www.gnu.org/licenses/lgpl-3.0).
from odoo import fields, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    orderkoll_document_id = fields.Many2one(
        "orderkoll.document",
        string="Orderkoll document",
        readonly=True,
        copy=False,
        index="btree_not_null",
        help="The emailed purchase order this quotation was created from.",
    )
