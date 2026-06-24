# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging
import requests

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cs_packaging_type = fields.Selection(
        selection=[('reusable', 'Statiegeld verpakking'), ('single_use', 'Wegwerpverpakking')],
        string='Verpakkingskeuze',
        default=False,
    )
    cs_ab_variant = fields.Char(string='A/B Variant', default='')

    cs_prev_carrier_id = fields.Many2one(
        'delivery.carrier',
        string='Vorige bezorgmethode (CS swap)',
        copy=False,
    )

    cs_amount_packaging = fields.Monetary(
        compute='_compute_cs_amount_packaging',
        string='Packaging deposit',
        store=True,
    )
    cs_amount_surcharge = fields.Monetary(
        compute='_compute_cs_amount_surcharge',
        string='Single-use surcharge',
        store=False,
    )

    @api.depends('order_line', 'order_line.product_uom_qty',
                 'order_line.is_cs_box', 'cs_packaging_type')
    def _compute_cart_info(self):
        """Exclude the CS box line from the cart count when it is hidden (single-use selected)."""
        super()._compute_cart_info()
        for order in self:
            if order.cs_packaging_type != 'reusable':
                hidden_box_qty = int(sum(
                    l.product_uom_qty for l in order.website_order_line if l.is_cs_box
                ))
                order.cart_quantity -= hidden_box_qty

    @api.depends('order_line.is_cs_packaging', 'order_line.price_subtotal', 'cs_packaging_type')
    def _compute_cs_amount_packaging(self):
        for order in self:
            cs_total = sum(l.price_subtotal for l in order.order_line if l.is_cs_packaging)
            order.cs_amount_packaging = cs_total if order.cs_packaging_type == 'reusable' else 0.0

    @api.depends('order_line.is_cs_packaging', 'order_line.price_subtotal', 'cs_packaging_type')
    def _compute_cs_amount_surcharge(self):
        for order in self:
            cs_total = sum(l.price_subtotal for l in order.order_line if l.is_cs_packaging)
            order.cs_amount_surcharge = cs_total if order.cs_packaging_type == 'single_use' else 0.0

    def _cs_website(self):
        """Resolve the website whose CS settings apply to this order.

        Website orders carry website_id; backend/other orders fall back to the
        first website so settings are always resolvable without a request.
        """
        self.ensure_one()
        return self.website_id or self.env['website'].sudo().search([], limit=1)

    def _cs_fallback_product(self, xmlid_name):
        """Return the product.product for a module service product, or False."""
        tmpl = self.env.ref(
            f'circular_shipping_checkout.{xmlid_name}', raise_if_not_found=False,
        )
        return tmpl.product_variant_id if tmpl else False

    def _get_cs_config(self):
        """Return plugin pricing config from the order's website settings."""
        ws = self._cs_website()
        return {
            'deposit_amount': ws.cs_deposit_amount or 0.0,
            'single_use_fee': ws.cs_single_use_fee or 0.0,
            'pricing_model':  ws.cs_pricing_model or 'direct',
        }

    def _apply_packaging_fee(self, packaging_type):
        """Add or update packaging fee lines. Idempotent.

        direct model (default):
          Reusable   → deposit line shown in its own deposit row.
          Single-use → surcharge line shown in its own surcharge row.
          Both lines use is_cs_packaging=True and is_delivery=False,
          keeping packaging fully separate from shipping totals.

        via_shipping model:
          The fee is baked into the shipping carrier line price instead of
          creating a separate packaging line. See _apply_via_shipping_fee().
        """
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            _logger.warning(
                'circular_shipping: cannot apply packaging fee — order %s in state %s',
                self.name, self.state,
            )
            return

        ws = self._cs_website()
        deposit_product = ws.cs_deposit_product_id or self._cs_fallback_product('product_packaging_deposit')
        fee_product     = ws.cs_single_use_product_id or self._cs_fallback_product('product_single_use_fee')
        if not deposit_product or not fee_product:
            _logger.error('circular_shipping: service products not configured — check settings/upgrade')
            return

        # Remove all previous CS lines (deposit/surcharge rows and the CSC box item)
        self.order_line.filtered(lambda l: l.is_cs_packaging or l.is_cs_box).unlink()

        config = self._get_cs_config()
        pricing_model = config.get('pricing_model', 'direct')

        # CSC box always shown for reusable packaging, regardless of pricing model
        if packaging_type == 'reusable':
            self._create_cs_box_line()

        if pricing_model == 'via_shipping':
            self._apply_via_shipping_fee(packaging_type, config)
        else:
            # direct model (default)
            if packaging_type == 'reusable':
                self._create_packaging_line(deposit_product, config['deposit_amount'])
            else:
                # Single-use: shown in its own surcharge row, independent of delivery totals
                self._create_packaging_line(fee_product, config['single_use_fee'])

    def _apply_via_shipping_fee(self, packaging_type, config):
        """via_shipping model: adjust the delivery carrier price instead of adding a separate line.

        Reusable: discount on shipping = deposit_amount (customer pays less shipping)
        Single-use: surcharge on shipping = single_use_fee (customer pays more shipping)
        The adjustment is capped so shipping never goes below 0.

        Falls back silently to the direct deposit model when no delivery line exists yet.
        """
        delivery_lines = self.order_line.filtered(
            lambda l: l.is_delivery and not l.is_cs_packaging
        )
        if not delivery_lines:
            # No shipping line yet — fall back to direct model silently
            _logger.info(
                'circular_shipping: via_shipping selected but no delivery line found on order %s,'
                ' falling back to direct',
                self.name,
            )
            if packaging_type == 'reusable':
                deposit_product = (
                    self._cs_website().cs_deposit_product_id
                    or self._cs_fallback_product('product_packaging_deposit')
                )
                if deposit_product:
                    self._create_packaging_line(deposit_product, config['deposit_amount'])
                else:
                    _logger.error(
                        'circular_shipping: deposit product not configured during fallback'
                    )
            return

        for line in delivery_lines:
            if packaging_type == 'reusable':
                adjustment = -config['deposit_amount']
            else:
                adjustment = config['single_use_fee']

            new_price = max(0.0, line.price_unit + adjustment)
            line.write({'price_unit': new_price})
            _logger.info(
                'circular_shipping: via_shipping adjusted delivery line %s by %s → %s',
                line.id, adjustment, new_price,
            )

    def _create_packaging_line(self, product, price_unit, name=None, is_delivery=False):
        """Create a packaging line marked is_cs_packaging.

        :param is_delivery: When True the line contributes to amount_delivery and
                            appears in the delivery totals row instead of packaging row.
        """
        vals = {
            'order_id':        self.id,
            'product_id':      product.id,
            'name':            name or product.name,
            'product_uom_qty': 1,
            'price_unit':      price_unit,
            'tax_id':          [],
            'is_cs_packaging': True,
            'is_delivery':     is_delivery,
        }
        if self.order_line:
            vals['sequence'] = self.order_line[-1].sequence + 1
        self.env['sale.order.line'].sudo().create(vals)

    def _ensure_cs_box_line(self):
        """Ensure the CS box line exists before the payment page renders.

        Creates the line if missing so the row is always present in the initial
        page HTML, letting JS show/hide it without requiring a full page reload.
        Only runs for editable orders to avoid touching confirmed/locked orders.
        Skipped unless packaging type is explicitly 'reusable' — covers False,
        single_use, and any future third value, preventing an orphan box line
        from being seeded before the user has made a selection.
        """
        self.ensure_one()
        if self.state not in ('draft', 'sent'):
            return
        if self.cs_packaging_type != 'reusable':
            return
        if not self.order_line.filtered(lambda l: l.is_cs_box):
            self._create_cs_box_line()

    def _create_cs_box_line(self):
        """Add the free CSC box product line (shown in cart items list at €-)."""
        try:
            cs_box = self.env.ref('circular_shipping_checkout.product_cs_box').product_variant_id
        except ValueError:
            _logger.warning('circular_shipping: product_cs_box not found — run module upgrade')
            return
        vals = {
            'order_id':        self.id,
            'product_id':      cs_box.id,
            'name':            cs_box.name,
            'product_uom_qty': 1,
            'price_unit':      0.0,
            'tax_id':          [],
            'is_cs_box':       True,
            'is_cs_packaging': False,
            'is_delivery':     False,
        }
        if self.order_line:
            vals['sequence'] = self.order_line[-1].sequence + 1
        self.env['sale.order.line'].sudo().create(vals)

    def _check_cs_eligibility(self):
        """Check if the CS packaging widget should be shown for this order.

        Covers: pickup carrier detection, country allowlist, max-quantity cap,
        and the product inclusion filter. Does NOT call the Boxo API — that
        check runs client-side via the /cs/check_postcode AJAX route so it
        never blocks page load.

        Returns (bool, str) — (is_eligible, reason).
        """
        self.ensure_one()
        ws = self._cs_website()

        carrier = getattr(self, 'carrier_id', None)
        _logger.info(
            'circular_shipping: eligibility check — order=%s state=%s carrier=%s zip=%s',
            self.name, self.state,
            carrier.name if carrier else None,
            self.partner_shipping_id.zip if self.partner_shipping_id else None,
        )

        if not self.partner_shipping_id:
            _logger.info('circular_shipping: eligibility — no shipping address for order %s', self.name)
            return False, 'No shipping address'

        # Carrier: skip in-store pickup orders
        if carrier:
            pickup_keywords = ('pickup', 'afhalen', 'collect', 'ophalen')
            if any(kw in carrier.name.lower() for kw in pickup_keywords):
                _logger.info(
                    'circular_shipping: eligibility — pickup carrier "%s" on order %s',
                    carrier.name, self.name,
                )
                return False, 'In-store pickup — no packaging needed'

        # Country allowlist (only enforced when configured)
        allowed_countries = ws.cs_allowed_country_ids
        if allowed_countries:
            country = self.partner_shipping_id.country_id
            if country and country not in allowed_countries:
                _logger.info(
                    'circular_shipping: eligibility — country %s not in allowlist for order %s',
                    country.code, self.name,
                )
                return False, f'Service not available in {country.name}'

        # Max-quantity cap (0 = no limit)
        max_qty = ws.cs_max_products or 0
        if max_qty > 0:
            total_qty = sum(
                l.product_uom_qty for l in self.order_line
                if not l.is_delivery and not l.is_cs_packaging and not l.is_cs_box
            )
            if total_qty > max_qty:
                _logger.info(
                    'circular_shipping: eligibility — qty %s exceeds max %s for order %s',
                    int(total_qty), max_qty, self.name,
                )
                return False, f'Order has {int(total_qty)} items; maximum is {max_qty}'

        # Product inclusion filter (only enforced when configured)
        eligible, reason = self._check_cs_product_filter(ws)
        if not eligible:
            return False, reason

        _logger.info('circular_shipping: eligibility result — order=%s eligible=True reason="Available"', self.name)
        return True, 'Available'

    def _check_cs_product_filter(self, ws=None):
        """Three-mode product filter: all / exclude / include.

        Returns (True, 'Available') when the filter passes, or (False, reason).
        """
        self.ensure_one()
        if ws is None:
            ws = self._cs_website()

        mode = ws.cs_product_allow_mode or 'include'
        _logger.info(
            'circular_shipping: product filter check — order=%s mode=%s',
            self.name, mode,
        )

        if mode == 'all':
            return True, 'Available'

        # Collect physical product IDs in cart (skip delivery, CS, and service lines)
        cart_product_ids = set()
        for line in self.order_line:
            if line.is_delivery or line.is_cs_packaging or line.is_cs_box:
                continue
            if not line.product_id or line.product_id.type == 'service':
                continue
            cart_product_ids.add(line.product_id.id)

        if not cart_product_ids:
            return True, 'Available'

        if mode == 'exclude':
            excluded_ids = set(ws.cs_excluded_product_ids.ids)
            restricted = cart_product_ids & excluded_ids
            if restricted:
                names = ', '.join(self.env['product.product'].browse(list(restricted)).mapped('name'))
                _logger.info(
                    'circular_shipping: product filter — excluded product(s) in cart: %s for order %s',
                    sorted(restricted), self.name,
                )
                return False, f'Bevat uitgesloten producten: {names}'
            return True, 'Available'

        if mode == 'include':
            included_ids = set(ws.cs_included_product_ids.ids)
            if not included_ids:
                return False, 'Geen producten geconfigureerd voor statiegeld verpakking'
            unlisted = cart_product_ids - included_ids
            if unlisted:
                names = ', '.join(self.env['product.product'].browse(list(unlisted)).mapped('name'))
                _logger.info(
                    'circular_shipping: product filter — unlisted product(s) in cart: %s for order %s',
                    sorted(unlisted), self.name,
                )
                return False, f'Bevat producten die niet zijn toegestaan: {names}'

            required_qty = ws.cs_required_total_qty or 0
            if required_qty == 0:
                _logger.info(
                    'circular_shipping: product filter — required_total_qty=0, widget inactive for order %s',
                    self.name,
                )
                return False, 'Kwantiteitseis is 0 — CS widget niet actief'
            cart_qty = sum(
                int(l.product_uom_qty) for l in self.order_line
                if not l.is_delivery and not l.is_cs_packaging and not l.is_cs_box
                and l.product_id and l.product_id.id in included_ids
            )
            if cart_qty != required_qty:
                _logger.info(
                    'circular_shipping: product filter — qty mismatch: cart=%s required=%s for order %s',
                    cart_qty, required_qty, self.name,
                )
                return False, f'Bestelling bevat {cart_qty} stuks; vereist is {required_qty}'

            return True, 'Available'

        return True, 'Available'

    def check_cs_postcode_availability(self, postcode):
        """
        Check Boxo API for postcode availability.
        Pattern: boxo_return/models/sale_order.py::check_boxo_postcode_availability
        Config: website settings (cs_test_mode, boxo_api_key, boxo_api_url)
        """
        self.ensure_one()
        ws        = self._cs_website()
        test_mode = ws.cs_test_mode
        api_key   = ws.boxo_api_key or ''
        api_base  = (ws.boxo_api_url or 'https://api.boxo.nu').rstrip('/')

        if test_mode:
            _logger.info('circular_shipping: test mode — Boxo API skipped, available=True for postcode=%s', postcode)
            return {'available': True, 'reason': 'Service available (test mode)'}

        if not api_key:
            _logger.warning('circular_shipping: Boxo API key not configured — available=False for postcode=%s', postcode)
            return {'available': False, 'reason': 'API key not configured'}

        try:
            resp = requests.get(
                f'{api_base}/service-available/{postcode}',
                headers={'X-Api-Key': api_key, 'Accept': 'application/json'},
                timeout=10,
            )
            if resp.status_code == 200:
                try:
                    available = bool(resp.json().get('available', False))
                except (ValueError, KeyError):
                    _logger.error(
                        'circular_shipping: Boxo API returned invalid JSON for postcode=%s', postcode,
                    )
                    return {'available': False, 'reason': 'Invalid API response'}
                _logger.info('circular_shipping: Boxo API — postcode=%s available=%s', postcode, available)
                return {
                    'available': available,
                    'reason': 'Service available' if available else 'Service not available in this postal code',
                }
            if resp.status_code == 400:
                _logger.warning('circular_shipping: Boxo API 400 — invalid postcode format postcode=%s', postcode)
                return {'available': False, 'reason': 'Invalid postal code format'}
            if resp.status_code == 401:
                _logger.error(
                    'circular_shipping: Boxo API 401 Unauthorized — check API key in Settings → Circular Shipping, postcode=%s',
                    postcode,
                )
                return {'available': False, 'reason': 'API authentication failed'}
            if resp.status_code == 404:
                return {'available': False, 'reason': 'Service not available in this postal code'}
            _logger.error('circular_shipping: Boxo API returned %s for postcode=%s', resp.status_code, postcode)
            return {'available': False, 'reason': f'API error: {resp.status_code}'}

        except requests.Timeout:
            _logger.error('circular_shipping: Boxo API timeout — postcode=%s', postcode)
            return {'available': False, 'reason': 'API request timeout'}
        except requests.RequestException as e:
            _logger.warning('circular_shipping: Boxo API connection failed — postcode=%s error=%s', postcode, e)
            return {'available': False, 'reason': 'API connection failed'}

    def _cs_post_payment_carrier_swap(self):
        """Switch carrier_id to the configured office carrier at order confirmation.

        Called before super().action_confirm() so that stock pickings and downstream
        integrations (Monta) always see the office carrier for reusable orders.
        Only writes carrier_id — never reprices or touches order lines.
        Idempotent; logs a warning and returns silently when the office carrier is
        missing or inactive so a payment that already succeeded is never blocked.
        """
        self.ensure_one()
        if self.cs_packaging_type != 'reusable':
            return

        office_carrier = self._cs_website().cs_office_delivery_carrier_id
        if not office_carrier:
            _logger.warning(
                'circular_shipping: office delivery carrier not configured — '
                'carrier NOT swapped for reusable order %s', self.name,
            )
            return

        if not office_carrier.active:
            _logger.warning(
                'circular_shipping: office delivery carrier "%s" inactive — '
                'carrier NOT swapped for reusable order %s',
                office_carrier.name, self.name,
            )
            return

        current_carrier = getattr(self, 'carrier_id', False)
        if current_carrier == office_carrier:
            return

        if current_carrier and not self.cs_prev_carrier_id:
            self.sudo().write({'cs_prev_carrier_id': current_carrier.id})

        self.sudo().write({'carrier_id': office_carrier.id})
        _logger.info(
            'circular_shipping: carrier swapped to office carrier "%s" on reusable order %s at confirmation',
            office_carrier.name, self.name,
        )

    def action_confirm(self):
        """Swap carrier and apply packaging fee at confirmation.

        The carrier swap runs BEFORE super() so that stock pickings and Monta
        receive the office carrier. Reusable orders are never routed to Monta.
        Orders that never passed through the CS widget (cs_packaging_type=False)
        are left untouched.

        Also stamps the exposure funnel's stage 4 (payment confirmed). We capture
        which orders were *confirmable* BEFORE super() so we only stamp orders that
        actually transitioned draft/sent -> sale on THIS call. This covers both
        paid orders (confirmed via the payment flow) and free website orders
        (confirmed via _validate_order), and avoids double-stamping when
        action_confirm runs again on an already-confirmed order.
        """
        was_confirmable = {order.id: order.state in ('draft', 'sent') for order in self}
        for order in self:
            if order.cs_packaging_type == 'reusable':
                order._cs_post_payment_carrier_swap()
            if order.cs_packaging_type and not order.order_line.filtered(lambda l: l.is_cs_packaging):
                order._apply_packaging_fee(order.cs_packaging_type)
        res = super().action_confirm()
        now = fields.Datetime.now()
        for order in self:
            if was_confirmable.get(order.id) and order.state == 'sale':
                order._cs_log_event(
                    stage4_payment_confirmed_ts=now,
                    order_total=order.amount_total,
                )
        return res

    # ── Exposure funnel tracking ──────────────────────────────────────────────
    # The exposure event is keyed by order_id (NOT the HTTP session) so stages 3/4
    # resolve the row even in payment-provider webhook/redirect contexts that carry
    # no browser session. Timestamps are stamp-once; booleans are last-value.
    # Writes go through sudo() and never raise into the checkout/payment flow.

    # Datetime fields that must only be set the first time (never overwritten).
    _CS_STAMP_ONCE_FIELDS = (
        'stage1_payment_page_ts',
        'stage2_widget_ts',
        'stage3_proceed_payment_ts',
        'stage4_payment_confirmed_ts',
        'choice_ts',
    )

    def _cs_log_event(self, create_if_missing=False, **vals):
        """Upsert each order's exposure event. Never raises into the caller.

        Only stage 1 (the payment-page hook) passes create_if_missing=True. Every
        later hook (stages 3/4, capture, choice, postcode) updates an existing row
        but never creates one, so backend / non-website orders that never reached
        the payment page do not pollute the table.
        """
        for order in self:
            try:
                order._cs_log_event_one(create_if_missing=create_if_missing, **vals)
            except Exception:
                _logger.exception(
                    'circular_shipping: exposure tracking failed for order %s', order.id,
                )

    def _cs_log_event_one(self, create_if_missing=False, **vals):
        self.ensure_one()
        Event = self.env['cs.exposure.event'].sudo()
        event = Event.search([('order_id', '=', self.id)], limit=1)
        if not event:
            if not create_if_missing:
                return
            base = {
                'order_id':   self.id,
                'order_ref':  self.name,
                'website_id': self.website_id.id or False,
                'ab_variant': self.cs_ab_variant or '',
                'order_total': self.amount_total,
                'line_count': len(self.order_line.filtered(
                    lambda l: not l.is_delivery and not l.is_cs_packaging and not l.is_cs_box
                )),
            }
            if 'session_key' in vals:
                base['session_key'] = vals['session_key']
            # Concurrent requests (payment render + availability + choice) can race
            # to create the row. The unique(order_id) constraint makes the loser
            # raise; recover inside a savepoint and re-read the winner's row.
            try:
                with self.env.cr.savepoint():
                    event = Event.create(base)
            except Exception:
                event = Event.search([('order_id', '=', self.id)], limit=1)
        if not event:
            return

        write_vals = {}
        for key, value in vals.items():
            if key == 'session_key':
                continue  # only set on create
            if key in self._CS_STAMP_ONCE_FIELDS and event[key]:
                continue  # stamp-once: keep the first value
            if event[key] == value:
                continue  # last-value: skip no-op writes (collapses poll churn)
            write_vals[key] = value
        if write_vals:
            event.write(write_vals)
