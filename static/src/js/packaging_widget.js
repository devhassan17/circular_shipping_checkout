/** @odoo-module **/
/**
 * Circular Shipping — Packaging choice widget for Odoo v17 eCommerce.
 *
 * Follows the same pattern as website_sale_delivery.js:
 *  1. User selects an option → POST /cs/set_packaging_choice (JSON-RPC)
 *  2. Server returns new_amount_total / _untaxed / _tax
 *  3. JS updates the matching monetary_field spans in the totals table
 *
 * @author Circular Shipping <info@circularshipping.nl>
 */

const VALID_POSTCODE = /^\d{4}\s?[A-Za-z]{2}$/;

const I18N = {
    nl: { moreInfo: 'Meer informatie' },
    de: { moreInfo: 'Mehr Informationen' },
    en: { moreInfo: 'More information' },
};

// Locate the order-line <tr> that belongs to the CS box product.
// Primary strategy: match Odoo's product image URL which always contains the
// product.product variant ID, even when no custom image has been uploaded.
// Fallback: any <tr> whose text content includes the product name.
function findCsBoxRows() {
    const widget = document.getElementById('cs-packaging-widget');
    const dataEl = document.getElementById('cs-payment-popup-data');
    const sourceEl = widget || dataEl;
    if (!sourceEl) return [];
    const productId   = sourceEl.dataset.csBoxProductId   || '';
    const productName = sourceEl.dataset.csBoxProductName || '';
    const rows = [];

    if (productId && productId !== '0') {
        document.querySelectorAll(
            `img[src*="/web/image/product.product/${productId}/"]`
        ).forEach(img => {
            const row = img.closest('tr');
            if (row && !rows.includes(row)) rows.push(row);
        });
    }

    if (rows.length === 0 && productName) {
        document.querySelectorAll('tr').forEach(tr => {
            if (tr.textContent.includes(productName) && !rows.includes(tr)) rows.push(tr);
        });
    }

    return rows;
}

function updateCsBoxVisibility(show) {
    findCsBoxRows().forEach(row => { row.style.display = show ? '' : 'none'; });
}

// Update the "X artikelen" span in the order-summary accordion header.
// Accepts the server-authoritative quantity so that multi-unit lines are
// counted correctly (DOM rows cannot reliably provide per-line quantities
// on the checkout/payment summary where qty fields are read-only text).
// Finds the first span in the accordion button whose text starts with a digit,
// so it works regardless of exact page structure.
function _resyncSummaryCount(qty) {
    const btn = document.querySelector('#o_wsale_total_accordion .accordion-button');
    if (!btn) return;
    for (const span of btn.querySelectorAll('span')) {
        if (/^\d/.test(span.textContent.trim())) {
            span.textContent = span.textContent.trim().replace(/^\d+/, qty);
            return;
        }
    }
}

// Update every element that is displaying the cart item count.
// Targets .my_cart_quantity (Odoo's canonical cart-count class used in the nav
// icon, payment-page summary badge, and mini-cart header) and any element
// with data-cs-item-count (our own explicit marker).
// Odoo's OWL cart component may re-render and overwrite our DOM write; the
// MutationObserver re-asserts the value for up to 500ms after the update.
function updateCartCount(qty) {
    const selector = '.my_cart_quantity, [data-cs-item-count]';
    document.querySelectorAll(selector).forEach(el => {
        el.textContent = qty;
    });

    const parents = new Set();
    document.querySelectorAll(selector).forEach(el => {
        if (el.parentElement) parents.add(el.parentElement);
    });
    if (parents.size === 0) return;

    const observer = new MutationObserver(() => {
        document.querySelectorAll(selector).forEach(el => {
            if (el.textContent !== String(qty)) {
                el.textContent = qty;
            }
        });
    });
    parents.forEach(parent => {
        observer.observe(parent, { childList: true, subtree: true, characterData: true });
    });
    setTimeout(() => observer.disconnect(), 500);
}

