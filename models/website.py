# -*- coding: utf-8 -*-
"""Persistent storage for Circular Shipping settings.

Settings used to live in ``ir.config_parameter`` and were round-tripped through
manual ``get_values``/``set_values`` overrides on ``res.config.settings``. That
pattern silently wiped m2m/m2o values whenever any unrelated Odoo settings panel
was saved (a TransientModel artefact), and stored everything globally.

Settings now live on the persistent ``website`` model — per website, native
typed columns and real relation tables. ``res.config.settings`` only proxies
them via ``related='website_id.cs_*'``. A related field is written only when the
saving panel's form payload actually contains it, so foreign-panel saves can no
longer touch CS data.
"""
import base64
import logging

import requests as _requests

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


# Default info-popup copy seeded onto each website (editable afterwards).
CS_POPUP_TEXT_NL = (
    '<p>Kies voor <strong>statiegeld verpakking</strong> en ontvang je koffie in '
    'herbruikbaar, duurzaam verpakkingsmateriaal. Bij retour ontvang je het statiegeld '
    'terug.</p>'
    '<p><a href="https://www.moyeecoffee.com/nl/circular-shipping-company" '
    'target="_blank" rel="noopener">'
    'Meer informatie over ons duurzame verpakkingssysteem →</a></p>'
)
CS_POPUP_TEXT_EN = (
    '<p>Choose <strong>deposit packaging</strong> and receive your coffee in reusable, '
    'sustainable packaging. Return the packaging and get your deposit back.</p>'
    '<p><a href="https://www.moyeecoffee.com/en/circular-shipping-company" '
    'target="_blank" rel="noopener">'
    'More information about our sustainable packaging system →</a></p>'
)
CS_POPUP_TEXT_DE = (
    '<p>Wählen Sie <strong>Pfandverpackung</strong> und erhalten Sie Ihren Kaffee '
    'in wiederverwendbarem, nachhaltigem Verpackungsmaterial. Bei Rückgabe erhalten '
    'Sie das Pfand zurück.</p>'
    '<p><a href="https://www.moyeecoffee.com/de/circular-shipping-company" '
    'target="_blank" rel="noopener">'
    'Mehr Informationen über unser nachhaltiges Verpackungssystem →</a></p>'
)

# Default one-line explainer copy shown under each choice in the widget
# (editable afterwards — same seeding model as the popup texts above).
CS_EXPLAINER_REUSABLE_NL = 'Je borg wordt geretourneerd bij inlevering'
CS_EXPLAINER_REUSABLE_EN = 'Your deposit is returned when packaging is collected'
CS_EXPLAINER_REUSABLE_DE = 'Ihr Pfand wird bei Rückgabe erstattet'
CS_EXPLAINER_SINGLE_USE_NL = 'Standaard bezorgverpakking'
CS_EXPLAINER_SINGLE_USE_EN = 'Standard delivery packaging'
CS_EXPLAINER_SINGLE_USE_DE = 'Standard Lieferverpackung'


