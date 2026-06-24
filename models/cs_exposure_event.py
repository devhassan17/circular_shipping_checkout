# -*- coding: utf-8 -*-
"""Checkout packaging-widget exposure / conversion funnel tracking.

One row per checkout ORDER (keyed by order_id). Records a 4-stage funnel so the
conversion rate of customers exposed to the packaging widget can be compared with
those who were not.

    STAGE 1  payment page reached      stage1_payment_page_ts
    STAGE 2  widget shown / not        widget_eligible (last value)
                                       postcode_serviceable (last value)
                                       stage2_widget_ts  (stamp-once = "ever shown")
    STAGE 3  proceeded to payment      stage3_proceed_payment_ts
    STAGE 4  payment confirmed         stage4_payment_confirmed_ts (state -> 'sale')
             payment captured          payment_captured (tx state -> 'done')

PRIVACY (data minimization): this table stores NO direct PII — no name, email,
postcode or address. Only an anonymous session hash plus non-PII order metrics.
order_id is kept for internal joins (ondelete='set null'); staff can re-identify
via the order, an accepted tradeoff. All writes happen via sudo() (the writer is
sale.order._cs_log_event). See the design doc for the full review trail.
"""
from odoo import api, fields, models


class CsExposureEvent(models.Model):
    _name = 'cs.exposure.event'
    _description = 'CS Packaging Widget Exposure Event'
    _order = 'create_date desc'

    # ── Identity / cohort (no PII) ──────────────────────────────────────────
    session_key = fields.Char(
        string='Session key', index=True, readonly=True,
        help='Anonymous SHA-256 of the web session id. Differentiates customers '
             'without storing personal data. Captured once at stage 1.',
    )
    website_id = fields.Many2one('website', string='Website', readonly=True)
    order_id = fields.Many2one(
        'sale.order', string='Order', readonly=True,
        ondelete='set null', index=True,
        help='Kept for internal joins. Set null if the cart is deleted so the '
             'event row (and abandoned-funnel data) survives.',
    )
    order_ref = fields.Char(string='Order reference', readonly=True)
    ab_variant = fields.Char(string='A/B variant', readonly=True)
    packaging_choice = fields.Selection(
        selection=[('reusable', 'Reusable'), ('single_use', 'Single use'), ('none', 'None')],
        string='Packaging choice', default='none', readonly=True,
    )
    order_total = fields.Float(string='Order total', readonly=True)
    line_count = fields.Integer(string='Product line count', readonly=True)

    # ── Funnel stage signals ────────────────────────────────────────────────
    stage1_payment_page_ts = fields.Datetime(string='1. Payment page', readonly=True)
    widget_eligible = fields.Boolean(string='Widget eligible (last value)', readonly=True)
    postcode_serviceable = fields.Boolean(string='Postcode serviceable (last value)', readonly=True)
    stage2_widget_ts = fields.Datetime(
        string='2. Widget shown', readonly=True,
        help='Stamped once the first time the widget was eligible. Not null = the '
             'widget was shown to this customer at least once.',
    )
    not_shown_reason = fields.Char(string='Not-shown reason', readonly=True)
    stage3_proceed_payment_ts = fields.Datetime(string='3. Proceeded to payment', readonly=True)
    stage4_payment_confirmed_ts = fields.Datetime(string='4. Payment confirmed', readonly=True)
    choice_ts = fields.Datetime(string='Packaging chosen at', readonly=True)
    payment_captured = fields.Boolean(string='Payment captured', readonly=True)

    # ── Derived helpers ─────────────────────────────────────────────────────
    furthest_stage = fields.Integer(
        string='Furthest stage', compute='_compute_funnel', store=True,
        help='Highest funnel stage reached (1-4).',
    )
    decision_seconds = fields.Float(
        string='Decision time (s)', compute='_compute_funnel', store=True,
        help='Seconds from widget shown (stage 2) to packaging choice.',
    )
    time_to_confirm_seconds = fields.Float(
        string='Time to confirm (s)', compute='_compute_funnel', store=True,
        help='Seconds from payment page (stage 1) to payment confirmed (stage 4).',
    )

    _sql_constraints = [
        ('order_id_uniq', 'unique(order_id)',
         'Only one exposure event per order.'),
    ]

    @api.depends('stage1_payment_page_ts', 'stage2_widget_ts', 'choice_ts',
                 'stage3_proceed_payment_ts', 'stage4_payment_confirmed_ts')
    def _compute_funnel(self):
        for rec in self:
            stage = 0
            if rec.stage1_payment_page_ts:
                stage = 1
            if rec.stage2_widget_ts:
                stage = max(stage, 2)
            if rec.stage3_proceed_payment_ts:
                stage = max(stage, 3)
            if rec.stage4_payment_confirmed_ts:
                stage = max(stage, 4)
            rec.furthest_stage = stage

            if rec.stage2_widget_ts and rec.choice_ts:
                rec.decision_seconds = (rec.choice_ts - rec.stage2_widget_ts).total_seconds()
            else:
                rec.decision_seconds = 0.0

            if rec.stage1_payment_page_ts and rec.stage4_payment_confirmed_ts:
                rec.time_to_confirm_seconds = (
                    rec.stage4_payment_confirmed_ts - rec.stage1_payment_page_ts
                ).total_seconds()
            else:
                rec.time_to_confirm_seconds = 0.0