// Recount currently-visible order-line rows and update all count displays.
// Only used on the cart page (#cart_products); the delivery/checkout page
// renders the initial count server-side so no DOM sync is needed there.
// (A delivery-page fallback was removed: it counted total/subtotal rows as
//  product rows and fed a wrong count into updateCartCount, which caused both
//  a stale display and a cascade of Odoo OWL re-renders slowing the page.)
function syncCartCountFromDOM() {
    const rows = document.querySelectorAll('#cart_products tr');
    const visible = Array.from(rows).filter(
        r => r.style.display !== 'none' && !r.classList.contains('d-none') && r.querySelector('td')
    );
    if (visible.length > 0) {
        updateCartCount(visible.length);
    }
}


function csrfToken() {
    return (window.odoo && odoo.csrf_token) || '';
}

async function rpc(route, params) {
    const res = await fetch(route, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify({ jsonrpc: '2.0', method: 'call', id: 1, params }),
    });
    const data = await res.json();
    return data.result;
}

function updateTotals(result) {
    if (!result || !result.ok) return;

    // Deposit row — shows for reusable (€3.95), hidden for single-use
    const depositRow    = document.getElementById('order_cs_packaging');
    const depositAmount = document.querySelector('#order_cs_packaging .monetary_field');
    if (depositRow) {
        depositRow.style.display = result.has_packaging ? '' : 'none';
        if (result.has_packaging && depositAmount && result.new_amount_packaging) {
            depositAmount.innerHTML = result.new_amount_packaging;
        }
    }

    // Surcharge row — shows for single-use, hidden for reusable
    const surchargeRow    = document.getElementById('order_cs_surcharge');
    const surchargeAmount = document.querySelector('#order_cs_surcharge .monetary_field');
    if (surchargeRow) {
        surchargeRow.style.display = result.has_surcharge ? '' : 'none';
        if (result.has_surcharge && surchargeAmount && result.new_amount_surcharge) {
            surchargeAmount.innerHTML = result.new_amount_surcharge;
        }
    }

    // Order totals
    const untaxed = document.querySelector('#order_total_untaxed .monetary_field');
    const tax     = document.querySelector('#order_total_taxes .monetary_field');
    const totals  = document.querySelectorAll('#order_total .monetary_field, #amount_total_summary.monetary_field');

    if (untaxed && result.new_amount_untaxed) untaxed.innerHTML = result.new_amount_untaxed;
    if (tax     && result.new_amount_tax)     tax.innerHTML     = result.new_amount_tax;
    totals.forEach(el => { if (result.new_amount_total) el.innerHTML = result.new_amount_total; });

    // Show/hide the CSC box line in the product list
    if (result.show_cs_box !== undefined) {
        updateCsBoxVisibility(result.show_cs_box);
    }

    // Update cart item count in all known display locations.
    if (result.new_cart_quantity !== undefined) {
        updateCartCount(result.new_cart_quantity);
        _resyncSummaryCount(result.new_cart_quantity);
    }
}

async function clearAndRefresh() {
    const result = await rpc('/cs/clear_packaging_choice', {});
    updateTotals(result || { ok: true, has_packaging: false, has_surcharge: false, show_cs_box: false });
    await refreshOrderSummary(false);
}

// Fetch the current page and splice the updated order-line and summary sections
// into the live DOM. Runs after a confirmed packaging choice change so that
// newly created or removed order lines (CS box, deposit, surcharge) are
// reflected without a full page reload.
async function refreshOrderSummary(showCsBox) {
    try {
        const response = await fetch(window.location.href);
        if (!response.ok) return;
        const html = await response.text();
        const doc = new DOMParser().parseFromString(html, 'text/html');

        // Cart summary sidebar (totals + line items on payment/checkout page)
        const cartSummary    = document.querySelector('#o_cart_summary');
        const newCartSummary = doc.querySelector('#o_cart_summary');
        if (cartSummary && newCartSummary) cartSummary.innerHTML = newCartSummary.innerHTML;

        // Product rows table (present on both cart and checkout pages)
        const cartBody    = document.querySelector('#cart_products tbody');
        const newCartBody = doc.querySelector('#cart_products tbody');
        if (cartBody && newCartBody) cartBody.innerHTML = newCartBody.innerHTML;

        // Item count in the order summary accordion header ("X artikelen")
        const countEl    = document.querySelector('#o_wsale_total_accordion .accordion-button .d-flex span:first-child');
        const newCountEl = doc.querySelector('#o_wsale_total_accordion .accordion-button .d-flex span:first-child');
        if (countEl && newCountEl) countEl.textContent = newCountEl.textContent;

        // Re-attach the popup button (DOM was replaced above)
        injectCsBoxPopup();
        // Re-apply current box-row visibility (server renders it visible by default)
        updateCsBoxVisibility(showCsBox);
    } catch (_) {
        // Non-fatal — totals were already updated by updateTotals()
    }
}

