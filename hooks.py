# -*- coding: utf-8 -*-
"""Install hook for circular_shipping_checkout.

Settings storage moved from ir.config_parameter to fields on `website` in
v18.0.2.0. The upgrade migration lives in `migrations/18.0.2.0/post-migrate.py`
and runs automatically when Odoo detects the version bump.

The earlier uninstall_hook / _REINSTALL_CLEAR_KEYS plumbing is no longer
needed — settings now live on persistent `website` rows, not in the global
ir.config_parameter table.

post_init_hook seeds the Moyee-branded popup copy on every website only when
not already set, so operator-edited copy is never overwritten.
"""
import logging

_logger = logging.getLogger(__name__)


_DEFAULT_POPUP_TEXTS = {
    'cs_popup_text_nl': (
        '<p>Kies voor <strong>statiegeld verpakking</strong> en ontvang je koffie in '
        'herbruikbaar, duurzaam verpakkingsmateriaal. Bij retour ontvang je het statiegeld '
        'terug.</p>'
        '<p><a href="https://www.moyeecoffee.com/nl/circular-shipping-company" '
        'target="_blank" rel="noopener">'
        'Meer informatie over ons duurzame verpakkingssysteem →</a></p>'
    ),
    'cs_popup_text_en': (
        '<p>Choose <strong>deposit packaging</strong> and receive your coffee in reusable, '
        'sustainable packaging. Return the packaging and get your deposit back.</p>'
        '<p><a href="https://www.moyeecoffee.com/en/circular-shipping-company" '
        'target="_blank" rel="noopener">'
        'More information about our sustainable packaging system →</a></p>'
    ),
    'cs_popup_text_de': (
        '<p>Wählen Sie <strong>Pfandverpackung</strong> und erhalten Sie Ihren Kaffee '
        'in wiederverwendbarem, nachhaltigem Verpackungsmaterial. Bei Rückgabe erhalten '
        'Sie das Pfand zurück.</p>'
        '<p><a href="https://www.moyeecoffee.com/de/circular-shipping-company" '
        'target="_blank" rel="noopener">'
        'Mehr Informationen über unser nachhaltiges Verpackungssystem →</a></p>'
    ),
}


def post_init_hook(env):
    """Seed default popup copy on every website if not already set.

    Idempotent: only writes a field when its current value is empty, so any
    text the operator has customised is left untouched.
    """
    seeded_total = 0
    for website in env['website'].sudo().search([]):
        vals = {}
        for field_name, default_value in _DEFAULT_POPUP_TEXTS.items():
            if not website[field_name]:
                vals[field_name] = default_value
        if vals:
            website.write(vals)
            seeded_total += len(vals)
            _logger.info(
                'circular_shipping: post_init_hook — seeded %d popup field(s) on website id=%s: %s',
                len(vals), website.id, ', '.join(sorted(vals.keys())),
            )
    if seeded_total == 0:
        _logger.info('circular_shipping: post_init_hook — no popup defaults needed (all already set)')
