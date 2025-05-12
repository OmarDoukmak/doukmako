from odoo import models, fields, api
from odoo.exceptions import ValidationError
import base64
import io
import matplotlib

matplotlib.use('Agg')  # Use a non-GUI backend
import matplotlib.pyplot as plt
import numpy as np
from shapely.geometry import Polygon
from matplotlib.patches import Polygon as MplPolygon, Wedge, Rectangle
import matplotlib as mpl
import trimesh


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cable_2d_image = fields.Binary("Cable 2D Cross-Section Image")
    hide_generate_2d_button = fields.Boolean(default=False)
    hide_regenerate_2d_button = fields.Boolean(default=True)

    def write(self, vals):
        if 'design_state' in vals and vals['design_state'] == 'draft':
            for rec in self:
                if rec.design_state != 'draft':
                    vals['hide_generate_2d_button'] = True
                    vals['hide_regenerate_2d_button'] = False

        return super().write(vals)

    @api.constrains('design_state')
    def _change_generate_2d_button_visibility(self):
        for rec in self:
            if rec.design_state and rec.design_state != 'draft':
                rec.hide_generate_2d_button = True
                rec.hide_regenerate_2d_button = True

    def generate_cable_cross_section_image(self):
        try:
            """
                Generate 2D design for the cable based on product attributes.
            """
            for rec in self:
                layers = rec.order_line.filtered(lambda l: l.product_template_id.cable_layer_type_id)  # cable layers
                cable_2d_img = self._draw_cable_2d(layers, False)  # Generate 2D cross-section
                rec.cable_2d_image = cable_2d_img  # store the figure as an image field
        except Exception as e:
            raise ValidationError(str(e))

    def _draw_cable_2d(self, layers, bom):
        """
            Generate a 2D cross-section of the cable based on the given layers.
        """
        fig, ax = plt.subplots(figsize=(6.5, 3.5))  # figure size
        ax.set_aspect(1)
        plt.axis('off')
        queue_layers = []  # define the queue layers (stack the layers above each others)
        last_layer = layers[-1]
        if len(layers) > 9:
            line_height = 0.25
        else:
            line_height = 0.3

        dimension = last_layer.diameter * 0.5  # give the image coordinates can fit the cable layers
        center_x, center_y = 0, 0  # define center point
        # Get the layup configuration
        layup_config, config = self.env['lu.diameter.multiplication.factor']._get_layup_configuration(self.no_cores)
        center_points = (center_x, center_y)
        rec = self._get_conductor_dimension(layers[0]) if layers else self.env['conductor.dimensions']  # get shape
        if rec:
            shape = 'sector' if rec.conductor_shape == 'Shaped' else 'circular'
        else:
            raise ValidationError('No related conductor dimensions record has been found')
        layer_number = 1
        for index, layer in enumerate(layers):  # draw layers in order from inside to outside
            layer_color = layer.product_template_id.layer_color_fill or '#b0b0b0'  # default layer color
            y_pos = last_layer.diameter / 1.4 - (last_layer.diameter / 2 * line_height * layer_number)
            arrow_angle = 90 - layer_number * 2
            diameter = layer.diameter  # default layer diameter
            thickness = layer.thickness  # default layer thickness
            qty = int(layer.product_uom_qty)  # layer quantity
            layer_type = layer.product_template_id.cable_type  # layer type
            if bom:
                colors = bom._get_colors()
            else:
                colors = self._get_colors(qty)
            # conductor layer
            if layer_type == 'phase_conductor':
                layer_number += 1
                if rec.conductor_material:
                    if rec.conductor_material == 'Copper':
                        layer_color = '#ffa600'
                    if rec.conductor_material == 'Aluminium':
                        layer_color = '#b0b0b0'
                number_of_wires = ''
                darken = 0
                for n in range(0, layer.product_template_id.number_of_wires):  # wires density
                    number_of_wires += 'O'
                    darken = 30
                conductor_radius = diameter / 2  # conductor radius

                if qty != layer.order_id.no_cores:
                    angles = np.linspace(0, 2 * np.pi, qty, endpoint=False)  # generate points
                    # radius of the layer which holds all conductors
                    outer_radius = (layers[index + 4]['diameter'] - layers[index + 1]['diameter']) / 2
                else:
                    angles = np.linspace(0, 2 * np.pi, qty, endpoint=False)  # generate points
                    # radius of the layer which holds all conductors
                    outer_radius = (layers[index + 2]['diameter'] - layers[index + 1]['diameter']) / 2

                if qty != layer.order_id.no_cores:
                    angle_step = 100  # sector partition
                    angle_start = 30  # sector start angle
                else:
                    angle_step = 360 / qty  # sector partition
                    angle_start = 90  # sector start angle

                # Calculate the total number of cores to distribute
                total_cores = layer.order_id.no_cores
                core_index = 0
                if total_cores <= 4:
                    for angle, color in zip(angles, colors):  # conductors angles and their colors
                        if shape.lower() == 'circular':  # circular conductor type
                            x_center = center_x + outer_radius * np.cos(angle)  # conductor center points
                            y_center = center_y + outer_radius * np.sin(angle)  # conductor center points
                            queue_layers.append(  # add conductor wires edge shape to the queue
                                Wedge((x_center, y_center), conductor_radius, 0, 360, edgecolor='#303030', fill=False))
                            queue_layers.append(  # add conductor wires shape to the queue
                                Wedge((x_center, y_center), conductor_radius, 0, 360, hatch=number_of_wires,
                                      edgecolor=layer_color,
                                      facecolor=self._darken_hex_color(layer_color, darken)))
                        # sector conductor type
                        elif shape.lower() == 'sector':

                            if qty == layer.order_id.no_cores:
                                tape_thickness = layers[index + 3]['diameter'] - layers[index + 2]['diameter']
                                conductor_radius = (layers[index + 2][
                                                        'diameter'] - 0.2) / 2  # radius of layer holds the phase layers
                                thickness = layers[index + 1]['thickness']  # insulation thickness
                            else:
                                tape_thickness = layers[index + 5]['diameter'] - layers[index + 4]['diameter']
                                conductor_radius = (layers[index + 4][
                                                        'diameter'] - 0.7) / 2  # radius of layer holds the phase layers
                                thickness = layers[index + 1]['thickness']  # insulation thickness

                            if layers[index + 1].thickness > 1:  # fixing rounding ratio for thin conductors
                                rounding_radius = layer.product_template_id.rounding_angle
                            else:
                                rounding_radius = layer.product_template_id.rounding_angle * 0.35
                            offset_distance = 0  # for future edit insulation can be drifted from the center points
                            offset_x = offset_distance * np.cos(np.deg2rad(angle_start + angle_step / 2))  # circular offset
                            offset_y = offset_distance * np.sin(np.deg2rad(angle_start + angle_step / 2))  # circular offset
                            rounded_sector = self._create_rounded_sector(  # wires rounded sector using shapely
                                (center_x + offset_x, center_y + offset_y), conductor_radius, angle_start,
                                angle_start + angle_step, thickness, rounding_radius)
                            x, y = rounded_sector.exterior.xy  # conductor coordinates
                            sector = MplPolygon(  # conductor sector shape
                                np.column_stack((x, y)), facecolor=self._darken_hex_color(layer_color, darken),
                                hatch=number_of_wires,
                                edgecolor=layer_color, joinstyle='round')
                            rounded_sector_insulation = self._create_rounded_sector(  # insulation rounded sector
                                (center_x + offset_x, center_y + offset_y), conductor_radius, angle_start,
                                angle_start + angle_step, -1, rounding_radius)
                            x_insulation, y_insulation = rounded_sector_insulation.exterior.xy  # insulation coordinates
                            if bom:  # check if this is bom or cable design
                                sector_insulation = MplPolygon(  # insulation sector shape
                                    np.column_stack((x_insulation, y_insulation)),
                                    facecolor=bom._get_color_by_reference_name(color), joinstyle='round')
                            else:
                                sector_insulation = MplPolygon(  # insulation sector shape
                                    np.column_stack((x_insulation, y_insulation)), facecolor='#a3a3a3', edgecolor='#303030',
                                    hatch='xxx', joinstyle='round')

                            sector_insulation_edge = MplPolygon(  # insulation sector edge shape
                                np.column_stack((x, y)), edgecolor='#303030', joinstyle='round', fill=False)
                            queue_layers.append(sector_insulation_edge)  # add shape to the figure queue
                            queue_layers.append(sector)  # add shape to the figure queue
                            queue_layers.append(sector_insulation)  # add shape to the figure queue
                            angle_start += angle_step  # next shape stating angle
                            arrow_x = conductor_radius / 2  # annotation prepare (x,y) axis
                            arrow_y = conductor_radius / 2  # annotation prepare (x,y) axis
                else:
                    # For each layer in the layup configuration
                    for layer_num, cores_in_layer in enumerate(layup_config):

                        if layer_num > 0 and layers[index + 1].product_template_id.multiplier_factor > 0:
                            multiplier_factor = layers[index + 1].product_template_id.multiplier_factor
                        else:
                            multiplier_factor = config.multiplier_factor

                        if layers[index + 1].product_template_id.custom_diameter > 0:
                            insulation_diameter = layers[index + 1].product_template_id.custom_diameter
                        else:
                            insulation_diameter = layers[index + 1]['diameter']

                        total_radius = multiplier_factor * (insulation_diameter / 2) - (insulation_diameter / 2)

                        # Calculate radius for this layer
                        layer_radius = total_radius - (insulation_diameter * (len(layup_config)-layer_num-1))

                        if layer_num == 0:
                            rotation = np.deg2rad(layer.product_template_id.rotation)
                        else:
                            rotation = 0

                        # Calculate angles for cores in this layer
                        angles = np.linspace(rotation, 2 * np.pi + rotation, cores_in_layer, endpoint=False)

                        # Draw each core in this layer
                        for angle in angles:
                            if core_index >= total_cores:
                                break
                            x_center = center_x + layer_radius * np.cos(angle)
                            y_center = center_y + layer_radius * np.sin(angle)
                            if layer.product_template_id.custom_diameter > 0:
                                conductor_diameter = layer.product_template_id.custom_diameter
                            else:
                                conductor_diameter = layer.diameter
                            queue_layers.append(
                                Wedge((x_center, y_center), conductor_diameter/2, 0, 360,
                                      edgecolor='#303030', fill=False))
                            queue_layers.append(
                                Wedge((x_center, y_center), conductor_diameter/2, 0, 360,
                                      hatch=number_of_wires, edgecolor=layer_color,
                                      facecolor=self._darken_hex_color(layer_color, darken)))
                            core_index += 1

                arrow_x = center_x + (outer_radius / -2) if shape.lower() == 'sector' else center_x
                arrow_y = center_y + (outer_radius) * np.sin(np.radians(90))
                ax.annotate(
                    layer.product_template_id.cable_layer_type_id.display_name,
                    size=14,
                    xy=(arrow_x, arrow_y),
                    xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                    # Offset y-position
                    arrowprops=dict(
                        arrowstyle='<-',
                        edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color

                        connectionstyle="angle3,angleA=0,angleB=-90",  # Curved arrow path
                        relpos=(0.5, 0.5)
                    ),
                    ha='left',
                    va='center'
                )
            # phase insulation layer (only draws circular type)
            elif layer_type == 'phase_insulation':
                radius = diameter / 2
                if layer.order_id.no_cores <= 4:
                    layer_number += 1
                    angles = np.linspace(0, 2 * np.pi, qty, endpoint=False)  # angle points
                      # insulation radius
                    outer_radius = (layers[index + 1]['diameter'] - diameter) / 2  # outer layer radius
                    for angle, color in zip(angles, colors):  # insulations based on their color standard
                        x = center_x + outer_radius * np.cos(angle)  # insulation coordinates
                        y = center_y + outer_radius * np.sin(angle)  # insulation coordinates
                        if shape.lower() == 'circular':  # only draw circular insulation
                            if bom:  # check if this is bom or cable design
                                dual_color = []
                                if '/' in color:
                                    dual_color.append(color.split('/')[0])
                                    dual_color.append(color.split('/')[1])
                                else:
                                    dual_color.append(color)
                                    dual_color.append(color)

                                queue_layers.append(Wedge((x, y), radius, 90, 270, color=bom._get_color_by_reference_name(
                                    dual_color[0])))  # half circle
                                queue_layers.append(Wedge((x, y), radius, 270, 90, color=bom._get_color_by_reference_name(
                                    dual_color[1])))  # other half circle
                            else:
                                queue_layers.append(  # full circle
                                    Wedge((x, y), radius, 0, 360, facecolor='#a3a3a3', edgecolor='#303030', hatch='xxx'))

                            arrow_x = (diameter - thickness) / 2 if qty > 1 else (np.cos(30 * np.pi / 180) * (
                                        diameter - thickness) / 2)  # annotation arrow coordinates
                            arrow_y = -y if qty > 1 else (np.sin(30 * np.pi / 180) * (
                                        diameter - thickness) / 2)  # annotation arrow coordinates

                else:
                    layer_number += 1
                    total_cores = layer.order_id.no_cores
                    core_index = 0

                    for layer_num, cores_in_layer in enumerate(layup_config):

                        if layer_num > 0 and layer.product_template_id.multiplier_factor > 0:
                            multiplier_factor = layer.product_template_id.multiplier_factor
                        else:
                            multiplier_factor = config.multiplier_factor

                        if layer.product_template_id.custom_diameter > 0:
                            insulation_diameter = layer.product_template_id.custom_diameter
                        else:
                            insulation_diameter = layer.diameter

                        insulation_radius = insulation_diameter / 2

                        total_radius = multiplier_factor * insulation_radius - insulation_radius

                        layer_radius = total_radius - (insulation_diameter * (len(layup_config)-layer_num-1))

                        if layer_num == 0:
                            rotation = np.deg2rad(layers[index - 1].product_template_id.rotation)
                        else:
                            rotation = 0

                        angles = np.linspace(rotation, 2 * np.pi + rotation, cores_in_layer, endpoint=False)

                        for angle in angles:
                            if core_index >= total_cores:
                                break

                            x = center_x + layer_radius * np.cos(angle)
                            y = center_y + layer_radius * np.sin(angle)

                            if shape.lower() == 'circular':
                                if bom:
                                    color = colors[core_index % len(colors)]
                                    dual_color = []
                                    if '/' in color:
                                        dual_color.append(color.split('/')[0])
                                        dual_color.append(color.split('/')[1])
                                    else:
                                        dual_color.append(color)
                                        dual_color.append(color)

                                    queue_layers.append(Wedge((x, y), insulation_radius, 90, 270,
                                                              color=bom._get_color_by_reference_name(dual_color[0])))
                                    queue_layers.append(Wedge((x, y), insulation_radius, 270, 90,
                                                              color=bom._get_color_by_reference_name(dual_color[1])))
                                else:
                                    queue_layers.append(Wedge((x, y), insulation_radius, 0, 360,
                                                              facecolor='#a3a3a3', edgecolor='#303030', hatch='xxx'))

                            core_index += 1

                if shape.lower() == 'circular':  # annotate for sector cables

                    ax.annotate(
                        layer.product_template_id.cable_layer_type_id.display_name,
                        size=14,
                        xy=(arrow_x, arrow_y),
                        xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                        # Offset y-position
                        arrowprops=dict(
                            arrowstyle='<-',
                            edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color

                            connectionstyle="angle3,angleA=0,angleB=-90",  # Curved arrow path
                            relpos=(0.5, 0.5)
                        ),
                        ha='left',
                        va='center'
                    )
                else:  # annotate for sector cables
                    arrow_y = center_y + thickness
                    if qty in [2, 3, 4]:
                        arrow_y = center_y + outer_radius / 2  # annotate arrow (x, y) index
                    if qty == 2:
                        arrow_y = center_y - outer_radius / 2  # annotate arrow (x, y) index
                    arrow_x = center_x + thickness / 2  # annotate arrow (x, y) index
                    # arrow_x = center_x + (layers[index + 1].diameter / 2 - thickness / 2) * np.sin(np.radians(arrow_angle))
                    # arrow_y = center_y + (layers[index + 1].diameter / 2 - thickness / 2) * np.sin(np.radians(arrow_angle))

                    ax.annotate(
                        layer.product_template_id.cable_layer_type_id.display_name,
                        size=14,
                        xy=(arrow_x, arrow_y),
                        xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                        # Offset y-position
                        arrowprops=dict(
                            arrowstyle='<-',
                            edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color

                            connectionstyle="angle3,angleA=0,angleB=-90",  # Curved arrow path
                            relpos=(0.5, 0.5)
                        ),
                        ha='left',
                        va='center'
                    )
            # neutral conductor layer
            elif layer_type == 'neutral_conductor':
                layer_number += 1
                rec1 = self._get_conductor_dimension(layer)
                if rec1:
                    shape = 'sector' if rec1.conductor_shape == 'Shaped' else 'circular'
                else:
                    raise ValidationError('No related conductor dimensions record has been found')
                if rec1.conductor_material:
                    if rec1.conductor_material == 'Copper':
                        layer_color = '#ffa600'
                    if rec1.conductor_material == 'Aluminium':
                        layer_color = '#b0b0b0'
                number_of_wires = ''
                darken = 0
                for n in range(0, layer.product_template_id.number_of_wires):  # wires density
                    number_of_wires += 'O'
                    darken = 30

                conductor_radius = (diameter - layers[index + 1]['thickness'] * 2) / 2  # conductor radius
                insulation_radius = (layers[index + 1]['diameter'] - layers[index + 1]['thickness'] * 2) / 2
                outer_radius = (layers[4]['diameter']) / 3
                angle = np.linspace(0, 2 * np.pi, 1, endpoint=False)[0]  # generate points

                if bom:
                    dual_color = []
                    if '/' in colors[-1]:
                        dual_color.append(colors[-1].split('/')[0])
                        dual_color.append(colors[-1].split('/')[1])
                    else:
                        dual_color.append(colors[-1])
                        dual_color.append(colors[-1])
                    bom_color = bom._get_color_by_reference_name(dual_color[0])

                if shape.lower() == 'circular':  # circular conductor type
                    x_center = center_x + outer_radius * np.cos(angle)  # conductor center points
                    y_center = center_y + outer_radius * np.sin(angle)  # conductor center points
                    queue_layers.append(  # add conductor wires edge shape to the queue
                        Wedge((x_center, y_center), conductor_radius, 0, 360, edgecolor='#303030', fill=False))
                    queue_layers.append(  # add conductor wires shape to the queue
                        Wedge((x_center, y_center), conductor_radius, 0, 360, hatch=number_of_wires,
                              edgecolor=layer_color,
                              facecolor=self._darken_hex_color(layer_color, darken)))
                    if bom:
                        queue_layers.append(  # add conductor wires shape to the queue
                            Wedge((x_center, y_center), insulation_radius, 0, 180, color=bom_color))
                        queue_layers.append(  # add conductor wires shape to the queue
                            Wedge((x_center, y_center), insulation_radius, 180, 360, color=bom_color))
                    else:
                        queue_layers.append(  # full circle
                            Wedge((x_center, y_center), insulation_radius, 0, 360, facecolor='#a3a3a3',
                                  edgecolor='#303030', hatch='xxx'))

                    arrow_x = x_center  # annotation prepare (x,y) axis
                    arrow_y = y_center

                    ax.annotate(
                        layer.product_template_id.cable_layer_type_id.display_name,
                        size=14,
                        xy=(arrow_x, arrow_y),
                        xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                        # Offset y-position
                        arrowprops=dict(
                            arrowstyle='<-',
                            edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color

                            connectionstyle="angle3,angleA=0,angleB=-90",  # Curved arrow path
                            relpos=(0.5, 0.5)
                        ),
                        ha='left',
                        va='center'
                    )
                    # insulation annotation
                    arrow_x = x_center + (conductor_radius + thickness / 2) * np.cos(
                        30 * np.pi / 180)  # annotation prepare (x,y) axis
                    arrow_y = y_center + (conductor_radius + thickness / 2) * np.sin(30 * np.pi / 180)
                    y_pos = last_layer.diameter / 1.4 - (last_layer.diameter / 2 * line_height * layer_number)
                    layer_number += 1
                    ax.annotate(
                        layers[index + 1].product_template_id.cable_layer_type_id.display_name,
                        size=14,
                        xy=(arrow_x, arrow_y),
                        xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                        # Offset y-position
                        arrowprops=dict(
                            arrowstyle='<-',
                            edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color

                            connectionstyle="angle3,angleA=0,angleB=-90",  # Curved arrow path
                            relpos=(0.5, 0.5)
                        ),
                        ha='left',
                        va='center'
                    )
                # sector conductor type
                elif shape.lower() == 'sector':
                    tape_thickness = 0.7
                    # tape_thickness = layers[index + 3]['diameter'] - layers[index + 2]['diameter']
                    # conductor_radius = (layers[index + 2]['diameter'] - tape_thickness) / 2
                    conductor_radius = (layers[index + 2]['diameter'] - 0.7) / 2  # radius of layer holds the neutral layers
                    thickness = layers[index + 1]['thickness']  # insulation thickness

                    if layers[index + 1].thickness > 1:  # fixing rounding ratio for thin conductors
                        rounding_radius = layer.product_template_id.rounding_angle
                    else:
                        rounding_radius = layer.product_template_id.rounding_angle * 0.35
                    angle_start = -30
                    angle_step = 60
                    offset_distance = 0  # for future edit insulation can be drifted from the center points
                    offset_x = offset_distance * np.cos(np.deg2rad(angle_start + angle_step / 2))  # circular offset
                    offset_y = offset_distance * np.sin(np.deg2rad(angle_start + angle_step / 2))  # circular offset
                    rounded_sector = self._create_rounded_sector(  # wires rounded sector using shapely
                        (center_x + offset_x, center_y + offset_y), conductor_radius, angle_start,
                        angle_start + angle_step, thickness, rounding_radius)
                    x, y = rounded_sector.exterior.xy  # conductor coordinates
                    sector = MplPolygon(  # conductor sector shape
                        np.column_stack((x, y)), facecolor=self._darken_hex_color(layer_color, darken),
                        hatch=number_of_wires,
                        edgecolor=layer_color, joinstyle='round')
                    rounded_sector_insulation = self._create_rounded_sector(  # insulation rounded sector
                        (center_x + offset_x, center_y + offset_y), conductor_radius, angle_start,
                        angle_start + angle_step, -1, rounding_radius)
                    x_insulation, y_insulation = rounded_sector_insulation.exterior.xy  # insulation coordinates
                    if bom:  # check if this is bom or cable design
                        sector_insulation = MplPolygon(  # insulation sector shape
                            np.column_stack((x_insulation, y_insulation)),
                            facecolor=bom_color, joinstyle='round')
                    else:
                        sector_insulation = MplPolygon(  # insulation sector shape
                            np.column_stack((x_insulation, y_insulation)), facecolor='#a3a3a3', edgecolor='#303030',
                            hatch='xxx', joinstyle='round')

                    sector_insulation_edge = MplPolygon(  # insulation sector edge shape
                        np.column_stack((x, y)), edgecolor='#303030', joinstyle='round', fill=False)
                    queue_layers.append(sector_insulation_edge)  # add shape to the figure queue
                    queue_layers.append(sector)  # add shape to the figure queue
                    queue_layers.append(sector_insulation)  # add shape to the figure queue
                    arrow_x = conductor_radius / 2  # annotation prepare (x,y) axis
                    arrow_y = 0  # annotation prepare (x,y) axis
                    # For neutral conductor annotations
                    ax.annotate(
                        layer.product_template_id.cable_layer_type_id.display_name,
                        size=14,
                        xy=(arrow_x, arrow_y),
                        xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                        # Offset y-position
                        arrowprops=dict(
                            arrowstyle='<-',
                            edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color

                            connectionstyle="angle3,angleA=0,angleB=-90",  # Curved arrow path
                            relpos=(0.5, 0.5)
                        ),
                        ha='left',
                        va='center'
                    )
                    arrow_x = (conductor_radius - 3*thickness/4) * np.cos(
                        20 * np.pi / 180)  # annotation prepare (x,y) axis
                    arrow_y = (conductor_radius - 3*thickness/4) * np.sin(20 * np.pi / 180)
                    y_pos = last_layer.diameter / 1.4 - (last_layer.diameter / 2 * line_height * layer_number)
                    layer_number += 1
                    ax.annotate(
                        layers[index + 1].product_template_id.cable_layer_type_id.display_name,
                        size=14,
                        xy=(arrow_x, arrow_y),
                        xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                        # Offset y-position
                        arrowprops=dict(
                            arrowstyle='<-',
                            edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color

                            connectionstyle="angle3,angleA=0,angleB=-90",  # Curved arrow path
                            relpos=(0.5, 0.5)
                        ),
                        ha='left',
                        va='center'
                    )
            # filler layer
            elif layer_type == 'filler':
                layer_number += 1
                layer_color = layer.product_template_id.layer_color_fill or '#e8e8e8'  # default color

                if layer.product_template_id.custom_diameter > 0:
                    diameter = layer.product_template_id.custom_diameter

                filler_radius = diameter / 2  # filler radius
                filler = plt.Circle(  # draw filler
                    (center_x, center_y), filler_radius, facecolor=layer_color,
                    edgecolor=self._darken_hex_color(layer_color, 30), hatch='', fill=True)
                queue_layers.append(filler)  # add filler to the queue
                # For filler layer annotations
                ax.annotate(
                    layer.product_template_id.cable_layer_type_id.display_name,
                    size=14,
                    xy=(0, 0),
                    xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                    arrowprops=dict(
                        arrowstyle='<-',
                        edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color
                        connectionstyle=f"{'angle3,angleA=0,angleB=-90' if -y_pos < (last_layer['diameter'] / 3) else 'angle,angleA=0,angleB=10,rad=45'}",
                        # Curved arrow path
                        # connectionstyle=f"arc3,rad={0.3 if len(layers.filtered(lambda l: l.product_template_id.cable_layer_type_id.cable_type == 'filler')) == 1 else 0.15}",  # Curved arrow path
                        relpos=(0.5, 0.5)
                    ),
                    ha='left',
                    va='center'
                )
            # tape layer
            elif layer_type == 'tape':
                layer_color = layer.product_template_id.layer_color_fill or '#bbbbbb'  # default color
                if layer.product_template_id.custom_diameter > 0:
                    diameter = layer.product_template_id.custom_diameter
                tape_radius = diameter / 2  # tape radius
                tape = plt.Circle(  # draw tape
                    (center_x, center_y), tape_radius, facecolor='#ffffff', edgecolor=layer_color, linewidth=1.5)
                queue_layers.append(tape)  # add tape to the queue
            # sheath layer
            elif layer_type in 'sheath':
                layer_number += 1
                layer_color = layer.product_template_id.layer_color_fill or '#1f1f1f'  # default color for this layer
                if layer.product_template_id.custom_diameter > 0:
                    diameter = layer.product_template_id.custom_diameter
                sheath_radius = diameter / 2
                if layer.product_template_id.strip_width > 0:  # handle strip line for outer layer
                    strip_color = layer.product_template_id.strip_color or '#1f1f1f'
                    if layer.product_template_id.strip_width_measure == 'degrees':
                        strip_width = layer.product_template_id.strip_width
                        strip_start_angle = 90 - strip_width / 2
                        strip_end_angle = 90 + strip_width / 2
                    else:
                        strip_width = layer.product_template_id.strip_width * 360 / (2 * np.pi * sheath_radius)
                        strip_start_angle = 90 - strip_width / 2
                        strip_end_angle = 90 + strip_width / 2
                    strip = Wedge(center_points, sheath_radius, strip_start_angle, strip_end_angle, color=strip_color)
                    queue_layers.append(strip)  # add strip
                    queue_layers.append(
                        plt.Circle(center_points, sheath_radius, color=self._darken_hex_color(layer_color, 30),
                                   linewidth=0.5, fill=False))
                    queue_layers.append(plt.Circle(center_points, sheath_radius, color=layer_color, fill=True))
                else:  # handle other inner layers
                    queue_layers.append(
                        plt.Circle(center_points, sheath_radius, color=self._darken_hex_color(layer_color, 30),
                                   linewidth=0.5, fill=False))
                    queue_layers.append(plt.Circle(center_points, sheath_radius, color=layer_color, fill=True))
                # For sheath layer annotations
                arrow_angle = 90 - layer_number * 2
                arrow_x = center_x + (sheath_radius - thickness / 3) * np.cos(np.radians(arrow_angle))
                arrow_y = center_y + (sheath_radius - thickness / 3) * np.sin(np.radians(arrow_angle))
                if -y_pos < (last_layer['diameter'] / 3):
                    angleB = 60
                elif last_layer['diameter'] / 3 < -y_pos < last_layer['diameter'] / 2:
                    angleB = 10
                else:
                    angleB = -45
                ax.annotate(
                    layer.product_template_id.cable_layer_type_id.display_name,
                    size=14,
                    xy=(arrow_x, -arrow_y),
                    xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                    arrowprops=dict(
                        arrowstyle='<-',
                        edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color
                        connectionstyle=f"angle,angleA=0,angleB={angleB},rad=45",  # Curved arrow path
                        relpos=(0.5, 0.5)
                    ),
                    ha='left',
                    va='center'
                )
            # armour layer
            elif layer_type == 'armour':
                layer_number += 1
                prev_diameter = layers[index - 1].diameter
                layer_color = layer.product_template_id.layer_color_fill or '#b0b0b0'  # default color for this layer

                if layer.product_template_id.custom_diameter > 0:
                    diameter = layer.product_template_id.custom_diameter
                    if layers[index - 1].product_template_id.custom_diameter:
                        prev_diameter = layers[index - 1].product_template_id.custom_diameter

                    thickness = (diameter - prev_diameter) / 2

                armour_radius = diameter / 2  # draw the outer edge
                inner_radius = armour_radius - thickness / 2  # Inner edge where armour should be filled
                armour_type_shape = None
                armour_tape_width = 0
                for armour_line in layer.product_template_attribute_value_ids:
                    if armour_line.attribute_line_id.attribute_id.name == 'Armour Type Shape':
                        armour_type_shape = armour_line.product_attribute_value_id.name
                    if 'tape width' in armour_line.attribute_line_id.attribute_id.name.lower():
                        if layer.product_template_id.custom_armour_tape_width > 0:
                            armour_tape_width = layer.product_template_id.custom_armour_tape_width
                        else:
                            armour_tape_width = float(armour_line.product_attribute_value_id.name)

                if 'round' in armour_type_shape.lower():
                    small_circle_radius = thickness / 2  # size of the small circles
                    num_circles = int(2 * np.pi * inner_radius / (2 * small_circle_radius))  # Fit around circumference
                    angles = np.linspace(0, 2 * np.pi, num_circles, endpoint=False)  # Evenly distribute circles
                    for index, angle in enumerate(angles):  # draw armour circles around circumference
                        x = center_x + inner_radius * np.cos(angle)
                        y = center_y + inner_radius * np.sin(angle)
                        corner_circle = plt.Circle(
                            (x, y), small_circle_radius, color=self._darken_hex_color(hex_color=layer_color, percent=75),
                            fill=False)
                        small_circle = plt.Circle((x, y), small_circle_radius * 0.5, color=layer_color, fill=True)
                        small_circle_shadow = plt.Circle(
                            (x, y), small_circle_radius, color=self._darken_hex_color(hex_color=layer_color, percent=40),
                            fill=True)
                        queue_layers.append(corner_circle)
                        queue_layers.append(small_circle)
                        queue_layers.append(small_circle_shadow)
                else:
                    line_width = (diameter - prev_diameter) * 2
                    armour_rectangle = plt.Circle(
                        (center_x, center_y), inner_radius+0.1, color=layer_color, fill=False, lw=line_width,
                        ls=(5, (armour_tape_width, 1)))
                    queue_layers.append(armour_rectangle)
                # draw armour boundaries
                armour_circle = plt.Circle((center_x, center_y), armour_radius - thickness, color='black', fill=False)
                thickness_armour_circle = plt.Circle((center_x, center_y), armour_radius, color='white', fill=True)
                queue_layers.append(armour_circle)
                queue_layers.append(thickness_armour_circle)
                # For armour layer annotations
                ax.annotate(
                    layer.product_template_id.cable_layer_type_id.display_name,
                    size=14,
                    xy=(armour_radius / 5, -(armour_radius - thickness / 2.5)),
                    xytext=(last_layer['diameter'] / 2 + last_layer['diameter'] / 2 * 0.2, y_pos),
                    arrowprops=dict(
                        arrowstyle='<-',
                        edgecolor=self._darken_hex_color('#0000c8', 1),  # Arrow edge (outline) color
                        connectionstyle=f"angle,angleA=0,angleB={60 if -y_pos < (last_layer['diameter'] / 3) else 10},rad=45",
                        # Curved arrow path
                        relpos=(0.5, 0.5)
                    ),
                    ha='left',
                    va='center'
                )
            else:
                continue  # future edit replace this for more layers

        for index in reversed(queue_layers):  # draw layers reversed prioritize inner layers over outer layers
            ax.add_patch(index)

        ax.set_xlim(-dimension, dimension * 3)  # increase x for annotations
        ax.set_ylim(-dimension - 1, dimension + 1)

        return self._save_plot(fig)  # return cable figure

    def _save_plot(self, fig):
        """
        Save a matplotlib plot to a base64-encoded image.
        """
        buffer = io.BytesIO()
        fig.savefig(buffer, format='png')
        plt.close(fig)  # Ensure figure is closed
        plt.clf()  # Clear the current figure
        plt.cla()  # Clear the current axes
        return base64.b64encode(buffer.getvalue())

    def _get_colors(self, qty):
        """
            Get phase insulation colors based on BOM colors.
        """
        if qty == 1:
            return [['#9e360a', '#9e360a']]
        if qty == 2:
            return [['#0000ff', '#0000ff'], ['#9e360a', '#9e360a']]
        if qty == 3:
            return [['#9e360a', '#9e360a'], ['#1a1a1a', '#1a1a1a'], ['#808080', '#808080']]
        if qty == 4:
            return [['#0000ff', '#0000ff'], ['#9e360a', '#9e360a'], ['#1a1a1a', '#1a1a1a'], ['#808080', '#808080']]
        if qty == 5:
            return [['#0000ff', '#0000ff'], ['#9e360a', '#9e360a'], ['#1a1a1a', '#1a1a1a'], ['#808080', '#808080'],
                    ['#008000', '#ffff00']]

    def _darken_hex_color(self, hex_color, percent=25):
        """
            Darken colors by percentage.
        """
        hex_color = hex_color.lstrip('#')  # Ensure the hex color is in the correct format
        r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)  # Convert hex to RGB
        factor = 1 - (percent / 100)  # Reduce each component by the given percentage
        r = max(0, int(r * factor))
        g = max(0, int(g * factor))
        b = max(0, int(b * factor))

        # Convert back to hex and return
        return f"#{r:02x}{g:02x}{b:02x}"

    def _create_rounded_sector(self, center, radius, start_angle, end_angle, thickness, round_radius):
        """
        Create a rounded sector using shapely.
        """
        angles = np.linspace(start_angle, end_angle, 100)  # Generate points for the sector shape
        points = [center]
        for angle in angles:
            y = center[1] + radius * np.sin(np.deg2rad(angle))
            x = center[0] + radius * np.cos(np.deg2rad(angle))
            points.append((x, y))
        points.append(center)

        sector_polygon = Polygon(points)  # Create a polygon from the points

        if thickness == -1:  # Round the edges of the sector for insulation
            if not round_radius:
                round_radius = 1
            rounded_sector = sector_polygon.buffer(-(round_radius + 1))
            rounded_sector = rounded_sector.buffer(round_radius + 1, join_style="round")
        else:  # Round the edges of the sector for conductor
            rounded_sector = sector_polygon.buffer(- (round_radius + thickness))
            rounded_sector = rounded_sector.buffer(round_radius, join_style="round")

        return rounded_sector

    def _get_conductor_dimension(self, layer):
        """
            Get conductor shape type from the related conductor dimension.
        """
        conductor_shape = ''
        domains = []
        cond_dim = self.env['conductor.dimensions']
        attrs = self.get_product_attributes(layer.product_template_attribute_value_ids)
        for k, v in attrs.items():
            for item in layer.product_template_id.diameter_selection:
                if item.condition_attribute.name == k:
                    if k == 'Conductor Shape':
                        conductor_shape = v
                    if k == 'Conductor Material':
                        conductor_material = v
                    domains.append((item.match_with_column.name, '=', v))
                    if conductor_shape == 'Shaped':
                        domains.append(('no_cores', '=', layer.product_uom_qty))
        rec = cond_dim.search(domains, limit=1)
        return rec

    def _get_neutral_conductor_dimension(self, layer):
        """
            Get neutral conductor shape type from the related conductor dimension.
        """
        if not self.order_id.neutral_core:
            raise ValidationError(('Neutral Conductor Option is not enabled, find it out in the Basic Info tab!'))

        # Decide the size of neutral conductor based on the phase conductor size:
        phase_conductor_size = None
        attrs = self.order_id.get_all_attributes()
        for k, v in attrs.items():
            if k == 'Conductor Size': phase_conductor_size = v

        neutral_conductor_size = None
        if phase_conductor_size:
            neutral_conductor_size = self.env['neutral.conductor'].search(
                [('phase_conductor_size', '=', phase_conductor_size)], limit=1).neutral_conductor_size

        domains = []
        conductor_shape = ''
        cond_dim = self.env['conductor.dimensions']
        attrs = self.order_id.get_product_attributes(self.product_template_attribute_value_ids)
        for k, v in attrs.items():
            for item in layer.diameter_selection:
                if item.condition_attribute.name == k:
                    if k == 'Neutral Conductor Shape': conductor_shape = v
                    domains.append((item.match_with_column.name, '=', v))
                    if conductor_shape == 'Shaped':
                        domains.append(('no_cores', '=', self.order_id.no_cores))
        if neutral_conductor_size:
            domains.append(('conductor_size', '=', neutral_conductor_size))
        # raise UserError((domains))
        rec = cond_dim.search(domains, limit=1)
        return rec
