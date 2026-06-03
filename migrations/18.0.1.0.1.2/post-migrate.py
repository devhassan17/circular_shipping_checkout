# -*- coding: utf-8 -*-
"""Move CS settings from ir.config_parameter to fields on `website`.

Runs once on upgrade from any pre-2.0 release to 18.0.2.0. Idempotent: if a
legacy key has already been removed, the corresponding website field is left
at its model default. Per-website application: existing global values are
copied to every website record so multi-website Odoo installs end up with the
same starting state (operators can diverge per-website afterwards).
"""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)


# ── Map legacy ir.config_parameter keys → (website field name, type tag) ──
_BOOL = 'bool'
_FLOAT = 'float'
_INT = 'int'
_STR = 'str'
_HTML = 'html'
_M2M_PRODUCT = 'm2m_product'
_M2M_COUNTRY = 'm2m_country'
_M2O_CARRIER = 'm2o_carrier'

_KEY_TO_FIELD = {
    'cs.enabled':                    ('cs_enabled', _BOOL),
    'cs.test_mode':                  ('cs_test_mode', _BOOL),
    'cs.deposit_amount':             ('cs_deposit_amount', _FLOAT),
    'cs.single_use_fee':             ('cs_single_use_fee', _FLOAT),
    'cs.pricing_model':              ('cs_pricing_model', _STR),
    'cs.default_selection':          ('cs_default_selection', _STR),
    'cs.ab_test_enabled':            ('cs_ab_test_enabled', _BOOL),
    'cs.ab_split_ratio':             ('cs_ab_split_ratio', _FLOAT),
    'cs.popup_text.nl':              ('cs_popup_text_nl', _HTML),
    'cs.popup_text.en':              ('cs_popup_text_en', _HTML),
    'cs.popup_text.de':              ('cs_popup_text_de', _HTML),
    'cs.explainer_reusable.nl':      ('cs_explainer_reusable_nl', _STR),
    'cs.explainer_reusable.en':      ('cs_explainer_reusable_en', _STR),
    'cs.explainer_reusable.de':      ('cs_explainer_reusable_de', _STR),
    'cs.explainer_single_use.nl':    ('cs_explainer_single_use_nl', _STR),
    'cs.explainer_single_use.en':    ('cs_explainer_single_use_en', _STR),
    'cs.explainer_single_use.de':    ('cs_explainer_single_use_de', _STR),
    'cs.allowed_country_ids':        ('cs_allowed_country_ids', _M2M_COUNTRY),
    'cs.max_products':               ('cs_max_products', _INT),
    'cs.product_allow_mode':         ('cs_product_allow_mode', _STR),
    'cs.excluded_product_ids':       ('cs_excluded_product_ids', _M2M_PRODUCT),
    'cs.included_product_ids':       ('cs_included_product_ids', _M2M_PRODUCT),
    'cs.required_total_qty':         ('cs_required_total_qty', _INT),
    'cs.office_delivery_carrier_id': ('cs_office_delivery_carrier_id', _M2O_CARRIER),
    'cs.box_image_url':              ('cs_box_image_url', _STR),
    'cs.dark_mode':                  ('cs_dark_mode', _BOOL),
    'boxo.api_key':                  ('boxo_api_key', _STR),
    'boxo.api_url':                  ('boxo_api_url', _STR),
}


def _coerce(value, type_tag, env):
    if value in (False, None):
        return None
    if type_tag == _BOOL:
        return str(value).strip().lower() in ('true', '1', 'yes')
    if type_tag == _FLOAT:
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    if type_tag == _INT:
        try:
            return int(value)
        except (TypeError, ValueError):
            return None
    if type_tag in (_STR, _HTML):
        return value or ''
    if type_tag == _M2M_PRODUCT:
        ids = [int(x) for x in str(value).split(',') if x.strip().isdigit()]
        existing = env['product.product'].browse(ids).exists().ids
        return [(6, 0, existing)]
    if type_tag == _M2M_COUNTRY:
        ids = [int(x) for x in str(value).split(',') if x.strip().isdigit()]
        existing = env['res.country'].browse(ids).exists().ids
        return [(6, 0, existing)]
    if type_tag == _M2O_CARRIER:
        raw = str(value).strip()
        if not raw.isdigit():
            return False
        carrier = env['delivery.carrier'].browse(int(raw))
        return carrier.id if carrier.exists() else False
    return None


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    ConfigParameter = env['ir.config_parameter'].sudo()
    websites = env['website'].sudo().search([])
    if not websites:
        _logger.info('circular_shipping migration: no website records, nothing to migrate')
        return

    # 1. Read legacy values once
    legacy = {}
    for key in _KEY_TO_FIELD:
        legacy[key] = ConfigParameter.get_param(key, False)

    # Pre-1.0 plugin used an un-suffixed `cs.popup_text` key as a fallback
    if legacy.get('cs.popup_text.nl') in (False, None, ''):
        fallback = ConfigParameter.get_param('cs.popup_text', False)
        if fallback:
            legacy['cs.popup_text.nl'] = fallback

    # 2. Apply to every website
    copied = []
    for website in websites:
        vals = {}
        for key, (field_name, type_tag) in _KEY_TO_FIELD.items():
            raw = legacy.get(key)
            if raw in (False, None, ''):
                continue
            coerced = _coerce(raw, type_tag, env)
            if coerced is None:
                continue
            vals[field_name] = coerced
        if vals:
            website.write(vals)
            copied.append((website.id, sorted(vals.keys())))

    for wid, keys in copied:
        _logger.info(
            'circular_shipping migration: migrated %d field(s) onto website id=%s: %s',
            len(keys), wid, ', '.join(keys),
        )

    # 3. Remove legacy keys (including the pre-1.0 cs.popup_text fallback)
    legacy_keys = list(_KEY_TO_FIELD.keys()) + ['cs.popup_text']
    stale = ConfigParameter.search([('key', 'in', legacy_keys)])
    if stale:
        _logger.info(
            'circular_shipping migration: removing %d legacy ir.config_parameter key(s): %s',
            len(stale), ', '.join(stale.mapped('key')),
        )
        stale.unlink()
