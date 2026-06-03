# -*- coding: utf-8 -*-
"""Persistent storage for Circular Shipping settings.

Settings used to live in `ir.config_parameter` and were round-tripped through
manual get_values/set_values overrides on res.config.settings. That pattern
silently wiped m2m and m2o fields whenever any unrelated Odoo settings panel
was saved (a TransientModel artefact — see migrations/18.0.2.0/post-migrate.py
header for the full story).

Settings now live on the persistent `website` model. res.config.settings
exposes each field via related='website_id.cs_*'. A related field can only be
written when the saving panel's form payload contains it, so foreign-panel
saves can no longer touch CS data.
"""
import base64
import logging

import requests as _requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class Website(models.Model):
    _inherit = 'website'

    # ── Plugin master switch ────────────────────────────────────────────────
    # Default False: operator must explicitly enable on each website so a
    # fresh install never starts widget-active on someone else's storefront.
    cs_enabled = fields.Boolean(
        string='Circular Shipping ingeschakeld',
        default=False,
    )

    # ── BOXO API integration ────────────────────────────────────────────────
    cs_test_mode = fields.Boolean(
        string='Testmodus',
        default=False,
        help='Skip the BOXO API call and treat any valid NL postcode as available.',
    )
    boxo_api_key = fields.Char(
        string='BOXO API-sleutel',
        help='API key for the BOXO postcode-availability service.',
    )
    boxo_api_url = fields.Char(
        string='BOXO API URL',
        default='https://api.boxo.nu',
    )

    # ── Pricing ─────────────────────────────────────────────────────────────
    cs_deposit_amount = fields.Float(
        string='Borg herbruikbaar (EUR)',
        default=3.95,
    )
    cs_single_use_fee = fields.Float(
        string='Toeslag wegwerp (EUR)',
        default=0.25,
    )
    cs_pricing_model = fields.Selection(
        selection=[('direct', 'Direct'), ('via_shipping', 'Via verzendkosten')],
        string='Prijsmodel',
        default='direct',
    )
    cs_default_selection = fields.Selection(
        selection=[('reusable', 'Statiegeld verpakking'), ('single_use', 'Wegwerpverpakking')],
        string='Standaard selectie',
        default='single_use',
    )

    # ── A/B testing (currently disabled in UI) ─────────────────────────────
    cs_ab_test_enabled = fields.Boolean(string='A/B test ingeschakeld', default=False)
    cs_ab_split_ratio = fields.Float(string='A/B split ratio (0-1)', default=0.5)

    # ── Popup copy (per language) ───────────────────────────────────────────
    cs_popup_text_nl = fields.Html(string='Info popup tekst — NL', sanitize=True)
    cs_popup_text_en = fields.Html(string='Info popup tekst — EN', sanitize=True)
    cs_popup_text_de = fields.Html(string='Info popup tekst — DE', sanitize=True)

    cs_explainer_reusable_nl = fields.Char(string='Uitleg statiegeld — NL')
    cs_explainer_reusable_en = fields.Char(string='Explainer deposit — EN')
    cs_explainer_reusable_de = fields.Char(string='Erklärung Pfand — DE')
    cs_explainer_single_use_nl = fields.Char(string='Uitleg wegwerp — NL')
    cs_explainer_single_use_en = fields.Char(string='Explainer single-use — EN')
    cs_explainer_single_use_de = fields.Char(string='Erklärung Einweg — DE')

    # ── Geographic and quantity eligibility ─────────────────────────────────
    cs_allowed_country_ids = fields.Many2many(
        'res.country',
        'cs_country_website_rel',
        'website_id',
        'country_id',
        string='Toegestane landen',
        help='Landen waar de CS widget getoond wordt. Leeg = alle landen.',
    )
    cs_max_products = fields.Integer(
        string='Maximum aantal producten',
        default=0,
        help='Maximum aantal producten voor herbruikbare verpakking. 0 = geen limiet.',
    )

    # ── Product filter ──────────────────────────────────────────────────────
    cs_product_allow_mode = fields.Selection(
        selection=[
            ('all', 'Alle producten toegestaan'),
            ('exclude', 'Alle behalve geselecteerde producten'),
            ('include', 'Alleen geselecteerde producten'),
        ],
        string='Productfilter modus',
        default='include',
    )
    cs_excluded_product_ids = fields.Many2many(
        'product.product',
        'cs_excluded_product_website_rel',
        'website_id',
        'product_id',
        string='Uitgesloten producten',
    )
    cs_included_product_ids = fields.Many2many(
        'product.product',
        'cs_included_product_website_rel',
        'website_id',
        'product_id',
        string='Toegestane producten',
    )
    cs_required_total_qty = fields.Integer(
        string='Vereist aantal',
        default=0,
        help='Totaal aantal stuks van de toegestane producten dat exact in de bestelling aanwezig moet zijn. 0 = CS widget nooit actief.',
    )

    # ── Delivery carrier swap ───────────────────────────────────────────────
    cs_office_delivery_carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Bezorgmethode (statiegeld)',
        help='Bezorgmethode die automatisch wordt geselecteerd wanneer de klant Statiegeld verpakking kiest.',
    )

    # ── CSC box thumbnail and contrast styling ──────────────────────────────
    cs_box_image_url = fields.Char(
        string='CSC Box afbeelding URL',
        help='URL van de afbeelding die in de widget naast de statiegeld-optie getoond wordt. Leeg = productafbeelding wordt verwijderd.',
    )
    cs_dark_mode = fields.Boolean(
        string='Contrast mode widget',
        default=False,
        help='Toont de verpakkingswidget met een roze achtergrond en roze rand.',
    )

    # ── Hooks ───────────────────────────────────────────────────────────────
    def write(self, vals):
        """Sync the CS box product image whenever cs_box_image_url is written."""
        previous = {w.id: w.cs_box_image_url for w in self} if 'cs_box_image_url' in vals else {}
        res = super().write(vals)
        if 'cs_box_image_url' in vals:
            for w in self:
                if previous.get(w.id) != w.cs_box_image_url:
                    w._sync_cs_box_image()
        return res

    def _sync_cs_box_image(self):
        """Fetch the configured URL and store it as the CSC box product image, or clear it when empty."""
        self.ensure_one()
        url = self.cs_box_image_url or ''
        try:
            cs_box_tmpl = self.env.ref('circular_shipping_checkout.product_cs_box').sudo()
        except ValueError:
            _logger.warning('circular_shipping: product_cs_box not found while syncing box image')
            return
        try:
            if not url:
                cs_box_tmpl.write({'image_1920': False})
                return
            response = _requests.get(url, timeout=10)
            response.raise_for_status()
            cs_box_tmpl.write({'image_1920': base64.b64encode(response.content)})
        except Exception:
            _logger.warning('circular_shipping: failed to sync box image from %s', url, exc_info=True)