# ======================================================================================================================
    sample_layers = [
        {"name": "Phase Conductor", "outer_diameter": 10.0, "thickness": 2.0, "color": [1.0, 0.5, 0.0]},  # Orange
        {"name": "Phase Insulation", "outer_diameter": 14.0, "thickness": 2.0, "color": [0.0, 0.0, 1.0]},  # Blue
        {"name": "Wire / Strip Armour", "outer_diameter": 18.0, "thickness": 2.0, "color": [0.5, 0.5, 0.5]},  # Gray
        {"name": "Outer Sheath", "outer_diameter": 22.0, "thickness": 2.0, "color": [0.0, 0.0, 0.0]},  # Black
    ]

    # Height of the cable (extrusion length)
    cable_height = 100.0
    cable_3d_mesh = fields.Binary("Cable 3D Model")

    def generate_cable_3d_model(self):
        # try:
            """
                Generate 3D design for the cable based on product attributes.
            """
            for rec in self:
                layers = rec.order_line.filtered(lambda l: l.product_template_id.cable_layer_type_id)  # cable layers
                # Generate the 3D cable mesh
                cable_3d_mesh = self.generate_cable_3d(self.sample_layers, self.cable_height)

                # Export to GLB (GLTF binary format)
                output_path = "C:\Program Files\odoo\odoo 17\server\odoo\custom\hype_studio\cableERP\cable_2d_cross_section_generator\data\cable_3d_model.glb"
                cable_3d_mesh.export(output_path)
                # output_path
                # rec.cable_3d_mesh = cable_3d_mesh  # store the figure as an image field
        # except Exception as e:
        #     raise ValidationError(str(e))

    # Create 3D mesh from concentric cylindrical layers
    def generate_cable_3d(self, layers, height):
        meshes = []
        for layer in layers:
            outer_radius = layer["outer_diameter"] / 2.0
            inner_radius = outer_radius - layer["thickness"]
            color = layer.get("color", [1.0, 1.0, 1.0])  # Default to white

            # Create cylindrical shell for the layer
            outer_cyl = trimesh.creation.cylinder(radius=outer_radius, height=height, sections=64)
            inner_cyl = trimesh.creation.cylinder(radius=inner_radius, height=height, sections=64)
            shell = outer_cyl.difference(inner_cyl)

            # Assign color
            shell.visual.vertex_colors = np.tile(np.array(color + [1.0]), (len(shell.vertices), 1))
            meshes.append(shell)

        # Combine all layer meshes into a single scene
        cable_mesh = trimesh.util.concatenate(meshes)
        return cable_mesh
