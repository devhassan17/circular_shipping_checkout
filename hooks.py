# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


_POPUP_TEXTS = {
    'cs.popup_text.nl': (
        '<p>Kies voor <strong>statiegeld verpakking</strong> en ontvang je koffie in '
        'herbruikbaar, duurzaam verpakkingsmateriaal. Bij retour ontvang je het statiegeld '
        'terug.</p>'
        '<p><a href="https://www.moyeecoffee.com/nl/circular-shipping-company" '
        'target="_blank" rel="noopener">'
        'Meer informatie over ons duurzame verpakkingssysteem →</a></p>'
    ),
    'cs.popup_text.en': (
        '<p>Choose <strong>deposit packaging</strong> and receive your coffee in reusable, '
        'sustainable packaging. Return the packaging and get your deposit back.</p>'
        '<p><a href="https://www.moyeecoffee.com/en/circular-shipping-company" '
        'target="_blank" rel="noopener">'
        'More information about our sustainable packaging system →</a></p>'
    ),
    'cs.popup_text.de': (
        '<p>Wählen Sie <strong>Pfandverpackung</strong> und erhalten Sie Ihren Kaffee '
        'in wiederverwendbarem, nachhaltigem Verpackungsmaterial. Bei Rückgabe erhalten '
        'Sie das Pfand zurück.</p>'
        '<p><a href="https://www.moyeecoffee.com/de/circular-shipping-company" '
        'target="_blank" rel="noopener">'
        'Mehr Informationen über unser nachhaltiges Verpackungssystem →</a></p>'
    ),
}


def post_init_hook(env):
    """Seed info-popup texts on fresh install.

    Only writes a value when the parameter does not exist yet, so custom
    text edited in the backend is never overwritten — not even on reinstall.
    On upgrade this hook does not run at all.
    """
    cfg = env['ir.config_parameter'].sudo()
    seeded = []
    for key, value in _POPUP_TEXTS.items():
        if not cfg.get_param(key):
            cfg.set_param(key, value)
            seeded.append(key)
    if seeded:
        _logger.info('circular_shipping: post_init_hook — seeded popup text param(s): %s', ', '.join(seeded))


# Parameters that are environment-specific and must be reconfigured after
# a reinstall: delivery method and product filter settings.
_REINSTALL_CLEAR_KEYS = (
    'cs.enabled',
    'cs.office_delivery_carrier_id',
    'cs.product_allow_mode',
    'cs.excluded_product_ids',
    'cs.included_product_ids',
    'cs.allowed_country_ids',
    'cs.max_products',
    'cs.required_total_qty',
)


def uninstall_hook(env):
    """Clear environment-specific settings on uninstall.

    Only the delivery method and product filter parameters are removed so
    that a reinstall starts with a clean slate for those fields. All text
    settings (popup copy, explainer labels, pricing) are left intact and
    will carry over to the reinstalled module unchanged.

    On module upgrade (without uninstall) this hook does not run.
    """
    cfg = env['ir.config_parameter'].sudo()
    params = cfg.search([('key', 'in', list(_REINSTALL_CLEAR_KEYS))])
    if params:
        _logger.info(
            'circular_shipping: uninstall_hook — removing %d config parameter(s): %s',
            len(params), ', '.join(params.mapped('key')),
        )
        params.unlink()