function setActiveRadio(widget, value) {
    widget.querySelectorAll('input[name="cs_packaging_choice"]').forEach((radio) => {
        radio.checked = radio.value === value;
        const row = radio.closest('.form-check') || radio.parentElement;
        if (row) row.style.fontWeight = radio.checked ? '600' : 'normal';
    });
}

function showWidget(widget, visible) {
    widget.style.display = visible ? 'block' : 'none';
}

function injectCsBoxPopup() {
    const widget = document.getElementById('cs-packaging-widget');
    const dataEl = document.getElementById('cs-payment-popup-data');
    const sourceEl = widget || dataEl;
    if (!sourceEl) return;

    const infoPopup = document.getElementById('cs-info-popup')
        || (dataEl && dataEl.querySelector('.cs-info-popup'));
    if (!infoPopup) return;

    const popupHTML = infoPopup.innerHTML;
    const productName = sourceEl.dataset.csBoxProductName || '';
    if (!productName || !popupHTML.trim()) return;

    findCsBoxRows().forEach((row) => {
        if (row.querySelector('.cs-info-wrapper')) return;

        let nameCell = null;
        row.querySelectorAll('td').forEach(td => {
            if (!nameCell && td.textContent.includes(productName)) nameCell = td;
        });
        if (!nameCell) return;

        // Find the innermost element containing the product name so the button
        // is appended inside it and stays in the same inline text flow.
        // Inserting as a sibling fails when Odoo wraps the cell in a
        // flex-column container — the wrapper becomes a new flex item and
        // drops to the next line.
        let nameEl = null;
        let bestTextLen = Infinity;
        for (const el of nameCell.querySelectorAll('*')) {
            const text = el.textContent.trim();
            if (text.includes(productName) && text.length < bestTextLen) {
                bestTextLen = text.length;
                nameEl = el;
            }
        }

        const wrapper = document.createElement('span');
        wrapper.className = 'cs-info-wrapper';

        const btn = document.createElement('button');
        btn.type = 'button';
        btn.className = 'cs-info-btn';
        btn.setAttribute('aria-label', (I18N[sourceEl.dataset.lang] || I18N.en).moreInfo);
        btn.setAttribute('aria-expanded', 'false');
        btn.textContent = 'i';

        const popup = document.createElement('div');
        popup.className = 'cs-info-popup';
        popup.innerHTML = popupHTML;

        wrapper.appendChild(btn);
        wrapper.appendChild(popup);

        if (nameEl) {
            nameEl.appendChild(wrapper);
        } else {
            nameCell.appendChild(wrapper);
        }

        btn.addEventListener('click', (e) => {
            e.stopPropagation();
            e.preventDefault();  // prevent <a> navigation when button is inside a link
            const isOpen = popup.style.display === 'block';
            popup.style.display = isOpen ? 'none' : 'block';
            btn.setAttribute('aria-expanded', String(!isOpen));
        });

        document.addEventListener('click', () => {
            if (popup.style.display === 'block') {
                popup.style.display = 'none';
                btn.setAttribute('aria-expanded', 'false');
            }
        });
    });
}

