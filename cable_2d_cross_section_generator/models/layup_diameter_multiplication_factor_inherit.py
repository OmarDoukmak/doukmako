from odoo import models, fields
from odoo.exceptions import ValidationError


class LayupDiameterMultiplicationFactor(models.Model):
    _inherit = "lu.diameter.multiplication.factor"

    def _get_layup_configuration(self, no_cores):
        """Get the layup configuration for a given number of cores"""
        config = self.env['lu.diameter.multiplication.factor'].search([('no_cores', '=', no_cores)], limit=1)
        if not config:
            raise ValidationError(f"No layup configuration found for {no_cores} cores.")

        layers = []
        if config.l1 > 0:
            layers.append(config.l1)
        if config.l2 > 0:
            layers.append(config.l2)
        if config.l3 > 0:
            layers.append(config.l3)
        if config.l4 > 0:
            layers.append(config.l4)
        if config.l5 > 0:
            layers.append(config.l5)
        if config.l6 > 0:
            layers.append(config.l6)

        return layers, config
