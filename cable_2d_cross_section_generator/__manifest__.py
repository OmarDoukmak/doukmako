# -*- coding: utf-8 -*-
{
    "name": "Cable 2D Cross Section Generator",
    "summary": "Allow you to generate 2D image of cable cross section.",
    "version": "0.1",
    "author": "Hype Studio, Omar Dukmak",
    "category": "Tools",
    "depends": ["base", "web", "hype_cable_pro", "mrp_overhead_cost"],
    "data": [
        'security/ir.model.access.csv',
        "data/tds.xml",
        "views/cable_2d_cross_section.xml",
        "views/product_template.xml",
        "views/bom.xml",
        "views/cable_layer_type.xml",
        "views/tds.xml",
    ],
    'demo': [],
    'external_dependencies': {
        'python': ['matplotlib', 'shapely'],
    },
    'installable': True,
    'auto_install': False,
    'license': "AGPL-3",
}
