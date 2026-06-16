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


_BOX_IMAGE_URL = 'https://moyeecoffee.odoo.com/web/image/ir.attachment/86165/datas'


_EXPLAINER_TEXTS = {
    'cs.explainer_reusable.nl': (
        'Je betaalt statiegeld, dat je weer terug krijgt bij het inleveren van deze '
        'hebruikbare verpakking!'
    ),
    'cs.explainer_reusable.en': (
        'You pay a deposit, which you get back when you return this reusable packaging!'
    ),
    'cs.explainer_reusable.de': (
        'Sie zahlen eine Kaution, die Sie bei Rückgabe der wiederverwendbaren '
        'Verpackung zurückerhalten!'
    ),
    'cs.explainer_single_use.nl': (
        'Als je kiest voor een wegwerpverpakking betaal je een toeslag van €0,25'
    ),
    'cs.explainer_single_use.en': (
        'If you choose for single-use, you pay a €0,25 surcharge'
    ),
    'cs.explainer_single_use.de': (
        'Bei Wahl einer Einwegverpackung wird ein Aufpreis von 0,25 € fällig'
    ),
}


_INSTALL_DEFAULTS = {
    'cs.enabled': 'False',
    'cs.product_allow_mode': 'include',
    'cs.box_image_url': _BOX_IMAGE_URL,
}


def post_init_hook(env):
    """Seed default config values and info-popup texts on fresh install.

    Only writes a value when the parameter does not exist yet, so custom
    text edited in the backend is never overwritten — not even on reinstall.
    On upgrade this hook does not run at all.
    """
    cfg = env['ir.config_parameter'].sudo()
    seeded = []
    for key, value in {**_INSTALL_DEFAULTS, **_POPUP_TEXTS, **_EXPLAINER_TEXTS}.items():
        if not cfg.get_param(key):
            cfg.set_param(key, value)
            seeded.append(key)
    if seeded:
        _logger.info('circular_shipping: post_init_hook — seeded param(s): %s', ', '.join(seeded))

    # Fetch and store the default box image when we just seeded its URL.
    if 'cs.box_image_url' in seeded:
        env['res.config.settings']._sync_cs_box_image(_BOX_IMAGE_URL)


# All settings survive uninstall so they are restored on reinstall.
# _INSTALL_DEFAULTS seeds cs.enabled=False only on a genuine first install
# (post_init_hook skips the key when it already exists).
_REINSTALL_CLEAR_KEYS = ()


def uninstall_hook(env):
    """No-op: all settings are preserved across uninstall/reinstall.

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
