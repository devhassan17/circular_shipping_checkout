# -*- coding: utf-8 -*-
import base64
import logging

import requests as _requests
from markupsafe import Markup
from odoo import models, fields

_logger = logging.getLogger(__name__)


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    cs_enabled = fields.Boolean(
        string='Circular Shipping ingeschakeld',
        default=True,
    )
    cs_test_mode = fields.Boolean(
        string='Testmodus',
        config_parameter='cs.test_mode',
    )
    # API key for the BOXO external service — BOXO name is intentional here
    boxo_api_key = fields.Char(
        string='BOXO API-sleutel',
        config_parameter='boxo.api_key',
    )
    boxo_api_url = fields.Char(
        string='BOXO API URL',
        config_parameter='boxo.api_url',
    )
    cs_deposit_amount = fields.Float(
        string='Borg herbruikbaar (EUR)',
        config_parameter='cs.deposit_amount',
        default=3.95,
    )
    cs_single_use_fee = fields.Float(
        string='Toeslag wegwerp (EUR)',
        config_parameter='cs.single_use_fee',
        default=0.25,
    )
    cs_default_selection = fields.Selection(
        selection=[('reusable', 'Statiegeld verpakking'), ('single_use', 'Wegwerpverpakking')],
        string='Standaard selectie',
        config_parameter='cs.default_selection',
        default='single_use',
    )
    cs_pricing_model = fields.Selection(
        selection=[('direct', 'Direct'), ('via_shipping', 'Via verzendkosten')],
        string='Prijsmodel',
        config_parameter='cs.pricing_model',
        default='direct',
    )
    cs_ab_test_enabled = fields.Boolean(
        string='A/B test ingeschakeld',
        config_parameter='cs.ab_test_enabled',
    )
    cs_ab_split_ratio = fields.Float(
        string='A/B split ratio (0–1)',
        config_parameter='cs.ab_split_ratio',
        default=0.5,
    )
    cs_popup_text_nl = fields.Html(
        string='Info popup tekst — NL',
        sanitize=True,
    )
    cs_popup_text_en = fields.Html(
        string='Info popup tekst — EN',
        sanitize=True,
    )
    cs_popup_text_de = fields.Html(
        string='Info popup tekst — DE',
        sanitize=True,
    )

    cs_explainer_reusable_nl = fields.Char(
        string='Uitleg statiegeld — NL',
        config_parameter='cs.explainer_reusable.nl',
    )
    cs_explainer_reusable_en = fields.Char(
        string='Explainer deposit — EN',
        config_parameter='cs.explainer_reusable.en',
    )
    cs_explainer_reusable_de = fields.Char(
        string='Erklärung Pfand — DE',
        config_parameter='cs.explainer_reusable.de',
    )
    cs_explainer_single_use_nl = fields.Char(
        string='Uitleg wegwerp — NL',
        config_parameter='cs.explainer_single_use.nl',
    )
    cs_explainer_single_use_en = fields.Char(
        string='Explainer single-use — EN',
        config_parameter='cs.explainer_single_use.en',
    )
    cs_explainer_single_use_de = fields.Char(
        string='Erklärung Einweg — DE',
        config_parameter='cs.explainer_single_use.de',
    )

    cs_allowed_country_ids = fields.Many2many(
        'res.country',
        'cs_config_allowed_countries_rel',
        'setting_id',
        'country_id',
        string='Toegestane landen',
        help='Landen waar de CS widget getoond wordt. Leeg = alle landen.',
    )
    cs_max_products = fields.Integer(
        string='Maximum aantal producten',
        config_parameter='cs.max_products',
        default=0,
        help='Maximum aantal producten voor herbruikbare verpakking. 0 = geen limiet.',
    )

    # Product filter — three-mode system (all / exclude / include)
    cs_product_allow_mode = fields.Selection(
        selection=[
            ('all', 'Alle producten toegestaan'),
            ('exclude', 'Alle behalve geselecteerde producten'),
            ('include', 'Alleen geselecteerde producten'),
        ],
        string='Productfilter modus',
        config_parameter='cs.product_allow_mode',
        default='include',
    )
    cs_excluded_product_ids = fields.Many2many(
        'product.product',
        'cs_config_excluded_products_rel',
        'setting_id',
        'product_id',
        string='Uitgesloten producten',
        help='Producten waarvoor de CS widget niet getoond wordt.',
    )
    cs_included_product_ids = fields.Many2many(
        'product.product',
        'cs_config_included_products_rel',
        'setting_id',
        'product_id',
        string='Toegestane producten',
        help='Alleen voor deze producten wordt de CS widget getoond.',
    )
    cs_office_delivery_carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Bezorgmethode (statiegeld)',
        help='Bezorgmethode die automatisch wordt geselecteerd wanneer de klant Statiegeld verpakking kiest.',
    )

    cs_required_total_qty = fields.Integer(
        string='Vereist aantal',
        config_parameter='cs.required_total_qty',
        default=0,
        help='Totaal aantal stuks van de toegestane producten dat exact in de bestelling aanwezig moet zijn. 0 = CS widget nooit actief (standaard bij eerste installatie).',
    )

    cs_box_image_url = fields.Char(
        string='CSC Box afbeelding URL',
        config_parameter='cs.box_image_url',
    )
    cs_dark_mode = fields.Boolean(
        string='Contrast mode widget',
        config_parameter='cs.dark_mode',
    )

    def get_values(self) -> dict:
        res = super().get_values()
        cfg = self.env['ir.config_parameter'].sudo()
        res['cs_enabled'] = cfg.get_param('cs.enabled', 'True') == 'True'
        for lang in ('nl', 'en', 'de'):
            raw = cfg.get_param(f'cs.popup_text.{lang}', '')
            res[f'cs_popup_text_{lang}'] = Markup(raw) if raw else False

        country_param = cfg.get_param('cs.allowed_country_ids', '')
        country_ids = [int(x) for x in country_param.split(',') if x.strip().isdigit()] if country_param else []
        res['cs_allowed_country_ids'] = [(6, 0, country_ids)]

        excluded_param = cfg.get_param('cs.excluded_product_ids', '')
        excluded_ids = [int(x) for x in excluded_param.split(',') if x.strip().isdigit()] if excluded_param else []
        res['cs_excluded_product_ids'] = [(6, 0, excluded_ids)]

        included_param = cfg.get_param('cs.included_product_ids', '')
        included_ids = [int(x) for x in included_param.split(',') if x.strip().isdigit()] if included_param else []
        res['cs_included_product_ids'] = [(6, 0, included_ids)]

        carrier_param = cfg.get_param('cs.office_delivery_carrier_id', '')
        if carrier_param.strip().isdigit():
            carrier = self.env['delivery.carrier'].sudo().browse(int(carrier_param))
            res['cs_office_delivery_carrier_id'] = carrier.id if carrier.exists() else False
        else:
            res['cs_office_delivery_carrier_id'] = False

        return res

    def set_values(self) -> None:
        super().set_values()
        cfg = self.env['ir.config_parameter'].sudo()
        cfg.set_param('cs.enabled', 'True' if self.cs_enabled else 'False')
        for lang in ('nl', 'en', 'de'):
            cfg.set_param(f'cs.popup_text.{lang}', getattr(self, f'cs_popup_text_{lang}', '') or '')
        cfg.set_param('cs.allowed_country_ids', ','.join(str(c.id) for c in self.cs_allowed_country_ids))
        cfg.set_param('cs.excluded_product_ids', ','.join(str(p.id) for p in self.cs_excluded_product_ids))
        cfg.set_param('cs.included_product_ids', ','.join(str(p.id) for p in self.cs_included_product_ids))
        cfg.set_param(
            'cs.office_delivery_carrier_id',
            str(self.cs_office_delivery_carrier_id.id) if self.cs_office_delivery_carrier_id else '',
        )
        self._sync_cs_box_image(self.cs_box_image_url or '')

    def _sync_cs_box_image(self, url):
        """Fetch *url* and store it as the CS box product image, or clear it when empty."""
        try:
            cs_box_tmpl = self.env.ref('circular_shipping_checkout.product_cs_box').sudo()
            if not url:
                cs_box_tmpl.write({'image_1920': False})
                return
            response = _requests.get(url, timeout=10)
            response.raise_for_status()
            cs_box_tmpl.write({'image_1920': base64.b64encode(response.content)})
        except Exception:
            _logger.warning('circular_shipping: failed to sync box image from %s', url, exc_info=True)
