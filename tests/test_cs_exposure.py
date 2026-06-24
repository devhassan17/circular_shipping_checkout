# -*- coding: utf-8 -*-
"""Tests for the packaging-widget exposure / conversion funnel.

Covers the model (cs.exposure.event), the sale.order._cs_log_event upsert helper
(create-once / stamp-once / last-value / dedup-by-order), the computed funnel
fields, the unique(order_id) constraint, ondelete='set null' survival, and the
action_confirm stage-4 hook including the "no row for backend orders" guard.

A browser-level HttpCase that drives a real checkout (payment page -> choice ->
transaction -> confirm) is the remaining integration layer and is exercised on
staging per the design doc's assignment.
"""
from datetime import datetime, timedelta

from psycopg2 import IntegrityError

from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged('post_install', '-at_install')
class TestCsExposureEvent(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Event = cls.env['cs.exposure.event'].sudo()
        cls.partner = cls.env['res.partner'].create({'name': 'CS Test Customer'})
        cls.product = cls.env['product.product'].create({
            'name': 'CS Test Service',
            'type': 'service',
            'list_price': 25.0,
        })

    def _make_order(self):
        return self.env['sale.order'].create({
            'partner_id': self.partner.id,
            'order_line': [(0, 0, {
                'product_id': self.product.id,
                'product_uom_qty': 2,
            })],
        })

    # ── helper: create / dedup / stamp-once / last-value ────────────────────

    def test_stage1_creates_single_event_and_dedups(self):
        order = self._make_order()
        t1 = datetime(2026, 6, 1, 10, 0, 0)
        order._cs_log_event(create_if_missing=True,
                            session_key='hash-abc', stage1_payment_page_ts=t1)
        order._cs_log_event(create_if_missing=True,
                            session_key='hash-abc', stage1_payment_page_ts=t1)
        events = self.Event.search([('order_id', '=', order.id)])
        self.assertEqual(len(events), 1, 'Exactly one event per order')
        self.assertEqual(events.session_key, 'hash-abc')
        self.assertEqual(events.order_ref, order.name)

    def test_no_create_without_flag(self):
        """Later-stage hooks must never create a row (backend-order guard)."""
        order = self._make_order()
        order._cs_log_event(postcode_serviceable=True)          # no flag
        order._cs_log_event(stage4_payment_confirmed_ts=datetime.now())
        self.assertFalse(self.Event.search([('order_id', '=', order.id)]),
                         'No event should be created by non-stage-1 hooks')

    def test_timestamps_are_stamp_once(self):
        order = self._make_order()
        t1 = datetime(2026, 6, 1, 10, 0, 0)
        t2 = datetime(2026, 6, 1, 11, 0, 0)
        order._cs_log_event(create_if_missing=True, stage1_payment_page_ts=t1)
        order._cs_log_event(create_if_missing=True, stage1_payment_page_ts=t2)
        event = self.Event.search([('order_id', '=', order.id)])
        self.assertEqual(event.stage1_payment_page_ts, t1,
                         'stage1 timestamp must not be overwritten')

    def test_booleans_are_last_value(self):
        order = self._make_order()
        order._cs_log_event(create_if_missing=True, widget_eligible=True)
        event = self.Event.search([('order_id', '=', order.id)])
        self.assertTrue(event.widget_eligible)
        order._cs_log_event(widget_eligible=False)
        self.assertFalse(event.widget_eligible, 'boolean reflects the last value')

    def test_session_key_only_set_on_create(self):
        order = self._make_order()
        order._cs_log_event(create_if_missing=True, session_key='first')
        event = self.Event.search([('order_id', '=', order.id)])
        order._cs_log_event(session_key='second', postcode_serviceable=True)
        self.assertEqual(event.session_key, 'first',
                         'session_key is captured once and never recomputed')

    # ── computed funnel fields ──────────────────────────────────────────────

    def test_computed_funnel(self):
        order = self._make_order()
        t1 = datetime(2026, 6, 1, 10, 0, 0)
        t2 = t1 + timedelta(seconds=30)
        t_choice = t1 + timedelta(seconds=45)
        t4 = t1 + timedelta(seconds=300)
        order._cs_log_event(create_if_missing=True,
                            stage1_payment_page_ts=t1, stage2_widget_ts=t2)
        order._cs_log_event(choice_ts=t_choice,
                            stage3_proceed_payment_ts=t1 + timedelta(seconds=120),
                            stage4_payment_confirmed_ts=t4)
        event = self.Event.search([('order_id', '=', order.id)])
        self.assertEqual(event.furthest_stage, 4)
        self.assertAlmostEqual(event.decision_seconds, 15.0)
        self.assertAlmostEqual(event.time_to_confirm_seconds, 300.0)

    def test_furthest_stage_partial(self):
        order = self._make_order()
        order._cs_log_event(create_if_missing=True,
                            stage1_payment_page_ts=datetime.now(),
                            stage2_widget_ts=datetime.now())
        event = self.Event.search([('order_id', '=', order.id)])
        self.assertEqual(event.furthest_stage, 2,
                         'abandoned-at-widget session reports stage 2')

    # ── constraints and data survival ───────────────────────────────────────

    @mute_logger('odoo.sql_db')
    def test_unique_order_constraint(self):
        order = self._make_order()
        self.Event.create({'order_id': order.id})
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self.Event.create({'order_id': order.id})
                self.env.flush_all()

    def test_ondelete_set_null_survives_cart_deletion(self):
        order = self._make_order()
        order._cs_log_event(create_if_missing=True,
                            stage1_payment_page_ts=datetime.now())
        event = self.Event.search([('order_id', '=', order.id)])
        ref = order.name
        order.unlink()
        self.assertTrue(event.exists(), 'event survives cart deletion')
        self.assertFalse(event.order_id, "order_id is nulled, not cascaded")
        self.assertEqual(event.order_ref, ref, 'order_ref snapshot retained')

    # ── stage 4 via action_confirm ──────────────────────────────────────────

    def test_action_confirm_stamps_stage4(self):
        order = self._make_order()
        order._cs_log_event(create_if_missing=True,
                            stage1_payment_page_ts=datetime.now())
        order.action_confirm()
        event = self.Event.search([('order_id', '=', order.id)])
        self.assertEqual(order.state, 'sale', 'order still confirms')
        self.assertTrue(event.stage4_payment_confirmed_ts,
                        'stage 4 stamped on confirmation')

    def test_action_confirm_no_event_for_backend_order(self):
        """A confirmed order that never reached the payment page gets no row."""
        order = self._make_order()
        order.action_confirm()
        self.assertEqual(order.state, 'sale')
        self.assertFalse(self.Event.search([('order_id', '=', order.id)]),
                         'no funnel row for orders that skipped the website funnel')

    def test_action_confirm_idempotent_stage4(self):
        order = self._make_order()
        t_first = datetime(2026, 6, 1, 9, 0, 0)
        order._cs_log_event(create_if_missing=True, stage1_payment_page_ts=datetime.now(),
                            stage4_payment_confirmed_ts=t_first)
        order.action_confirm()  # already-confirmable->sale, but stage4 already set
        event = self.Event.search([('order_id', '=', order.id)])
        self.assertEqual(event.stage4_payment_confirmed_ts, t_first,
                         'stage 4 is stamp-once, not moved by re-confirmation')
