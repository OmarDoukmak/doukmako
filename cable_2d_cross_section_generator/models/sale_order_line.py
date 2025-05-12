from odoo import models, fields, api
import math
import numpy as np


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    conductor_dimension_id = fields.Many2one('conductor.dimensions', store=True,
                                             compute="_compute_conductor_dimension_id")
    armour_no_wires = fields.Integer(store=True, compute="_compute_armour_no_wires")

    @api.depends('diameter', 'thickness')
    def _compute_armour_no_wires(self):
        for line in self:
            line.armour_no_wires = math.ceil(np.pi * line.diameter / (line.thickness or 1) * 0.89)

    @api.depends('product_template_attribute_value_ids')
    def _compute_conductor_dimension_id(self):
        """
            Get conductor shape type from the related conductor dimension.
        """
        for rec in self:
            conductor_shape = ''
            domains = []
            record = self.env['conductor.dimensions']
            if rec.product_template_id.cable_type in ['phase_conductor', 'neutral_conductor']:
                attrs = rec.order_id.get_product_attributes(rec.product_template_attribute_value_ids)
                for k, v in attrs.items():
                    for item in rec.product_template_id.diameter_selection:
                        if item.condition_attribute.name == k:
                            if k == 'Conductor Shape':
                                conductor_shape = v
                            if k == 'Conductor Material':
                                conductor_material = v
                            domains.append((item.match_with_column.name, '=', v))
                            if conductor_shape == 'Shaped':
                                domains.append(('no_cores', '=', rec.product_uom_qty))
                record = record.search(domains, limit=1)

                rec.conductor_dimension_id = record
