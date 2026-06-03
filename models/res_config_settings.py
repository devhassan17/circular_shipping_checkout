# -*- coding: utf-8 -*-
"""Settings UI proxies.

All values are stored on the persistent `website` model (see website.py).
Every field below is `related='website_id.<field>'` so saving an unrelated
Odoo settings panel cannot clear them — Odoo only writes a `related` field
when it is explicitly present in the saved form payload.
"""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # ── Plugin master switch ────────────────────────────────────────────────
    cs_enabled = fields.Boolean(related='website_id.cs_enabled', readonly=False)

    # ── BOXO API integration ────────────────────────────────────────────────
    cs_test_mode = fields.Boolean(related='website_id.cs_test_mode', readonly=False)
    boxo_api_key = fields.Char(related='website_id.boxo_api_key', readonly=False)
    boxo_api_url = fields.Char(related='website_id.boxo_api_url', readonly=False)

    # ── Pricing ─────────────────────────────────────────────────────────────
    cs_deposit_amount = fields.Float(related='website_id.cs_deposit_amount', readonly=False)
    cs_single_use_fee = fields.Float(related='website_id.cs_single_use_fee', readonly=False)
    cs_pricing_model = fields.Selection(related='website_id.cs_pricing_model', readonly=False)
    cs_default_selection = fields.Selection(related='website_id.cs_default_selection', readonly=False)

    # ── A/B testing ─────────────────────────────────────────────────────────
    cs_ab_test_enabled = fields.Boolean(related='website_id.cs_ab_test_enabled', readonly=False)
    cs_ab_split_ratio = fields.Float(related='website_id.cs_ab_split_ratio', readonly=False)

    # ── Popup copy ──────────────────────────────────────────────────────────
    cs_popup_text_nl = fields.Html(related='website_id.cs_popup_text_nl', readonly=False, sanitize=True)
    cs_popup_text_en = fields.Html(related='website_id.cs_popup_text_en', readonly=False, sanitize=True)
    cs_popup_text_de = fields.Html(related='website_id.cs_popup_text_de', readonly=False, sanitize=True)

    cs_explainer_reusable_nl = fields.Char(related='website_id.cs_explainer_reusable_nl', readonly=False)
    cs_explainer_reusable_en = fields.Char(related='website_id.cs_explainer_reusable_en', readonly=False)
    cs_explainer_reusable_de = fields.Char(related='website_id.cs_explainer_reusable_de', readonly=False)
    cs_explainer_single_use_nl = fields.Char(related='website_id.cs_explainer_single_use_nl', readonly=False)
    cs_explainer_single_use_en = fields.Char(related='website_id.cs_explainer_single_use_en', readonly=False)
    cs_explainer_single_use_de = fields.Char(related='website_id.cs_explainer_single_use_de', readonly=False)

    # ── Geographic and quantity eligibility ─────────────────────────────────
    cs_allowed_country_ids = fields.Many2many(related='website_id.cs_allowed_country_ids', readonly=False)
    cs_max_products = fields.Integer(related='website_id.cs_max_products', readonly=False)

    # ── Product filter ──────────────────────────────────────────────────────
    cs_product_allow_mode = fields.Selection(related='website_id.cs_product_allow_mode', readonly=False)
    cs_excluded_product_ids = fields.Many2many(related='website_id.cs_excluded_product_ids', readonly=False)
    cs_included_product_ids = fields.Many2many(related='website_id.cs_included_product_ids', readonly=False)
    cs_required_total_qty = fields.Integer(related='website_id.cs_required_total_qty', readonly=False)

    # ── Delivery carrier swap ───────────────────────────────────────────────
    cs_office_delivery_carrier_id = fields.Many2one(related='website_id.cs_office_delivery_carrier_id', readonly=False)

    # ── CSC box thumbnail and contrast styling ──────────────────────────────
    cs_box_image_url = fields.Char(related='website_id.cs_box_image_url', readonly=False)
    cs_dark_mode = fields.Boolean(related='website_id.cs_dark_mode', readonly=False)
