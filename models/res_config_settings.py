# -*- coding: utf-8 -*-
"""Settings panel proxy for Circular Shipping.

Every field is ``related='website_id.cs_*'`` (readonly=False) so the values are
stored on the persistent ``website`` record (see models/website.py). Because a
related field is only written when the saved form payload contains it, saving an
unrelated settings panel can no longer wipe CS data — the bug the old
get_values/set_values + ir.config_parameter approach suffered from.

``website_id`` is provided by the ``website`` module's res.config.settings and
defaults to the current website.
"""
from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cs_enabled = fields.Boolean(related='website_id.cs_enabled', readonly=False)

    cs_test_mode = fields.Boolean(related='website_id.cs_test_mode', readonly=False)
    boxo_api_key = fields.Char(related='website_id.boxo_api_key', readonly=False)
    boxo_api_url = fields.Char(related='website_id.boxo_api_url', readonly=False)

    cs_deposit_amount = fields.Float(related='website_id.cs_deposit_amount', readonly=False)
    cs_single_use_fee = fields.Float(related='website_id.cs_single_use_fee', readonly=False)
    cs_pricing_model = fields.Selection(related='website_id.cs_pricing_model', readonly=False)
    cs_default_selection = fields.Selection(related='website_id.cs_default_selection', readonly=False)
    cs_deposit_product_id = fields.Many2one(related='website_id.cs_deposit_product_id', readonly=False)
    cs_single_use_product_id = fields.Many2one(related='website_id.cs_single_use_product_id', readonly=False)

    cs_ab_test_enabled = fields.Boolean(related='website_id.cs_ab_test_enabled', readonly=False)
    cs_ab_split_ratio = fields.Float(related='website_id.cs_ab_split_ratio', readonly=False)

    cs_popup_text_nl = fields.Html(related='website_id.cs_popup_text_nl', readonly=False, sanitize=True)
    cs_popup_text_en = fields.Html(related='website_id.cs_popup_text_en', readonly=False, sanitize=True)
    cs_popup_text_de = fields.Html(related='website_id.cs_popup_text_de', readonly=False, sanitize=True)

    cs_explainer_reusable_nl = fields.Char(related='website_id.cs_explainer_reusable_nl', readonly=False)
    cs_explainer_reusable_en = fields.Char(related='website_id.cs_explainer_reusable_en', readonly=False)
    cs_explainer_reusable_de = fields.Char(related='website_id.cs_explainer_reusable_de', readonly=False)
    cs_explainer_single_use_nl = fields.Char(related='website_id.cs_explainer_single_use_nl', readonly=False)
    cs_explainer_single_use_en = fields.Char(related='website_id.cs_explainer_single_use_en', readonly=False)
    cs_explainer_single_use_de = fields.Char(related='website_id.cs_explainer_single_use_de', readonly=False)

    cs_allowed_country_ids = fields.Many2many(related='website_id.cs_allowed_country_ids', readonly=False)
    cs_max_products = fields.Integer(related='website_id.cs_max_products', readonly=False)

    cs_product_allow_mode = fields.Selection(related='website_id.cs_product_allow_mode', readonly=False)
    cs_excluded_product_ids = fields.Many2many(related='website_id.cs_excluded_product_ids', readonly=False)
    cs_included_product_ids = fields.Many2many(related='website_id.cs_included_product_ids', readonly=False)
    cs_required_total_qty = fields.Integer(related='website_id.cs_required_total_qty', readonly=False)

    cs_office_delivery_carrier_id = fields.Many2one(
        related='website_id.cs_office_delivery_carrier_id', readonly=False,
    )

    cs_box_image_url = fields.Char(related='website_id.cs_box_image_url', readonly=False)
    cs_dark_mode = fields.Boolean(related='website_id.cs_dark_mode', readonly=False)
