# -*- coding: utf-8 -*-
from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    is_cs_packaging = fields.Boolean(
        string='Circular Shipping Packaging Line',
        default=False,
        help='Marks a deposit or surcharge line added by the CS widget (shown in totals, not cart).',
    )
    is_cs_box = fields.Boolean(
        string='Circular Shipping Box Line',
        default=False,
        help='Marks the free CSC box product line shown in the cart items list.',
    )

    def _show_in_cart(self):
        """Exclude deposit/surcharge lines from cart items; keep the CSC box line visible."""
        return super()._show_in_cart() and not self.is_cs_packaging
