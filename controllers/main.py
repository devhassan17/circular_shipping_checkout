# -*- coding: utf-8 -*-
import hashlib
import logging
import re
import time

from odoo import fields, http
from odoo.http import request
from odoo.exceptions import UserError
from markupsafe import Markup

try:
    from odoo.addons.website_sale.controllers.main import WebsiteSale
except ImportError:
    # Fallback for Odoo versions that reorganised the controller location
    from odoo.addons.website_sale.controllers.website_sale import WebsiteSale

# Keys from cs_packaging_config that are permitted to be exposed to the frontend
_CS_FRONTEND_ALLOWLIST = frozenset({
    'deposit_amount',
    'single_use_fee',
    'pricing_model',
    'default_selection',
})

_logger = logging.getLogger(__name__)

VALID_CHOICES = ('reusable', 'single_use')
NL_POSTCODE   = re.compile(r'^\d{4}[A-Za-z]{2}$')


class WebsiteSaleCircularShipping(WebsiteSale):

    # ── Clear packaging lines when navigating back to cart ──────────────────
    # Packaging lines are cleared when the user visits the cart so the order
    # total stays clean if they start a fresh checkout flow.

    def _cs_clear_packaging(self):
        """Remove all CS packaging and box lines and reset the type field."""
        try:
            order = request.website.sale_get_order()
            if not order:
                return
            lines = request.env['sale.order.line'].sudo().search([
                ('order_id', '=', order.id),
                '|',
                ('is_cs_packaging', '=', True),
                ('is_cs_box', '=', True),
            ])
            if lines:
                lines.sudo().unlink()
            order.sudo().write({'cs_packaging_type': False})
        except (ValueError, UserError) as e:
            _logger.exception('circular_shipping: error clearing packaging lines: %s', e)

    @http.route()
    def cart(self, *args, **kwargs):
        self._cs_clear_packaging()
        return super().cart(*args, **kwargs)

    def _prepare_checkout_page_values(self, order_sudo, **kwargs):
        """Inject CS packaging widget variables into the checkout page context."""
        values = super()._prepare_checkout_page_values(order_sudo, **kwargs)
        if request.website.sudo().cs_enabled:
            order_sudo._ensure_cs_box_line()
        values.update(self._cs_get_payment_values(order_sudo))
        return values

    # ── Template variables for the payment page ──────────────────────────────

    def _cs_get_payment_values(self, order):
        """Build CS-specific template variables for the payment page."""
        ws = request.website.sudo()
        if not ws.cs_enabled:
            return {
                'cs_packaging_config':     {},
                'cs_test_mode':            False,
                'cs_packaging_choice':     '',
                'cs_ab_variant':           '',
                'cs_lang':                 'en',
                'cs_packaging_label':      '',
                'cs_show_packaging_row':   False,
                'cs_partner_zip':          '',
                'cs_box_product_id':       0,
                'cs_box_product_name':     '',
                'cs_popup_text':           Markup(''),
                'cs_explainer_reusable':   '',
                'cs_explainer_single_use': '',
                'cs_box_image_url':        '',
                'cs_dark_mode':            False,
            }
        _lang_code = request.lang.code
        lang_key = 'nl' if _lang_code.startswith('nl') else ('de' if _lang_code.startswith('de') else 'en')
        popup_text_raw = getattr(ws, f'cs_popup_text_{lang_key}') or ''
        cs_popup_text = Markup(popup_text_raw) if popup_text_raw else Markup('')
        cs_explainer_reusable   = getattr(ws, f'cs_explainer_reusable_{lang_key}') or ''
        cs_explainer_single_use = getattr(ws, f'cs_explainer_single_use_{lang_key}') or ''
        test_mode = ws.cs_test_mode
        _full_config = {
            'deposit_amount':    ws.cs_deposit_amount or 0.0,
            'single_use_fee':    ws.cs_single_use_fee or 0.0,
            'pricing_model':     ws.cs_pricing_model or 'direct',
            'default_selection': ws.cs_default_selection or 'single_use',
        }
        current_choice = ''
        if order:
            current_choice = (
                order.cs_packaging_type
                if order.order_line.filtered(lambda l: l.is_cs_packaging)
                else ''
            )
        shipping = order.partner_shipping_id if order else None

        # Expose CSC box product variant ID so JS can find its cart row by image URL.
        # Use sudo() so Odoo 18 website record rules don't hide the non-published variant.
        cs_box_product_id = 0
        cs_box_product_name = ''
        try:
            cs_box_tmpl = request.env.ref('circular_shipping_checkout.product_cs_box').sudo()
            cs_box_product_id = cs_box_tmpl.product_variant_id.id
            cs_box_product_name = cs_box_tmpl.name
        except Exception:
            pass

        cs_box_image_url = ws.cs_box_image_url or ''
        dark_mode = ws.cs_dark_mode

        return {
            'cs_packaging_config':   {k: v for k, v in _full_config.items() if k in _CS_FRONTEND_ALLOWLIST},
            'cs_test_mode':          test_mode,
            'cs_packaging_choice':   current_choice,
            'cs_ab_variant':         self._get_ab_variant(),
            'cs_lang':               lang_key,
            'cs_packaging_label':    {'nl': '+ Statiegeld Verpakking', 'de': '+ Pfandverpackung'}.get(lang_key, '+ Deposit Packaging'),
            'cs_show_packaging_row': order._check_cs_eligibility()[0] if order else False,
            'cs_partner_zip':        (shipping.zip or '').replace(' ', '').upper() if shipping else '',
            'cs_box_product_id':     cs_box_product_id,
            'cs_box_product_name':   cs_box_product_name,
            'cs_popup_text':          cs_popup_text,
            'cs_explainer_reusable':  cs_explainer_reusable,
            'cs_explainer_single_use': cs_explainer_single_use,
            'cs_box_image_url':       cs_box_image_url,
            'cs_dark_mode':           dark_mode,
        }

    def _get_shop_payment_values(self, order, **kwargs):
        """Hook called by website_sale to build the payment page template context."""
        try:
            values = super()._get_shop_payment_values(order, **kwargs)
        except AttributeError:
            values = {}
        values.update(self._cs_get_payment_values(order))
        return values

    @http.route()
    def shop_payment(self, **post):
        """Override payment page to inject CS template variables via qcontext."""
        _order = request.website.sale_get_order()
        if _order:
            _order.sudo()._ensure_cs_box_line()

        response = super().shop_payment(**post)
        if hasattr(response, 'qcontext'):
            order = request.website.sale_get_order()
            self._cs_track_payment_page(order)
            response.qcontext.update(self._cs_get_payment_values(order))
        return response

    # ── Exposure funnel tracking helpers ──────────────────────────────────────

    def _cs_session_key(self):
        """Anonymous SHA-256 of the web session id (same primitive as A/B variant)."""
        sid = request.session.sid or ''
        return hashlib.sha256(sid.encode()).hexdigest() if sid else ''

    def _cs_track_payment_page(self, order):
        """Stage 1 (payment page reached) + Stage 2 (widget shown / not)."""
        if not order or not request.website.sudo().cs_enabled:
            return
        now = fields.Datetime.now()
        eligible, reason = order._check_cs_eligibility()
        log_vals = {
            'session_key':            self._cs_session_key(),
            'stage1_payment_page_ts': now,
            'widget_eligible':        eligible,
            'not_shown_reason':       '' if eligible else (reason or ''),
        }
        if eligible:
            # stamp-once "ever shown" marker
            log_vals['stage2_widget_ts'] = now
        # Stage 1 is the only hook that may create the event row.
        order.sudo()._cs_log_event(create_if_missing=True, **log_vals)

    # ── AJAX: set packaging choice ────────────────────────────────────────────
    # Returns updated order totals (same fields as website_sale delivery widget)
    # so the JS can update the displayed amounts without a page reload.

    @http.route('/cs/set_packaging_choice', type='json', auth='public', website=True)
    def set_packaging_choice(self, choice=None, **kwargs):
        if not request.website.sudo().cs_enabled:
            return {'ok': False, 'error': 'plugin_disabled'}
        last_call = request.session.get('cs_last_set_ts', 0)
        now = time.time()
        if now - last_call < 0.5:  # 500ms server-side guard against automation
            return {'ok': False, 'error': 'too_many_requests'}
        request.session['cs_last_set_ts'] = now

        if choice not in VALID_CHOICES:
            return {'ok': False, 'error': 'invalid_choice'}

        order = request.website.sale_get_order()
        if not order:
            return {'ok': False, 'error': 'no_order'}

        order.sudo().write({'cs_packaging_type': choice})
        order.sudo()._apply_packaging_fee(choice)

        ab_variant = self._get_ab_variant()
        order.sudo().write({'cs_ab_variant': ab_variant})

        # Exposure funnel: record the packaging choice + decision timestamp.
        order.sudo()._cs_log_event(packaging_choice=choice, choice_ts=fields.Datetime.now())

        Monetary = request.env['ir.qweb.field.monetary']
        currency = order.currency_id
        return {
            'ok':                    True,
            'choice':                choice,
            # Deposit row — shown for reusable, hidden for single-use
            'new_amount_packaging':  Monetary.value_to_html(order.cs_amount_packaging, {'display_currency': currency}),
            'has_packaging':         order.cs_amount_packaging != 0.0,
            # Surcharge row — shown for single-use, hidden for reusable
            'new_amount_surcharge':  Monetary.value_to_html(order.cs_amount_surcharge, {'display_currency': currency}),
            'has_surcharge':         order.cs_amount_surcharge != 0.0,
            # Order totals
            'new_amount_untaxed':    Monetary.value_to_html(order.amount_untaxed, {'display_currency': currency}),
            'new_amount_tax':        Monetary.value_to_html(order.amount_tax,     {'display_currency': currency}),
            'new_amount_total':      Monetary.value_to_html(order.amount_total,   {'display_currency': currency}),
            'new_amount_total_raw':  order.amount_total,
            # CSC box product line — visible only for reusable packaging
            'show_cs_box':           choice == 'reusable',
            # Cart item count excluding the CS box when it is hidden
            'new_cart_quantity':     int(sum(
                l.product_uom_qty for l in order.order_line
                if not l.is_delivery
                and not l.is_cs_packaging
                and not (l.is_cs_box and choice != 'reusable')
            )),
        }

    # ── Cart update hook: log eligibility after product changes ─────────────

    @http.route()
    def cart_update_json(self, product_id, line_id=None, add_qty=None, set_qty=None, **kwargs):
        result = super().cart_update_json(
            product_id, line_id=line_id, add_qty=add_qty, set_qty=set_qty, **kwargs,
        )
        order = request.website.sale_get_order()
        if order:
            eligible, reason = order._check_cs_eligibility()
            _logger.info(
                'circular_shipping: cart changed — product_id=%s add_qty=%s set_qty=%s '
                'order=%s eligible=%s reason="%s"',
                product_id, add_qty, set_qty, order.name, eligible, reason,
            )
        return result

    # ── AJAX: clear packaging choice (e.g. user navigates away and back) ─────

    @http.route('/cs/clear_packaging_choice', type='json', auth='public', website=True)
    def clear_packaging_choice(self, **kwargs):
        if not request.website.sudo().cs_enabled:
            return {'ok': True}
        order = request.website.sale_get_order()
        if not order:
            return {'ok': True}
        order.sudo().order_line.filtered(
            lambda l: l.is_cs_packaging or l.is_cs_box
        ).unlink()
        order.sudo().write({'cs_packaging_type': False})
        Monetary = request.env['ir.qweb.field.monetary']
        currency = order.currency_id
        return {
            'ok':                    True,
            'has_packaging':         False,
            'new_amount_packaging':  Monetary.value_to_html(0.0, {'display_currency': currency}),
            'has_surcharge':         False,
            'new_amount_surcharge':  Monetary.value_to_html(0.0, {'display_currency': currency}),
            'new_amount_untaxed':    Monetary.value_to_html(order.amount_untaxed, {'display_currency': currency}),
            'new_amount_tax':        Monetary.value_to_html(order.amount_tax,     {'display_currency': currency}),
            'new_amount_total':      Monetary.value_to_html(order.amount_total,   {'display_currency': currency}),
            'new_amount_total_raw':  order.amount_total,
            'show_cs_box':           False,
            'new_cart_quantity':     int(sum(
                l.product_uom_qty for l in order.order_line
                if not l.is_delivery and not l.is_cs_packaging and not l.is_cs_box
            )),
        }

    # ── AJAX: postcode availability check ─────────────────────────────────────
    # Proxied server-side to keep the BOXO API key out of the browser.

    @http.route('/cs/check_postcode', type='json', auth='public', website=True)
    def check_postcode(self, postcode=None, **kwargs):
        if not request.website.sudo().cs_enabled:
            return {'available': False}
        if not postcode:
            return {'available': False}
        postcode = postcode.replace(' ', '').upper()
        if not postcode:
            return {'available': False}

        order = request.website.sale_get_order()
        if not order:
            _logger.warning('circular_shipping: check_postcode — no active order for postcode=%s', postcode)
            return {'available': False}

        result = order.sudo().check_cs_postcode_availability(postcode)
        available = result.get('available', False)
        # Exposure funnel: last-value postcode serviceability (the helper skips
        # no-op writes, so repeated availability polls don't churn the DB).
        order.sudo()._cs_log_event(postcode_serviceable=bool(available))
        return {'available': available}

    # ── AJAX: check availability for the current order's shipping address ─────
    # Reads partner_shipping_id from the active order so the correct selected
    # address is always used, regardless of what the browser cached client-side.

    @http.route('/cs/check_current_address', type='json', auth='public', website=True)
    def check_current_address(self, **kwargs):
        if not request.website.sudo().cs_enabled:
            return {'available': False, 'postcode': ''}
        order = request.website.sale_get_order()
        if not order or not order.partner_shipping_id:
            _logger.info('circular_shipping: check_current_address — no active order or shipping partner')
            return {'available': False, 'postcode': ''}

        shipping = order.partner_shipping_id
        postcode  = (shipping.zip or '').replace(' ', '').upper()

        _logger.info(
            'circular_shipping: check_current_address — order=%s partner="%s" zip=%s',
            order.name, shipping.name, postcode,
        )

        if not postcode:
            _logger.info('circular_shipping: check_current_address — postcode is empty, available=False')
            return {'available': False, 'postcode': postcode}

        result = self.check_postcode(postcode=postcode)
        result['postcode'] = postcode

        eligible, elig_reason = order._check_cs_eligibility()
        _logger.info(
            'circular_shipping: address check result — order=%s zip=%s '
            'postcode_available=%s eligible=%s elig_reason="%s"',
            order.name, postcode, result.get('available'), eligible, elig_reason,
        )
        return result

    # ── Internal: A/B variant assignment ──────────────────────────────────────

    def _get_ab_variant(self):
        ws = request.website.sudo()
        if not ws.cs_ab_test_enabled:
            return ''
        if 'cs_ab_variant' not in request.session:
            ratio   = ws.cs_ab_split_ratio or 0.5
            sid     = request.session.sid or ''
            h       = int(hashlib.sha256(sid.encode()).hexdigest(), 16)
            variant = 'A' if (h % 1000) / 1000 < ratio else 'B'
            request.session['cs_ab_variant'] = variant
        return request.session['cs_ab_variant']
