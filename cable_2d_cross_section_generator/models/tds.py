from odoo import models, fields, api


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    tds_html = fields.Html(string="TDS Details", compute="_compute_tds_html", sanitize=False)

    @api.depends('order_line')
    def _compute_tds_html(self):
        for order in self:
            order.tds_html = order.env['ir.qweb']._render('cable_2d_cross_section_generator.tds_html_template', {
                'order': order
            })
