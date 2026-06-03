# -*- coding: utf-8 -*-
from odoo import models, fields


class DeliveryCarrier(models.Model):
    _inherit = 'delivery.carrier'

    cs_is_office_carrier = fields.Boolean(
        string='Circular Shipping bezorgmethode',
        help=(
            'Markeer deze bezorgmethode als de Circular Shipping kantoorcarrier. '
            'Bestellingen met statiegeld verpakking worden na betaling naar deze methode omgezet '
            'en worden niet naar Monta gestuurd.'
        ),
        default=False,
    )