async function initWidget() {
    const widget = document.getElementById('cs-packaging-widget');
    if (!widget) return;

    const testMode   = widget.dataset.testMode !== 'False';
    const selected   = (widget.dataset.selected || '').trim();
    const defaultSel = (widget.dataset.default  || 'single_use').trim();

    // Stop Odoo's checkout.js 'click .card' address-change handler from
    // intercepting clicks inside our widget (our div previously had class="card").
    widget.addEventListener('click', (e) => e.stopPropagation());

    // Info popup toggle
    const infoBtn = widget.querySelector('#cs-info-toggle');
    const infoPopup = widget.querySelector('#cs-info-popup');
    if (infoBtn && infoPopup) {
        infoBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            const isOpen = infoPopup.style.display === 'block';
            infoPopup.style.display = isOpen ? 'none' : 'block';
            infoBtn.setAttribute('aria-expanded', String(!isOpen));
        });
        document.addEventListener('click', () => {
            if (infoPopup.style.display === 'block') {
                infoPopup.style.display = 'none';
                infoBtn.setAttribute('aria-expanded', 'false');
            }
        });
    }
    injectCsBoxPopup();

    // Start hidden — we'll show once we know the service is available
    showWidget(widget, false);

    // Restore previous selection if one was persisted server-side
    setActiveRadio(widget, selected || defaultSel);

    // Determine availability ─────────────────────────────────────────────────
    // Always read the shipping address from the server so that the currently
    // selected address (partner_shipping_id) is used, not a cached client value.
    let available = false;
    if (testMode) {
        // Test mode: show unconditionally (no API call needed)
        available = true;
    } else {
        const res = await rpc('/cs/check_current_address', {});
        available = !!(res && res.available);
    }
    showWidget(widget, available);
    let isCurrentlyAvailable = available;

    // Re-check eligibility when user selects a different saved shipping address.
    //
    // Root cause: Odoo 18 address cards use .js_change_address click handlers —
    // there are no radio inputs in the address section. A 'change' listener or
    // fetch interceptor on window.fetch both miss the update entirely.
    //
    // Layer 1 — click on .js_change_address card: fires immediately when the user
    //   selects a new address (fast path, fires before the AJAX round-trip).
    // Layer 2 — MutationObserver on .oe_website_sale: catches the delivery section
    //   rebuild that always follows /shop/update_address (backup, covers edge cases
    //   like programmatic address changes or future Odoo refactors).
    // Shared debounce collapses both layers into a single RPC call per change.

    let _addrCheckTimer = null;
    const _scheduleAddrCheck = () => {
        clearTimeout(_addrCheckTimer);
        _addrCheckTimer = setTimeout(async () => {
            try {
                const res = await rpc('/cs/check_current_address', {});
                const nowAvailable = !!(res && res.available);
                const wasAvailable = isCurrentlyAvailable;
                isCurrentlyAvailable = nowAvailable;
                if (!nowAvailable && wasAvailable) {
                    await clearAndRefresh();
                } else if (nowAvailable && !wasAvailable) {
                    const result = await rpc('/cs/set_packaging_choice', { choice: currentChoice });
                    if (result && result.ok) {
                        updateTotals(result);
                        await refreshOrderSummary(currentChoice === 'reusable');
                    }
                }
                showWidget(widget, nowAvailable);
            } catch (_) {}
        }, 400);
    };

    // Layer 1: Odoo 18 address cards use click handlers (no radio inputs).
    // The selected card loses .js_change_address; unselected cards have it.
    // Clicking any .js_change_address card triggers the address update flow.
    document.addEventListener('click', (e) => {
        if (testMode) return;
        if (e.target.closest('[name="address_card"].js_change_address')) {
            _scheduleAddrCheck();
        }
    });

    // Layer 2: MutationObserver on the checkout/payment form.
    // We watch for childList mutations only (not attribute changes), so our own
    // showWidget() calls (which only set style.display) do not re-trigger the
    // observer and there is no feedback loop.
    if (!testMode) {
        const _checkoutRoot = document.querySelector(
            'form[action*="/shop/checkout"], form[action*="/shop/payment"], ' +
            '#o_wsale_checkout, .oe_website_sale'
        );
        if (_checkoutRoot) {
            new MutationObserver((mutations) => {
                // Ignore mutations that originate inside our own widget or the
                // deposit/surcharge rows we control — those are side-effects of
                // our own updateTotals() calls, not address changes.
                const allOwn = mutations.every(m =>
                    widget.contains(m.target) || m.target === widget ||
                    m.target.id === 'order_cs_packaging' ||
                    m.target.id === 'order_cs_surcharge'
                );
                if (!allOwn) _scheduleAddrCheck();
            }).observe(_checkoutRoot, { childList: true, subtree: true });
        }
    }

    // Restore correct box-row visibility based on the persisted server-side
    // choice.  The row is always rendered in the initial HTML (the server
    // ensures it), so this must happen before any AJAX call could alter it.
    updateCsBoxVisibility(selected === 'reusable');

    // Also react to an editable postcode field if present (e.g. combined checkout
    // where the user fills in a new address rather than selecting a saved one).
    const postcodeInput = document.querySelector(
        'input[name="zip"], input[name="zipcode"], input[id*="zip"]'
    );
    if (postcodeInput) {
        async function onPostcodeInput() {
            try {
                const pc = postcodeInput.value.replace(/\s/g, '').toUpperCase();
                if (testMode) {
                    const nowAvailable = pc.length >= 4;
                    const wasAvailable = isCurrentlyAvailable;
                    isCurrentlyAvailable = nowAvailable;
                    if (!nowAvailable && wasAvailable) {
                        await clearAndRefresh();
                    }
                    showWidget(widget, nowAvailable);
                } else if (pc.length >= 4) {
                    const res = await rpc('/cs/check_postcode', { postcode: pc });
                    const nowAvailable = !!(res && res.available);
                    const wasAvailable = isCurrentlyAvailable;
                    isCurrentlyAvailable = nowAvailable;
                    if (!nowAvailable && wasAvailable) {
                        await clearAndRefresh();
                    } else if (nowAvailable && !wasAvailable) {
                        const result = await rpc('/cs/set_packaging_choice', { choice: currentChoice });
                        if (result && result.ok) {
                            updateTotals(result);
                            await refreshOrderSummary(currentChoice === 'reusable');
                        }
                    }
                    showWidget(widget, nowAvailable);
                }
            } catch (_) {}
            // Don't hide on partial input — wait until we have something to send
        }
        let _postcodeTimer = null;
        postcodeInput.addEventListener('input', () => {
            clearTimeout(_postcodeTimer);
            _postcodeTimer = setTimeout(onPostcodeInput, 600);
        });
        postcodeInput.addEventListener('change', onPostcodeInput);
    }

    // Wire radio buttons ─────────────────────────────────────────────────────
    // Track the last confirmed server-side choice so we can revert on failure.
    let currentChoice = selected || defaultSel;
    let inflight = false;

    widget.querySelectorAll('input[name="cs_packaging_choice"]').forEach((radio) => {
        radio.addEventListener('change', async () => {
            if (inflight) return;
            inflight = true;

            const prevChoice = currentChoice;
            setActiveRadio(widget, radio.value);
            widget.querySelectorAll('input[name="cs_packaging_choice"]').forEach(r => r.disabled = true);

            try {
                const result = await rpc('/cs/set_packaging_choice', { choice: radio.value });
                if (result && result.ok) {
                    currentChoice = radio.value;
                    updateTotals(result);
                    await refreshOrderSummary(radio.value === 'reusable');
                } else {
                    // Server rejected (e.g. rate-limit) — revert so the radio is
                    // clickable again (a checked radio never fires 'change').
                    setActiveRadio(widget, prevChoice);
                }
            } catch (_) {
                setActiveRadio(widget, prevChoice);
            } finally {
                widget.querySelectorAll('input[name="cs_packaging_choice"]').forEach(r => r.disabled = false);
                inflight = false;
            }
        });
    });

    // If no choice has been persisted yet, silently apply the default so the
    // order total is always in sync when the user arrives at the payment page.
    if (!selected && available) {
        try {
            const result = await rpc('/cs/set_packaging_choice', { choice: defaultSel });
            if (result && result.ok) {
                currentChoice = defaultSel;
                updateTotals(result);
                await refreshOrderSummary(defaultSel === 'reusable');
            }
        } catch (_) {
            // Silently ignore — the user can still make a manual selection.
        }
    }
}

function initPaymentPagePopup() {
    if (document.getElementById('cs-payment-popup-data')) injectCsBoxPopup();
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => { initWidget(); initPaymentPagePopup(); });
} else {
    initWidget();
    initPaymentPagePopup();
}

