from odoo import models, fields, api
from odoo.exceptions import ValidationError


class BOM(models.Model):
    _inherit = 'mrp.bom'

    cable_2d_image = fields.Binary("Cable 2D Cross-Section Image")
    tds_html = fields.Html(string="TDS Details", compute="_compute_tds_html", sanitize=False)

    @api.depends('design_id')
    def _compute_tds_html(self):
        for rec in self:
            rec.tds_html = self.env['ir.qweb']._render('cable_2d_cross_section_generator.tds_html_template', {
                'order': rec.design_id
            })

    def generate_cable_cross_section_image(self):
        """
            Generate 2D and 3D designs for the cable based on product attributes.
        """
        try:
            for rec in self:
                layers = rec.design_id.order_line  # get cable layers
                cable_2d_img = rec.design_id._draw_cable_2d(layers, rec)  # Generate 2D cross-section
                rec.cable_2d_image = cable_2d_img  # store the figure as an image field
        except Exception as e:
            raise ValidationError(str(e))

    def _get_colors(self):  # get referenced colors
        for rec in self:
            if rec.color_codes:
                if ' ' in rec.color_codes and rec.design_id.no_cores > 1:  # check for the number of the colors
                    color_list = rec.color_codes.strip().split(' ')
                    if len(color_list) != rec.design_id.no_cores:  # make sure the number of selected colors equals to number of cores
                        raise ValidationError(f'No. of referenced colors {len(color_list)} must be equal to No. of design cores {rec.design_id.no_cores}')
                    return color_list
                if rec.design_id.no_cores == 1:  # handle single core
                    color_list = [rec.color_codes]
                    return color_list
            raise ValidationError(f'reference {rec.color_codes} does not refer to any color.')  # wrong input

    def _get_color_by_reference_name(self, color):  # get color hex code
        if color.lower() == 'bk':
            result = '#1a1a1a'
        elif color.lower() == 'bn':
            result = '#9e360a'
        elif color.lower() == 'rd':
            result = '#ff0000'
        elif color.lower() == 'og':
            result = '#ffa600'
        elif color.lower() == 'ye':
            result = '#ffff00'
        elif color.lower() == 'gn':
            result = '#008000'
        elif color.lower() == 'bu':
            result = '#0000ff'
        elif color.lower() == 'vt':
            result = '#ee82ee'
        elif color.lower() == 'gy':
            result = '#808080'
        elif color.lower() == 'wh':
            result = '#ffffff'
        elif color.lower() == 'pk':
            result = '#FF007F'
        elif color.lower() == 'tq':
            result = '#40e0d0'
        elif color.lower() == 'gnye':
            result = '#8ee53f'
        elif color.lower() == 'gd':
            result = '#ffd700'
        elif color.lower() == 'sr':
            result = '#c0c0c0'
        else:
            raise ValidationError(f'{color} is not a color.')
        return result
