from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    TYPES = [
        ('phase_conductor', 'Phase Conductor'),
        ('phase_insulation', 'Phase Insulation'),
        ('neutral_conductor', 'Neutral Conductor'),
        ('neutral_insulation', 'Neutral Insulation'),
        ('filler', 'Filler'),
        ('tape', 'Tape'),
        ('sheath', 'Sheath'),
        ('armour', 'Armour'),
    ]

    cable_layer_type_id = fields.Many2one('cable.layer.type', string="Cable Layer Type")
    cable_type = fields.Selection(related="cable_layer_type_id.cable_type")
    number_of_wires = fields.Integer(string="Number of Wires", default=2)
    rounding_angle = fields.Float(string="Rounding Angle", default=1.0)
    strip_color = fields.Char(string='Strip Color')
    strip_width_measure = fields.Selection([('degrees', 'Degrees'), ('millimeters', 'Millimeters')], default='degrees')
    strip_width = fields.Float(string='Strip Width')
    custom_diameter = fields.Float(string='Custom Diameter')
    custom_armour_tape_width = fields.Float(string='Custom Flat/Strip Width')
    multiplier_factor = fields.Float(string='Multiplier Factor')
    rotation = fields.Float(string="Rotation Degree", help="In Degrees.")

    def _get_selection_string(self, field):
        for rec in self:
            return rec._fields[field].convert_to_export(rec[field], rec)