class Website(models.Model):
    _inherit = 'website'

    # ── Default callables for the service products ──────────────────────────
    def _default_cs_deposit_product(self):
        tmpl = self.env.ref(
            'circular_shipping_checkout.product_packaging_deposit', raise_if_not_found=False,
        )
        return tmpl.product_variant_id if tmpl else False

    def _default_cs_single_use_product(self):
        tmpl = self.env.ref(
            'circular_shipping_checkout.product_single_use_fee', raise_if_not_found=False,
        )
        return tmpl.product_variant_id if tmpl else False

    # ── Plugin master switch ────────────────────────────────────────────────
    # Default False: operator must explicitly enable per website so a fresh
    # install never starts widget-active on someone else's storefront.
    cs_enabled = fields.Boolean(
        string='Circular Shipping ingeschakeld',
        default=False,
    )

    # ── BOXO API integration ────────────────────────────────────────────────
    cs_test_mode = fields.Boolean(
        string='Testmodus',
        default=False,
        help='Widget verschijnt bij elk geldig NL postcode zonder de BOXO API aan te roepen.',
    )
    boxo_api_key = fields.Char(string='BOXO API-sleutel')
    boxo_api_url = fields.Char(string='BOXO API URL', default='https://api.boxo.nu')

    # ── Pricing ─────────────────────────────────────────────────────────────
    cs_deposit_amount = fields.Float(string='Borg herbruikbaar (EUR)', default=3.95)
    cs_single_use_fee = fields.Float(string='Toeslag wegwerp (EUR)', default=0.25)
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
    cs_deposit_product_id = fields.Many2one(
        'product.product',
        string='Borgproduct',
        default=_default_cs_deposit_product,
        help='Product dat als borgregel aan de bestelling wordt toegevoegd bij statiegeld verpakking.',
    )
    cs_single_use_product_id = fields.Many2one(
        'product.product',
        string='Wegwerptoeslagproduct',
        default=_default_cs_single_use_product,
        help='Product dat als toeslagregel aan de bestelling wordt toegevoegd bij wegwerpverpakking.',
    )

    # ── A/B testing (currently disabled in UI) ─────────────────────────────
    cs_ab_test_enabled = fields.Boolean(string='A/B test ingeschakeld', default=False)
    cs_ab_split_ratio = fields.Float(string='A/B split ratio (0-1)', default=0.5)

    # ── Popup copy (per language) ───────────────────────────────────────────
    cs_popup_text_nl = fields.Html(
        string='Info popup tekst — NL', sanitize=True, default=lambda self: CS_POPUP_TEXT_NL,
    )
    cs_popup_text_en = fields.Html(
        string='Info popup tekst — EN', sanitize=True, default=lambda self: CS_POPUP_TEXT_EN,
    )
    cs_popup_text_de = fields.Html(
        string='Info popup tekst — DE', sanitize=True, default=lambda self: CS_POPUP_TEXT_DE,
    )

    cs_explainer_reusable_nl = fields.Char(
        string='Uitleg statiegeld — NL', default=lambda self: CS_EXPLAINER_REUSABLE_NL,
    )
    cs_explainer_reusable_en = fields.Char(
        string='Explainer deposit — EN', default=lambda self: CS_EXPLAINER_REUSABLE_EN,
    )
    cs_explainer_reusable_de = fields.Char(
        string='Erklärung Pfand — DE', default=lambda self: CS_EXPLAINER_REUSABLE_DE,
    )
    cs_explainer_single_use_nl = fields.Char(
        string='Uitleg wegwerp — NL', default=lambda self: CS_EXPLAINER_SINGLE_USE_NL,
    )
    cs_explainer_single_use_en = fields.Char(
        string='Explainer single-use — EN', default=lambda self: CS_EXPLAINER_SINGLE_USE_EN,
    )
    cs_explainer_single_use_de = fields.Char(
        string='Erklärung Einweg — DE', default=lambda self: CS_EXPLAINER_SINGLE_USE_DE,
    )

    # ── Geographic / quantity gating ────────────────────────────────────────
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

    # ── Product filter — three-mode system (all / exclude / include) ────────
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
        help='Producten waarvoor de CS widget niet getoond wordt.',
    )
    cs_included_product_ids = fields.Many2many(
        'product.product',
        'cs_included_product_website_rel',
        'website_id',
        'product_id',
        string='Toegestane producten',
        help='Alleen voor deze producten wordt de CS widget getoond.',
    )
    cs_required_total_qty = fields.Integer(
        string='Vereist aantal',
        default=0,
        help='Totaal aantal stuks van de toegestane producten dat exact in de bestelling '
             'aanwezig moet zijn. 0 = CS widget nooit actief.',
    )

    # ── Delivery ─────────────────────────────────────────────────────────────
    cs_office_delivery_carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Bezorgmethode (statiegeld)',
        help='Bezorgmethode die automatisch wordt geselecteerd wanneer de klant Statiegeld '
             'verpakking kiest.',
    )

    # ── Widget appearance ────────────────────────────────────────────────────
    cs_box_image_url = fields.Char(string='CSC Box afbeelding URL')
    cs_dark_mode = fields.Boolean(string='Contrast mode widget', default=False)

    # ── Keep product list_price in sync with the configured amount ──────────
    @api.onchange('cs_deposit_amount')
    def _onchange_cs_deposit_amount(self):
        if self.cs_deposit_product_id and self.cs_deposit_amount:
            self.cs_deposit_product_id.list_price = self.cs_deposit_amount

    @api.onchange('cs_single_use_fee')
    def _onchange_cs_single_use_fee(self):
        if self.cs_single_use_product_id and self.cs_single_use_fee:
            self.cs_single_use_product_id.list_price = self.cs_single_use_fee

    def write(self, vals):
        """Persist amount→product price sync and box-image fetch on save.

        onchange gives live UI feedback; this guarantees the side effects also
        happen when the fields are written from anywhere (settings save, ORM).
        """
        res = super().write(vals)
        for website in self:
            if 'cs_deposit_amount' in vals and website.cs_deposit_product_id:
                website.cs_deposit_product_id.sudo().list_price = website.cs_deposit_amount
            if 'cs_single_use_fee' in vals and website.cs_single_use_product_id:
                website.cs_single_use_product_id.sudo().list_price = website.cs_single_use_fee
            if 'cs_box_image_url' in vals:
                website._sync_cs_box_image(website.cs_box_image_url or '')
        return res

    def _sync_cs_box_image(self, url):
        """Fetch *url* and store it as the CS box product image, or clear it when empty."""
        cs_box_tmpl = self.env.ref(
            'circular_shipping_checkout.product_cs_box', raise_if_not_found=False,
        )
        if not cs_box_tmpl:
            return
        cs_box_tmpl = cs_box_tmpl.sudo()
        try:
            if not url:
                cs_box_tmpl.write({'image_1920': False})
                return
            response = _requests.get(url, timeout=10)
            response.raise_for_status()
            cs_box_tmpl.write({'image_1920': base64.b64encode(response.content)})
        except Exception:
            _logger.warning('circular_shipping: failed to sync box image from %s', url, exc_info=True)
