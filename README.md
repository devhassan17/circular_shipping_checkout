# circular_shipping_checkout

> **Note:** This directory is the active Odoo.sh deployment copy.
> The canonical source is at `platforms/odoo/18.0/circular_shipping_checkout/`.
>
> When making changes, edit `platforms/odoo/18.0/` and sync here.
> Do not edit this directory directly except for emergency production fixes.

Reusable vs single-use packaging choice at checkout, with a refundable deposit,
a single-use surcharge, postcode availability via the BOXO API, a product/country
eligibility filter, and an automatic delivery-carrier swap that keeps reusable
orders away from Monta.

---

## Master switch (`cs_enabled`)

`cs_enabled` is a per-`website` boolean (Settings → Circular Shipping → "Plugin
status"). When **off**, the storefront must behave exactly as if the module were
not installed: no widget, no rows, no fees, no carrier swap, no eligibility logic.
Every plugin entry point is gated on it.

```
                        cs_enabled (website field, default False)
                                      │
            ┌─────────────────────────┼─────────────────────────────┐
            │ ON                      │                              │ OFF
            ▼                         ▼                              ▼
  widget renders,            AJAX routes work,           ALL entry points early-return:
  rows render,               box line seeded,            _cs_get_payment_values → empty dict
  fees applied,              eligibility runs             (cs_show_packaging_row = False)
  carrier swaps                                          set/clear/check routes → no-op
                                                          cart()/cart_update_json() → skip
                                                          shop_payment() → no box line
                                                          action_confirm() → no swap/fee
```

Gated entry points (each checks `website.cs_enabled` / `order._cs_website().cs_enabled`):

| Layer       | Entry point                          | When OFF |
|-------------|--------------------------------------|----------|
| Controller  | `_cs_get_payment_values`             | returns all-empty values → nothing renders |
| Controller  | `cart`                               | skips `_cs_clear_packaging` |
| Controller  | `shop_payment`                       | skips `_ensure_cs_box_line` |
| Controller  | `cart_update_json`                   | skips eligibility check + log |
| Controller  | `set_packaging_choice`               | `{ok: False, error: plugin_disabled}` |
| Controller  | `clear_packaging_choice`             | `{ok: True}` no-op |
| Controller  | `check_postcode` / `check_current_address` | `{available: False}` |
| Model       | `action_confirm`                     | no carrier swap, no fee re-application |

---

## Data model — where settings and order state live

```
 res.config.settings (TransientModel)          website (persistent)
 ──────────────────────────────────            ─────────────────────────────
 cs_enabled            ─ related ─────────────► cs_enabled
 cs_test_mode          ─ related ─────────────► cs_test_mode
 boxo_api_key / _url   ─ related ─────────────► boxo_api_key / boxo_api_url
 cs_deposit_amount     ─ related ─────────────► cs_deposit_amount
 cs_single_use_fee     ─ related ─────────────► cs_single_use_fee
 cs_pricing_model      ─ related ─────────────► cs_pricing_model  (direct | via_shipping)
 cs_default_selection  ─ related ─────────────► cs_default_selection
 cs_popup_text_{nl,en,de}                       (+ explainer_* per language)
 cs_allowed_country_ids / cs_max_products
 cs_product_allow_mode (all|exclude|include)
 cs_excluded/included_product_ids
 cs_required_total_qty
 cs_office_delivery_carrier_id  ───────────────► delivery.carrier (cs_is_office_carrier)
 cs_box_image_url / cs_dark_mode

 Why related (not ir.config_parameter): a related field is only written when the
 saving panel's form actually contains it, so saving an UNRELATED Odoo settings
 page can no longer silently wipe m2m / m2o CS fields. (See website.py header.)

 sale.order                          sale.order.line
 ─────────────────────────           ──────────────────────────────
 cs_packaging_type (reusable|        is_cs_packaging  → deposit/surcharge line
   single_use|False)                                    (in totals, NOT cart list)
 cs_ab_variant                       is_cs_box        → free CSC box product line
 cs_prev_carrier_id                                     (visible in cart list)
 cs_amount_packaging  (computed, stored)
 cs_amount_surcharge  (computed)
```

---

## Flow 1 — Cart page

```
 GET /shop/cart
      │
      ▼
 cart()  ──[cs_enabled?]──no──► super().cart()   (plugin dormant)
      │ yes
      ▼
 _cs_clear_packaging()                  reset before a fresh checkout flow:
      └─ unlink is_cs_packaging + is_cs_box lines
         write cs_packaging_type = False
      ▼
 super().cart()


 POST /shop/cart/update_json (add/remove product)
      │
      ▼
 super().cart_update_json()  →  result
      │
      └─[cs_enabled?]──yes──► _check_cs_eligibility() → log (eligible, reason)
                              (advisory logging only; no state change)
```

---

## Flow 2 — Checkout / delivery page (widget render)

```
 GET /shop/checkout
      │
      ▼
 _prepare_checkout_page_values(order)
      │
      ├─[cs_enabled?]──yes──► order._ensure_cs_box_line()   (only if type == reusable)
      │
      ▼
 _cs_get_payment_values(order)
      │
      ├─[cs_enabled?]──no──► return ALL-EMPTY dict
      │                       cs_show_packaging_row = False  ──► no widget, no rows
      │ yes
      ▼
 build values:
   cs_packaging_config (allowlisted: deposit_amount, single_use_fee,
                        pricing_model, default_selection)
   cs_show_packaging_row = order._check_cs_eligibility()[0]   ◄── eligibility gate
   cs_lang, cs_popup_text (per lang), cs_partner_zip,
   cs_box_product_id/name, cs_dark_mode, cs_ab_variant
      │
      ▼
 QWeb templates (templates.xml)
   t-if="cs_show_packaging_row":
     • packaging_widget         (radio: reusable / single_use)
     • total_cs_packaging row   (deposit €, shown for reusable)
     • total_cs_surcharge row   (surcharge €, shown for single_use)
     • payment_popup_data       (hidden ⓘ popup HTML + box product ids)
      │
      ▼
 packaging_widget.js  (only acts if #cs-packaging-widget exists in DOM)
```

---

## Flow 3 — User picks a packaging option (live, no reload)

```
 user clicks radio  ──►  packaging_widget.js
      │
      ▼
 POST /cs/set_packaging_choice  {choice}
      │
      ├─[cs_enabled?]──no──► {ok:False, error:'plugin_disabled'}
      ├─[<500ms since last?]─► {ok:False, error:'too_many_requests'}
      ├─[choice not in (reusable,single_use)]─► {ok:False, error:'invalid_choice'}
      │ ok
      ▼
 order.write(cs_packaging_type = choice)
 order._apply_packaging_fee(choice) ──────────────┐
      │                                            │
      │   ┌────────────────────────────────────────┘
      │   ▼  _apply_packaging_fee (idempotent: unlink old CS lines first)
      │      pricing_model == 'via_shipping'?
      │        ├─ yes → adjust delivery carrier price_unit
      │        │        reusable: −deposit   single_use: +fee   (clamped ≥ 0)
      │        │        (falls back to direct if no delivery line yet)
      │        └─ no  → 'direct' model:
      │                 reusable   → _create_packaging_line(deposit_product, deposit_amount)
      │                              + _create_cs_box_line()  (free box, qty 1)
      │                 single_use → _create_packaging_line(fee_product, single_use_fee)
      ▼
 response: re-rendered monetary HTML for
   packaging row, surcharge row, untaxed, tax, total, cart quantity,
   show_cs_box (true only for reusable)
      │
      ▼
 JS updates the matching totals spans + shows/hides the CSC box cart row


 POST /cs/clear_packaging_choice   (navigated away / deselected)
      └─[cs_enabled?]──► unlink CS lines, cs_packaging_type=False, return zeroed totals
```

---

## Flow 4 — Postcode availability (BOXO)

```
 JS (on widget load / address change)
      │
      ▼
 POST /cs/check_postcode {postcode}     or    POST /cs/check_current_address
      │                                              │ reads order.partner_shipping_id.zip
      ├─[cs_enabled?]──no──► {available:False}        │
      │ yes                                           ▼
      ▼                                        check_postcode(zip)
 order.check_cs_postcode_availability(postcode)
      │
      ├─ cs_test_mode?  ──► {available:True}  (no API call; any valid NL zip)
      ├─ no api_key?    ──► {available:False, 'API key not configured'}
      ▼
 GET {boxo_api_url}/service-available/{zip}   header: X-Api-Key
      200 → {available: body.available}
      400 → invalid postcode    401 → auth failed    404 → not available
      timeout / conn error → {available:False}
      (API key never leaves the server — proxied server-side.)
```

---

## Flow 5 — Eligibility gate (`_check_cs_eligibility`)

Decides whether `cs_show_packaging_row` is true. The BOXO postcode check is NOT
part of this — it runs client-side so it never blocks page load.

```
 _check_cs_eligibility(order)
      │
      ├─ no shipping address?                 ──► (False, 'No shipping address')
      ├─ carrier name ~ pickup/afhalen/        ──► (False, 'In-store pickup')
      │   collect/ophalen?
      ├─ cs_allowed_country_ids set AND        ──► (False, 'not available in <country>')
      │   shipping country not in it?
      ├─ cs_max_products > 0 AND cart qty >    ──► (False, 'max is N')
      │   max?
      ▼
 _check_cs_product_filter(mode = all | exclude | include)
      all      → (True)
      exclude  → any cart product in cs_excluded_product_ids? → (False)
      include  → cs_included_product_ids empty?               → (False)
                 any cart product NOT in the list?            → (False)
                 cs_required_total_qty == 0?                  → (False, widget inactive)
                 cart qty of listed products != required_qty? → (False)
                 else                                          → (True)
      │
      ▼
 (True, 'Available')   ──►  widget + rows render
```

---

## Flow 6 — Order confirmation (carrier swap + Monta routing)

```
 payment success → action_confirm()
      │
      └─ for each order:
           ├─[cs_enabled?]──no──► skip entirely (behaves as uninstalled)
           │ yes
           ├─ cs_packaging_type == 'reusable'?
           │     └─► _cs_post_payment_carrier_swap()    (BEFORE super())
           │           save current carrier → cs_prev_carrier_id
           │           carrier_id = cs_office_delivery_carrier_id
           │           ► reusable orders ship via office carrier, NEVER to Monta
           │           (no-op + warning if office carrier missing/inactive;
           │            never blocks an already-paid order)
           │
           ├─ cs_packaging_type set AND no is_cs_packaging line yet?
           │     └─► _apply_packaging_fee(type)   (safety net if fee was lost)
           ▼
      super().action_confirm()
           single_use / no type → normal carrier → Monta as usual
```

---

## File map

```
controllers/main.py        HTTP routes, payment-page values, AJAX endpoints, all
                           controller-layer cs_enabled gating
models/website.py          persistent settings storage + cs_box_image sync hook
models/res_config_settings.py  settings-UI proxies (related → website)
models/sale_order.py       fees, eligibility, BOXO call, carrier swap, action_confirm
models/sale_order_line.py  is_cs_packaging / is_cs_box flags + cart visibility
models/delivery_carrier.py cs_is_office_carrier flag
views/templates.xml        widget + deposit/surcharge rows + popup data (QWeb)
views/res_config_settings_views.xml   Settings → Circular Shipping panel
data/product_data.xml      deposit, single-use fee, and CSC box service products
static/src/js/packaging_widget.js      front-end interactions
```
