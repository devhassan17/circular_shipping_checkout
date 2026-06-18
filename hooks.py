# -*- coding: utf-8 -*-
"""Install-time seeding for Circular Shipping settings.

Settings live as fields on the ``website`` model (see models/website.py). New
website records get their values from the field defaults automatically; this
hook back-fills the websites that already exist at install time, which field
defaults do not reach. Idempotent: only writes a field when it is still empty,
so operator-customised values are never overwritten — not even on reinstall.

On module upgrade this hook does not run.
"""
import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Seed default settings on every existing website if not already set."""
    from .models.website import (
        CS_POPUP_TEXT_NL, CS_POPUP_TEXT_EN, CS_POPUP_TEXT_DE,
    )

    deposit = env.ref('circular_shipping_checkout.product_packaging_deposit', raise_if_not_found=False)
    single_use = env.ref('circular_shipping_checkout.product_single_use_fee', raise_if_not_found=False)

    seeded_total = 0
    for website in env['website'].sudo().search([]):
        vals = {}
        if not website.cs_popup_text_nl:
            vals['cs_popup_text_nl'] = CS_POPUP_TEXT_NL
        if not website.cs_popup_text_en:
            vals['cs_popup_text_en'] = CS_POPUP_TEXT_EN
        if not website.cs_popup_text_de:
            vals['cs_popup_text_de'] = CS_POPUP_TEXT_DE
        if not website.boxo_api_url:
            vals['boxo_api_url'] = 'https://api.boxo.nu'
        if deposit and not website.cs_deposit_product_id:
            vals['cs_deposit_product_id'] = deposit.product_variant_id.id
        if single_use and not website.cs_single_use_product_id:
            vals['cs_single_use_product_id'] = single_use.product_variant_id.id
        if vals:
            website.write(vals)
            seeded_total += len(vals)
            _logger.info(
                'circular_shipping: post_init_hook — seeded %d field(s) on website id=%s: %s',
                len(vals), website.id, ', '.join(sorted(vals.keys())),
            )
    if seeded_total == 0:
        _logger.info('circular_shipping: post_init_hook — no defaults needed (all already set)')
