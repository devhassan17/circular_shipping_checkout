# -*- coding: utf-8 -*-
"""Payment-transaction hooks for the exposure funnel (stages 3 and capture).

We hook at the model level (create / write) rather than the website_sale payment
controller. Codex's review identified PaymentPortal._validate_transaction_for_order
as the "cleanest" controller hook, but the controller method name is not verifiable
without the exact Odoo 18 build, whereas create()/write() are stable across versions
and fire for every transaction. We map a transaction to its order via sale_order_ids
(added by the sale module) and only touch orders that already have an exposure event.

    create()  → a transaction exists for the order  → STAGE 3 (proceeded to payment)
    write(state='done')                              → payment_captured = True

STAGE 4 (payment confirmed) is handled in sale_order.action_confirm, which fires for
both paid and free website orders.
"""
from odoo import api, fields, models


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    @api.model_create_multi
    def create(self, vals_list):
        txs = super().create(vals_list)
        now = fields.Datetime.now()
        for tx in txs:
            orders = tx.sale_order_ids
            if orders:
                # _cs_log_event is order-keyed and never raises into the caller.
                orders._cs_log_event(stage3_proceed_payment_ts=now)
        return txs

    def write(self, vals):
        res = super().write(vals)
        if vals.get('state') == 'done':
            for tx in self:
                orders = tx.sale_order_ids
                if orders:
                    orders._cs_log_event(payment_captured=True)
        return res
