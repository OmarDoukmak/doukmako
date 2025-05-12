from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CableLayerType(models.Model):
    _name = 'cable.layer.type'
    _rec_name = 'name'

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
    DISPLAY_TYPES = [
        ('name', 'Name'),
        ('csd_element_name', 'CSD Element'),
        ('name_first', 'Name CSD Element'),
        ('name_last', 'CSD Element Name'),
    ]

    name = fields.Char(string="Cable Layer")
    cable_type = fields.Selection(TYPES, string="CSD Element Type")
    csd_element_name = fields.Char(string="CSD Element Type")
    display_type = fields.Selection(DISPLAY_TYPES, string="Display Type", default="csd_element_name")
    display_name = fields.Char(string="Display Name", compute="_compute_display_name")
    product_id = fields.Many2one('product.template', string="Related Product")

    def _get_selection_string(self, field):
        for rec in self:
            return rec._fields[field].convert_to_export(rec[field], rec)

    @api.depends('name', 'cable_type', 'display_type')
    def _compute_display_name(self):
        for rec in self:
            if rec.display_type == 'name_first':
                rec.display_name = f"{rec.name} {rec._get_selection_string('csd_element_name')}"
            elif rec.display_type == 'name_last':
                rec.display_name = f"{rec._get_selection_string('csd_element_name')} {rec.name}"
            elif rec.display_type == 'name':
                rec.display_name = rec.name
            else:
                rec.display_name = rec._get_selection_string('csd_element_name')

    @api.onchange('name')
    @api.constrains('name')
    def _change_values(self):
        for rec in self:
            if rec.name:
                product_id = self.env['product.template'].search([('name', '=', rec.name)], limit=1)
                if product_id:
                    product_id.write({'cable_layer_type_id': rec.id})
                    rec.product_id = product_id
                cable_type_dict = {value: key for key, value in CableLayerType.TYPES}

                if 'Phase Conductor' in rec.name:
                    value_to_find = 'Phase Conductor'
                elif 'Phase Insulation' in rec.name:
                    value_to_find = 'Phase Insulation'
                elif 'Neutral Conductor' in rec.name:
                    value_to_find = 'Neutral Conductor'
                elif 'Neutral Insulation' in rec.name:
                    value_to_find = 'Neutral Insulation'
                elif 'Filler' in rec.name:
                    value_to_find = 'Filler'
                elif 'Sheath' in rec.name:
                    value_to_find = 'Sheath'
                elif 'Armour' in rec.name:
                    value_to_find = 'Armour'
                else:
                    value_to_find = 'Tape'

                rec.cable_type = cable_type_dict.get(value_to_find, None)
