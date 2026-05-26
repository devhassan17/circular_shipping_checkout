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

    def _get_cs_config(self):
        """Return plugin config from ir.config_parameter."""
        cfg = self.env['ir.config_parameter'].sudo()
        return {
            'deposit_amount': float(cfg.get_param('cs.deposit_amount', '3.95')),
            'single_use_fee': float(cfg.get_param('cs.single_use_fee', '0.25')),
            'pricing_model':  cfg.get_param('cs.pricing_model', 'direct'),
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

        try:
            deposit_product = self.env.ref('circular_shipping_checkout.product_packaging_deposit').product_variant_id
            fee_product     = self.env.ref('circular_shipping_checkout.product_single_use_fee').product_variant_id
        except ValueError:
            _logger.error('circular_shipping: service products not found — run module upgrade')
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
                try:
                    deposit_product = self.env.ref(
                        'circular_shipping_checkout.product_packaging_deposit'
                    ).product_variant_id
                    self._create_packaging_line(deposit_product, config['deposit_amount'])
                except ValueError:
                    _logger.error(
                        'circular_shipping: product_packaging_deposit not found during fallback'
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
        cfg = self.env['ir.config_parameter'].sudo()

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
        allowed_raw = cfg.get_param('cs.allowed_country_ids', '')
        if allowed_raw:
            allowed_ids = {int(x) for x in allowed_raw.split(',') if x.strip().isdigit()}
            country = self.partner_shipping_id.country_id
            if country and country.id not in allowed_ids:
                _logger.info(
                    'circular_shipping: eligibility — country %s not in allowlist for order %s',
                    country.code, self.name,
                )
                return False, f'Service not available in {country.name}'

        # Max-quantity cap (0 = no limit)
        max_qty = int(cfg.get_param('cs.max_products', '0') or '0')
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
        eligible, reason = self._check_cs_product_filter(cfg)
        if not eligible:
            return False, reason

        _logger.info('circular_shipping: eligibility result — order=%s eligible=True reason="Available"', self.name)
        return True, 'Available'

    def _check_cs_product_filter(self, cfg=None):
        """Three-mode product filter: all / exclude / include.

        Returns (True, 'Available') when the filter passes, or (False, reason).
        """
        self.ensure_one()
        if cfg is None:
            cfg = self.env['ir.config_parameter'].sudo()

        mode = cfg.get_param('cs.product_allow_mode', 'include')
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

        def _load_ids(param_key):
            raw = cfg.get_param(param_key, '')
            return {int(x) for x in raw.split(',') if x.strip().isdigit()} if raw else set()

        if mode == 'exclude':
            excluded_ids = _load_ids('cs.excluded_product_ids')
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
            included_ids = _load_ids('cs.included_product_ids')
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

            required_qty = int(cfg.get_param('cs.required_total_qty', '0') or '0')
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
        Config: ir.config_parameter (cs.test_mode, boxo.api_key, boxo.api_url)
        """
        self.ensure_one()
        cfg       = self.env['ir.config_parameter'].sudo()
        test_mode = cfg.get_param('cs.test_mode', 'False') == 'True'
        api_key   = cfg.get_param('boxo.api_key', '')
        api_base  = (cfg.get_param('boxo.api_url', '') or 'https://api.boxo.nu').rstrip('/')

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

        cfg = self.env['ir.config_parameter'].sudo()
        office_carrier_id_raw = cfg.get_param('cs.office_delivery_carrier_id', '')
        if not office_carrier_id_raw or not office_carrier_id_raw.strip().isdigit():
            _logger.warning(
                'circular_shipping: office delivery carrier not configured — '
                'carrier NOT swapped for reusable order %s', self.name,
            )
            return

        office_carrier = self.env['delivery.carrier'].sudo().browse(int(office_carrier_id_raw))
        if not office_carrier.exists() or not office_carrier.active:
            _logger.warning(
                'circular_shipping: office delivery carrier id=%s not found or inactive — '
                'carrier NOT swapped for reusable order %s',
                office_carrier_id_raw, self.name,
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
        """
        for order in self:
            if order.cs_packaging_type == 'reusable':
                order._cs_post_payment_carrier_swap()
            if order.cs_packaging_type and not order.order_line.filtered(lambda l: l.is_cs_packaging):
                order._apply_packaging_fee(order.cs_packaging_type)
        return super().action_confirm()
