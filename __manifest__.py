# -*- coding: utf-8 -*-
{
    'name': 'Circular Shipping — Packaging Choice v1.2.1',
    'version': '18.0.1.1',
    'category': 'eCommerce',
    'summary': 'Reusable vs single-use packaging choice at checkout with deposit and A/B testing',
    'author': 'Circular Shipping Company B.V.',
    'website': 'https://circularshipping.nl',
    'license': 'LGPL-3',
    'depends': [
        'website_sale',
        'sale_management',
        'website',
        'delivery',
    ],
    'data': [
        'security/ir.model.access.csv',
        'data/product_data.xml',
        'views/res_config_settings_views.xml',
        'views/delivery_carrier_views.xml',
        'views/templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'circular_shipping_checkout/static/src/css/packaging_widget.css',
            'circular_shipping_checkout/static/src/js/packaging_widget.js',
        ],
        'web.assets_backend': [
            'circular_shipping_checkout/static/src/css/settings_backend.css',
        ],
    },
    'external_dependencies': {'python': ['requests']},
    'post_init_hook': 'post_init_hook',
    'uninstall_hook': 'uninstall_hook',
    'installable': True,
    'application': False,
    'auto_install': False,
}
