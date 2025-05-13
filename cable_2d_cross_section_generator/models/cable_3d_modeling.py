from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError  # Added UserError
import base64
import io
import numpy as np
from shapely.geometry import Polygon

# --- 3D Library ---
try:
    import trimesh

    # Check for scipy, needed for boolean operations (optional)
    try:
        import scipy

        SCIPY_AVAILABLE = True
    except ImportError:
        SCIPY_AVAILABLE = False
except ImportError:
    trimesh = None  # Handle case where trimesh is not installed

import logging  # Use Odoo's logger

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    cable_3d_model_attachment_ids = fields.Many2many('ir.attachment', 'rel_cable_attachment',
                                                     string="Cable 3D Model (GLB)")  # Store as attachment
    model_3d = fields.Binary(string="3d Model")

    cable_length_3d = fields.Float("3D Model Length (mm)", default=50.0)  # Configurable length
    cable_length_step_3d = fields.Float("3D Length Step per Layer (mm)",
                                        default=5.0)  # How much shorter each outer layer is

    def generate_cable_3d_model(self):
        """
        Button action to generate and save the 3D cable model (GLB).
        """
        if not trimesh:
            raise UserError("The 'trimesh' library is required for 3D generation but is not installed.")
        if not np:
            raise UserError("The 'numpy' library is required for 3D generation but is not installed.")

        for rec in self:
            layers = rec.order_line.filtered(lambda l: l.product_template_id.cable_layer_type_id)
            if not layers:
                rec.cable_3d_model_glb = False
                raise UserError("No cable layers found on the order lines to generate a 3D model.")

            cable_length = rec.cable_length_3d if rec.cable_length_3d > 0 else 50.0  # Use configured length

            try:
                # Generate the 3D mesh using the new detailed function
                # TODO: Pass BOM data if needed by _generate_cable_3d
                cable_mesh = rec._generate_cable_3d(layers, False, cable_length)  # Pass BOM if required

                if cable_mesh is None or not isinstance(cable_mesh, trimesh.Trimesh) or len(cable_mesh.faces) == 0:
                    rec.cable_3d_model_glb = False
                    _logger.warning(f"3D mesh generation for SO {rec.name} resulted in an empty or invalid mesh.")
                    # Optionally raise UserError here if an empty mesh is considered an error
                    # raise UserError("3D model generation failed: The resulting mesh is empty or invalid.")
                    continue  # Skip saving if mesh is bad

                # Export mesh to GLB format in memory
                with io.BytesIO() as buffer:
                    _logger.info(f"Exporting 3D mesh for SO {rec.name} to GLB format...")
                    cable_mesh.export(buffer, file_type='glb')
                    buffer.seek(0)
                    glb_data = buffer.read()

                # Encode and save to attachment field
                if rec.cable_3d_model_attachment_ids:
                    rec.cable_3d_model_attachment_ids.unlink()

                rec.cable_3d_model_attachment_ids = [(0, 0, {
                    'name': f'{rec.name}.glb',
                    'type': 'binary',
                    'datas': base64.b64encode(glb_data),
                    'res_model': 'sale.order',
                    'res_id': rec.id,
                    'mimetype': 'model/gltf-binary',
                })]
                rec.model_3d = rec.cable_3d_model_attachment_ids.datas
                _logger.info(f"Successfully generated and saved 3D model for SO {rec.name}.")

            except Exception as e:
                _logger.exception(f"Error generating 3D cable model for SO {rec.name}: {e}")
                rec.cable_3d_model_attachment_ids = False  # Clear field on error
                rec.model_3d = False
                raise UserError(f"Failed to generate 3D model: {e}")

    def _generate_cable_3d(self, layers, bom, cable_length):
        """
        Generate a 3D mesh representation of the cable based on the given layers.
        Mirrors the logic of _draw_cable_2d but creates trimesh objects.

        :param layers: Filtered recordset of sale.order.line representing cable layers.
        :param bom: BOM data (structure TBD, currently unused placeholder).
        :param cable_length: The length (extrusion height) of the cable segment in mm.
        :return: A trimesh.Trimesh object or None if generation fails.
        """
        if not trimesh:
            _logger.error("Trimesh library not available for 3D generation.")
            return None
        if not np:
            _logger.error("Numpy library not available for 3D generation.")
            return None

        all_3d_meshes = []  # List to hold individual trimesh objects

        # Get overall dimension for reference (e.g., from last layer)
        last_layer = layers[-1] if layers else None
        dimension_3d = max(last_layer.diameter * 0.5, 1.0) if last_layer else 1.0  # Ensure positive dimension

        center_x, center_y = 0, 0  # Cable centered at XY origin
        layup_config, config = self.env['lu.diameter.multiplication.factor']._get_layup_configuration(self.no_cores)

        # Get initial conductor shape (same logic as 2D)
        rec_initial = self._get_conductor_dimension(layers[0]) if layers else None
        shape = 'sector' if rec_initial and rec_initial.conductor_shape == 'Shaped' else 'circular'

        # --- Main Loop for 3D Generation ---
        for index, layer in enumerate(layers):
            cable_length -= self.cable_length_step_3d
            # --- Parameter Calculation (Same as 2D version) ---
            layer_color_hex = layer.product_template_id.layer_color_fill or '#b0b0b0'
            diameter = layer.diameter
            thickness = layer.thickness
            qty = int(layer.product_uom_qty)
            layer_type = layer.product_template_id.cable_type

            # Convert color hex to RGBA for trimesh
            try:
                color_rgba = trimesh.visual.color.hex_to_rgba(layer_color_hex)
            except ValueError:
                _logger.warning(f"Invalid hex color '{layer_color_hex}' for layer {index}. Using gray.")
                color_rgba = [128, 128, 128, 255]  # Default gray RGBA

            # TODO: Get BOM-specific colors if bom=True (similar to 2D)
            if bom:
                colors = bom._get_colors()  # Adapt if structure differs
            else:
                colors = self._get_colors(qty)  # Uses SO method

            # --- Layer Type Specific 3D Mesh Creation ---

            # conductor layer
            if layer_type == 'phase_conductor':
                rec_cond = self._get_conductor_dimension(layer)
                shape_cond = 'sector' if rec_cond and rec_cond.conductor_shape == 'Shaped' else 'circular'
                cond_color_hex = layer_color_hex  # Base color
                if rec_cond and layer_color_hex == '#b0b0b0':
                    if rec_cond.conductor_material == 'Copper':
                        cond_color_hex = '#ffa600'
                    elif rec_cond.conductor_material == 'Aluminium':
                        cond_color_hex = '#b0b0b0'
                try:
                    cond_color_rgba = trimesh.visual.color.hex_to_rgba(cond_color_hex)
                except ValueError:
                    cond_color_rgba = color_rgba  # Fallback to default layer color

                conductor_radius = diameter / 2

                # Calculate outer_radius for placement (same logic as 2D, with index checks)
                outer_radius = 0.0
                try:
                    if qty != layer.order_id.no_cores:
                        if index + 4 < len(layers) and index + 1 < len(layers):
                            outer_radius = (layers[index + 4].diameter - layers[index + 1].diameter) / 2
                    else:
                        if index + 2 < len(layers) and index + 1 < len(layers):
                            outer_radius = (layers[index + 2].diameter - layers[index + 1].diameter) / 2
                except IndexError:
                    pass  # Already logged in 2D part, ignore here for now
                outer_radius = max(0.0, outer_radius)

                angles = np.linspace(0, 2 * np.pi, qty, endpoint=False)
                angle_step = 360 / qty if qty > 0 else 360
                angle_start = 90  # Default start angle

                total_cores = layer.order_id.no_cores
                core_index = 0

                if total_cores <= 4 or shape_cond.lower() == 'sector':
                    for i_core, (angle, color) in enumerate(zip(angles, colors)):
                        if shape_cond.lower() == 'circular':
                            x_center_c = center_x + outer_radius * np.cos(angle)
                            y_center_c = center_y + outer_radius * np.sin(angle)
                            # Create 3D Cylinder for circular conductor
                            if conductor_radius > 1e-6:  # Avoid zero-radius cylinders
                                mesh = trimesh.primitives.Cylinder(
                                    radius=conductor_radius, height=cable_length, sections=32)
                                # Apply transform and color
                                transform = trimesh.transformations.translation_matrix(
                                    [x_center_c, y_center_c, 0])  # Z=0 initially
                                mesh.apply_transform(transform)
                                mesh.visual.face_colors = cond_color_rgba
                                # all_3d_meshes.append(mesh)

                                layup_config1, config1 = self.env['lu.diameter.multiplication.factor']._get_layup_configuration(7)
                                for layer_num_ins, cores_in_layer_ins in enumerate(layup_config1):
                                    multiplier_factor_ins = config1.multiplier_factor
                                    insulation_diameter_ins = diameter / 3  # todo add correct diameter
                                    insulation_radius_ins = insulation_diameter_ins / 2
                                    total_radius_layup_ins = multiplier_factor_ins * insulation_radius_ins - insulation_radius_ins
                                    layer_radius_layup_ins = total_radius_layup_ins - (
                                            insulation_diameter_ins * (len(layup_config1) - layer_num_ins - 1))
                                    rotation_ins = 0
                                    if index > 0: rotation_ins = np.deg2rad(
                                        layers[index - 1].product_template_id.rotation) if layer_num_ins == 0 else 0
                                    angles_layup_ins = np.linspace(
                                        rotation_ins, 2 * np.pi + rotation_ins, cores_in_layer_ins, endpoint=False)

                                    for angle_layup_ins in angles_layup_ins:
                                        x_layup_ins = x_center_c + layer_radius_layup_ins * np.cos(angle_layup_ins)
                                        y_layup_ins = y_center_c + layer_radius_layup_ins * np.sin(angle_layup_ins)

                                        if insulation_radius_ins > 1e-6:
                                            mesh = trimesh.primitives.Cylinder(radius=insulation_radius_ins,
                                                                               height=cable_length, sections=32)
                                            transform = trimesh.transformations.translation_matrix(
                                                [x_layup_ins, y_layup_ins, 0])
                                            mesh.apply_transform(transform)
                                            # Apply color (similar to <= 4 cores)
                                            ins_color_rgba_layup = trimesh.visual.color.hex_to_rgba(cond_color_hex)
                                            mesh.visual.face_colors = ins_color_rgba_layup
                                            all_3d_meshes.append(mesh)

                        elif shape_cond.lower() == 'sector':
                            # --- Sector Calculation (Same parameters as 2D) ---
                            current_angle_start = angle_start + i_core * angle_step
                            try:
                                # Recalculate or retrieve parameters needed for _create_rounded_sector
                                if qty == total_cores:
                                    if index + 2 < len(layers) and index + 1 < len(layers):
                                        sector_cond_radius = (layers[index + 2].diameter - 0.2) / 2
                                        sector_thickness = layers[index + 1].thickness
                                    else:
                                        raise IndexError(
                                            "Index out of bounds for sector radius/thickness (matching qty)")
                                else:
                                    if index + 4 < len(layers) and index + 1 < len(layers):
                                        sector_cond_radius = (layers[index + 4].diameter - 0.7) / 2
                                        sector_thickness = layers[index + 1].thickness
                                    else:
                                        raise IndexError(
                                            "Index out of bounds for sector radius/thickness (non-matching qty)")

                                rounding_angle_mult = 0.35 if layers[index + 1].thickness <= 1 else 1.0
                                rounding_radius = layer.product_template_id.rounding_angle * rounding_angle_mult
                                offset_distance = 0
                                offset_x = offset_distance * np.cos(np.deg2rad(current_angle_start + angle_step / 2))
                                offset_y = offset_distance * np.sin(np.deg2rad(current_angle_start + angle_step / 2))

                                # Use _create_rounded_sector to get the Shapely polygon
                                rounded_sector_cond_poly = self._create_rounded_sector(
                                    (center_x + offset_x, center_y + offset_y), sector_cond_radius, current_angle_start,
                                    current_angle_start + angle_step, sector_thickness, rounding_radius)

                                if rounded_sector_cond_poly and rounded_sector_cond_poly.exterior:
                                    # Get vertices for extrusion
                                    vertices_2d = np.array(rounded_sector_cond_poly.exterior.xy).T

                                    if len(vertices_2d) >= 3:
                                        # Extrude the 2D polygon
                                        mesh = trimesh.creation.extrude_polygon(vertices_2d, height=cable_length)
                                        # Transform is applied later (after centering Z)
                                        mesh.visual.face_colors = cond_color_rgba
                                        all_3d_meshes.append(mesh)
                                    else:
                                        _logger.warning(
                                            f"Sector {i_core} for layer {index}: Not enough vertices ({len(vertices_2d)}) after rounding. Skipping.")
                                else:
                                    _logger.warning(
                                        f"Could not create rounded sector polygon for 3D extrusion (layer {index}, core {i_core}).")

                            except IndexError as e:
                                _logger.error(
                                    f"Error calculating sector parameters for 3D (layer {index}, core {i_core}): {e}")
                            except Exception as e:
                                _logger.error(f"Error creating 3D sector for layer {index}, core {i_core}: {e}")

                else:  # Layup config for > 4 cores
                    # ... (Existing logic for > 4 cores using layup_config) ...
                    for layer_num, cores_in_layer in enumerate(layup_config):
                        multiplier_factor = layers[index + 1].product_template_id.multiplier_factor if layer_num > 0 and \
                                                                                                       layers[
                                                                                                           index + 1].product_template_id.multiplier_factor > 0 else config.multiplier_factor
                        insulation_diameter = layers[index + 1].product_template_id.custom_diameter if layers[
                                                                                                           index + 1].product_template_id.custom_diameter > 0 else \
                        layers[index + 1].diameter
                        total_radius_layup = multiplier_factor * (insulation_diameter / 2) - (insulation_diameter / 2)
                        layer_radius_layup = total_radius_layup - (
                                    insulation_diameter * (len(layup_config) - layer_num - 1))
                        rotation_layup = np.deg2rad(layer.product_template_id.rotation) if layer_num == 0 else 0
                        angles_layup = np.linspace(rotation_layup, 2 * np.pi + rotation_layup, cores_in_layer,
                                                   endpoint=False)

                        for angle_layup in angles_layup:
                            if core_index >= total_cores: break
                            x_center_layup = center_x + layer_radius_layup * np.cos(angle_layup)
                            y_center_layup = center_y + layer_radius_layup * np.sin(angle_layup)
                            conductor_diameter_layup = layer.product_template_id.custom_diameter if layer.product_template_id.custom_diameter > 0 else layer.diameter
                            conductor_radius_layup = conductor_diameter_layup / 2

                            if conductor_radius_layup > 1e-6:
                                mesh = trimesh.primitives.Cylinder(radius=conductor_radius_layup, height=cable_length,
                                                                   sections=32)
                                transform = trimesh.transformations.translation_matrix(
                                    [x_center_layup, y_center_layup, 0])
                                mesh.apply_transform(transform)
                                mesh.visual.face_colors = cond_color_rgba
                                # all_3d_meshes.append(mesh)

                                layup_config1, config1 = self.env['lu.diameter.multiplication.factor']._get_layup_configuration(7)
                                for layer_num_ins, cores_in_layer_ins in enumerate(layup_config1):
                                    multiplier_factor_ins = config1.multiplier_factor
                                    insulation_diameter_ins = diameter / 3  # todo add correct diameter
                                    insulation_radius_ins = insulation_diameter_ins / 2
                                    total_radius_layup_ins = multiplier_factor_ins * insulation_radius_ins - insulation_radius_ins
                                    layer_radius_layup_ins = total_radius_layup_ins - (
                                            insulation_diameter_ins * (len(layup_config1) - layer_num_ins - 1))
                                    rotation_ins = 0
                                    if index > 0: rotation_ins = np.deg2rad(
                                        layers[index - 1].product_template_id.rotation) if layer_num_ins == 0 else 0
                                    angles_layup_ins = np.linspace(
                                        rotation_ins, 2 * np.pi + rotation_ins, cores_in_layer_ins, endpoint=False)

                                    for angle_layup_ins in angles_layup_ins:
                                        x_layup_ins = x_center_layup + layer_radius_layup_ins * np.cos(angle_layup_ins)
                                        y_layup_ins = y_center_layup + layer_radius_layup_ins * np.sin(angle_layup_ins)

                                        if insulation_radius_ins > 1e-6:
                                            mesh = trimesh.primitives.Cylinder(radius=insulation_radius_ins,
                                                                               height=cable_length, sections=32)
                                            transform = trimesh.transformations.translation_matrix(
                                                [x_layup_ins, y_layup_ins, 0])
                                            mesh.apply_transform(transform)
                                            # Apply color (similar to <= 4 cores)
                                            ins_color_rgba_layup = trimesh.visual.color.hex_to_rgba(cond_color_hex)
                                            mesh.visual.face_colors = ins_color_rgba_layup
                                            all_3d_meshes.append(mesh)

                            core_index += 1

            # phase insulation layer
            elif layer_type == 'phase_insulation':
                insulation_radius = diameter / 2
                total_cores = layer.order_id.no_cores  # Get total cores from order

                if total_cores <= 4:
                    # Calculate placement radius (same logic as 2D)
                    outer_radius_ins = 0.0
                    try:
                        if index + 1 < len(layers): outer_radius_ins = (layers[index + 1].diameter - diameter) / 2
                    except IndexError:
                        pass
                    outer_radius_ins = max(0.0, outer_radius_ins)

                    angles_ins = np.linspace(0, 2 * np.pi, qty, endpoint=False)

                    for angle_ins, color_name in zip(angles_ins, colors):
                        x_ins = center_x + outer_radius_ins * np.cos(angle_ins)
                        y_ins = center_y + outer_radius_ins * np.sin(angle_ins)

                        if shape.lower() == 'circular':  # Only handle circular insulation here
                            if insulation_radius > 1e-6:
                                mesh = trimesh.primitives.Cylinder(radius=insulation_radius, height=cable_length,
                                                                   sections=32)
                                transform = trimesh.transformations.translation_matrix([x_ins, y_ins, 0])
                                mesh.apply_transform(transform)
                                # --- Apply Color (potentially dual color) ---
                                ins_color_rgba = color_rgba  # Default
                                if bom:
                                    try:
                                        dual_color = color_name.split('/') if '/' in color_name else [color_name,
                                                                                                      color_name]
                                        # For 3D, maybe just use the first color? Or average them?
                                        # Using first color for simplicity:
                                        color1_hex = bom._get_color_by_reference_name(dual_color[0])  # Needs hex output
                                        ins_color_rgba = trimesh.visual.color.hex_to_rgba(color1_hex)
                                    except Exception as e:
                                        _logger.warning(
                                            f"Failed to get/convert BOM color '{color_name}' for insulation: {e}")
                                else:  # Default non-BOM color
                                    ins_color_rgba = trimesh.visual.color.hex_to_rgba('#a3a3a3')  # Default gray

                                mesh.visual.face_colors = ins_color_rgba
                                all_3d_meshes.append(mesh)

                        elif shape.lower() == 'sector':
                            # --- Sector Insulation (Extrude rounded sector) ---
                            current_angle_start = angle_start + i_core * angle_step  # Needs i_core from conductor loop? This logic might be flawed if insulation is separate loop.
                            try:
                                # Recalculate or retrieve parameters needed for _create_rounded_sector
                                if qty == total_cores:
                                    if index + 1 < len(layers):  # Use insulation thickness
                                        sector_cond_radius = (layers[
                                                                  index + 2].diameter - 0.2) / 2  # Base radius from conductor layer
                                        sector_thickness = layers[index + 1].thickness
                                    else:
                                        raise IndexError(
                                            "Index out of bounds for sector radius/thickness (matching qty)")
                                else:
                                    if index + 1 < len(layers):
                                        sector_cond_radius = (layers[
                                                                  index + 4].diameter - 0.7) / 2  # Base radius from conductor layer
                                        sector_thickness = layers[index + 1].thickness
                                    else:
                                        raise IndexError(
                                            "Index out of bounds for sector radius/thickness (non-matching qty)")

                                rounding_angle_mult = 0.35 if layers[index + 1].thickness <= 1 else 1.0
                                rounding_radius = layer.product_template_id.rounding_angle * rounding_angle_mult
                                offset_distance = 0
                                offset_x = offset_distance * np.cos(np.deg2rad(current_angle_start + angle_step / 2))
                                offset_y = offset_distance * np.sin(np.deg2rad(current_angle_start + angle_step / 2))

                                # Use _create_rounded_sector with thickness = -1 for insulation shape
                                rounded_sector_ins_poly = self._create_rounded_sector(
                                    (center_x + offset_x, center_y + offset_y), sector_cond_radius, current_angle_start,
                                    current_angle_start + angle_step, -1, rounding_radius)

                                if rounded_sector_ins_poly and rounded_sector_ins_poly.exterior:
                                    vertices_2d_ins = np.array(rounded_sector_ins_poly.exterior.xy).T
                                    if len(vertices_2d_ins) >= 3:
                                        mesh = trimesh.creation.extrude_polygon(vertices_2d_ins, height=cable_length)
                                        # --- Apply Color ---
                                        ins_color_rgba_sec = color_rgba  # Default
                                        if bom:
                                            try:
                                                color_hex_sec = bom._get_color_by_reference_name(
                                                    color_name)  # Needs hex output
                                                ins_color_rgba_sec = trimesh.visual.color.hex_to_rgba(color_hex_sec)
                                            except Exception as e:
                                                _logger.warning(
                                                    f"Failed to get/convert BOM color '{color_name}' for sector insulation: {e}")
                                        else:
                                            ins_color_rgba_sec = trimesh.visual.color.hex_to_rgba('#a3a3a3')

                                        mesh.visual.face_colors = ins_color_rgba_sec
                                        all_3d_meshes.append(mesh)
                                    else:
                                        _logger.warning(
                                            f"Insulation Sector {i_core} for layer {index}: Not enough vertices ({len(vertices_2d_ins)}). Skipping.")
                                else:
                                    _logger.warning(
                                        f"Could not create rounded sector insulation polygon for 3D (layer {index}, core {i_core}).")

                            except IndexError as e:
                                _logger.error(
                                    f"Error calculating sector insulation parameters for 3D (layer {index}, core {i_core}): {e}")
                            except Exception as e:
                                _logger.error(
                                    f"Error creating 3D sector insulation for layer {index}, core {i_core}: {e}")

                else:  # Layup config for > 4 cores insulation
                    # ... (Existing logic for > 4 cores insulation using layup_config) ...
                    core_index_ins = 0
                    for layer_num_ins, cores_in_layer_ins in enumerate(layup_config):
                        multiplier_factor_ins = layer.product_template_id.multiplier_factor if layer_num_ins > 0 and layer.product_template_id.multiplier_factor > 0 else config.multiplier_factor
                        insulation_diameter_ins = layer.product_template_id.custom_diameter if layer.product_template_id.custom_diameter > 0 else layer.diameter
                        insulation_radius_ins = insulation_diameter_ins / 2
                        total_radius_layup_ins = multiplier_factor_ins * insulation_radius_ins - insulation_radius_ins
                        layer_radius_layup_ins = total_radius_layup_ins - (
                                    insulation_diameter_ins * (len(layup_config) - layer_num_ins - 1))
                        rotation_ins = 0
                        if index > 0: rotation_ins = np.deg2rad(
                            layers[index - 1].product_template_id.rotation) if layer_num_ins == 0 else 0
                        angles_layup_ins = np.linspace(rotation_ins, 2 * np.pi + rotation_ins, cores_in_layer_ins,
                                                       endpoint=False)

                        for angle_layup_ins in angles_layup_ins:
                            if core_index_ins >= total_cores: break
                            x_layup_ins = center_x + layer_radius_layup_ins * np.cos(angle_layup_ins)
                            y_layup_ins = center_y + layer_radius_layup_ins * np.sin(angle_layup_ins)

                            if shape.lower() == 'circular':  # Only circular handled here
                                if insulation_radius_ins > 1e-6:
                                    mesh = trimesh.primitives.Cylinder(radius=insulation_radius_ins,
                                                                       height=cable_length, sections=32)
                                    transform = trimesh.transformations.translation_matrix(
                                        [x_layup_ins, y_layup_ins, 0])
                                    mesh.apply_transform(transform)
                                    # Apply color (similar to <= 4 cores)
                                    ins_color_rgba_layup = color_rgba  # Default
                                    if bom:
                                        try:
                                            color_layup = colors[core_index_ins % len(colors)]
                                            dual_color_layup = color_layup.split('/') if '/' in color_layup else [
                                                color_layup, color_layup]
                                            color1_hex_layup = bom._get_color_by_reference_name(
                                                dual_color_layup[0])  # Needs hex output
                                            ins_color_rgba_layup = trimesh.visual.color.hex_to_rgba(color1_hex_layup)
                                        except Exception as e:
                                            _logger.warning(
                                                f"Failed to get/convert BOM color '{color_layup}' for layup insulation: {e}")
                                    else:
                                        ins_color_rgba_layup = trimesh.visual.color.hex_to_rgba('#a3a3a3')

                                    mesh.visual.face_colors = ins_color_rgba_layup
                                    all_3d_meshes.append(mesh)
                            core_index_ins += 1

            # neutral conductor layer
            elif layer_type == 'neutral_conductor':
                rec_neutral = self._get_neutral_conductor_dimension(layer)
                shape_neutral = 'sector' if rec_neutral and rec_neutral.conductor_shape == 'Shaped' else 'circular'
                neutral_color_hex = layer_color_hex  # Base color
                if rec_neutral:
                    if rec_neutral.conductor_material == 'Copper':
                        neutral_color_hex = '#ffa600'
                    elif rec_neutral.conductor_material == 'Aluminium':
                        neutral_color_hex = '#b0b0b0'
                try:
                    neutral_color_rgba = trimesh.visual.color.hex_to_rgba(neutral_color_hex)
                except ValueError:
                    neutral_color_rgba = color_rgba  # Fallback

                # --- Parameter Calculation (same checks as 2D) ---
                conductor_radius_neutral = 0.0
                insulation_radius_neutral = 0.0
                outer_radius_neutral_placement = 0.0
                thickness_neutral_ins = 0.0
                try:
                    if index + 1 < len(layers):
                        thickness_neutral_ins = layers[index + 1].thickness
                        conductor_radius_neutral = (diameter - thickness_neutral_ins * 2) / 2
                        insulation_radius_neutral = (layers[index + 1].diameter - thickness_neutral_ins * 2) / 2
                    if len(layers) > 4: outer_radius_neutral_placement = layers[4].diameter / 3
                except IndexError:
                    pass  # Ignore errors here, handled in 2D
                conductor_radius_neutral = max(0.0, conductor_radius_neutral)
                insulation_radius_neutral = max(0.0, insulation_radius_neutral)
                outer_radius_neutral_placement = max(0.0, outer_radius_neutral_placement)

                angle_neutral = 0.0

                bom_color_neutral_rgba = trimesh.visual.color.hex_to_rgba('#0000ff')  # Default blue
                if bom:
                    try:
                        last_color = colors[-1] if colors else 'Blue'
                        dual_color_neutral = last_color.split('/') if '/' in last_color else [last_color, last_color]
                        bom_color_neutral_hex = bom._get_color_by_reference_name(dual_color_neutral[0])  # Needs hex
                        bom_color_neutral_rgba = trimesh.visual.color.hex_to_rgba(bom_color_neutral_hex)
                    except Exception as e:
                        _logger.warning(f"Failed to get/convert BOM color for neutral insulation: {e}")
                else:
                    bom_color_neutral_rgba = trimesh.visual.color.hex_to_rgba('#a3a3a3')  # Default gray if no BOM

                if shape_neutral.lower() == 'circular':
                    x_center_neutral = center_x + outer_radius_neutral_placement * np.cos(angle_neutral)
                    y_center_neutral = center_y + outer_radius_neutral_placement * np.sin(angle_neutral)
                    # Conductor Mesh
                    if conductor_radius_neutral > 1e-6:
                        mesh_cond_n = trimesh.primitives.Cylinder(radius=conductor_radius_neutral, height=cable_length,
                                                                  sections=32)
                        transform_cond_n = trimesh.transformations.translation_matrix(
                            [x_center_neutral, y_center_neutral, 0])
                        mesh_cond_n.apply_transform(transform_cond_n)
                        mesh_cond_n.visual.face_colors = neutral_color_rgba
                        all_3d_meshes.append(mesh_cond_n)
                    # Insulation Mesh
                    if insulation_radius_neutral > 1e-6:
                        mesh_ins_n = trimesh.primitives.Cylinder(radius=insulation_radius_neutral, height=cable_length,
                                                                 sections=32)
                        transform_ins_n = trimesh.transformations.translation_matrix(
                            [x_center_neutral, y_center_neutral, 0])  # Same center
                        mesh_ins_n.apply_transform(transform_ins_n)
                        mesh_ins_n.visual.face_colors = bom_color_neutral_rgba  # Use BOM/default color
                        all_3d_meshes.append(mesh_ins_n)

                elif shape_neutral.lower() == 'sector':
                    # --- Sector Calculation (same params as 2D) ---
                    try:
                        if index + 2 < len(layers):
                            sector_cond_radius_n = (layers[index + 2].diameter - 0.7) / 2
                        else:
                            sector_cond_radius_n = 0.0
                        if index + 1 < len(layers):
                            sector_thickness_n = layers[index + 1].thickness
                        else:
                            sector_thickness_n = 0.0

                        sector_cond_radius_n = max(0.0, sector_cond_radius_n)
                        rounding_angle_mult_n = 0.35 if sector_thickness_n <= 1 else 1.0
                        rounding_radius_n = layer.product_template_id.rounding_angle * rounding_angle_mult_n
                        angle_start_n = -30;
                        angle_step_n = 60
                        offset_x_n = 0;
                        offset_y_n = 0

                        # Create conductor polygon
                        rounded_sector_cond_n_poly = self._create_rounded_sector(
                            (center_x + offset_x_n, center_y + offset_y_n), sector_cond_radius_n, angle_start_n,
                            angle_start_n + angle_step_n, sector_thickness_n, rounding_radius_n)
                        if rounded_sector_cond_n_poly and rounded_sector_cond_n_poly.exterior:
                            vertices_2d_cond_n = np.array(rounded_sector_cond_n_poly.exterior.xy).T
                            if len(vertices_2d_cond_n) >= 3:
                                mesh_cond_n = trimesh.creation.extrude_polygon(vertices_2d_cond_n, height=cable_length)
                                mesh_cond_n.visual.face_colors = neutral_color_rgba
                                all_3d_meshes.append(mesh_cond_n)

                        # Create insulation polygon
                        rounded_sector_ins_n_poly = self._create_rounded_sector(
                            (center_x + offset_x_n, center_y + offset_y_n), sector_cond_radius_n, angle_start_n,
                            angle_start_n + angle_step_n, -1, rounding_radius_n)
                        if rounded_sector_ins_n_poly and rounded_sector_ins_n_poly.exterior:
                            vertices_2d_ins_n = np.array(rounded_sector_ins_n_poly.exterior.xy).T
                            if len(vertices_2d_ins_n) >= 3:
                                mesh_ins_n = trimesh.creation.extrude_polygon(vertices_2d_ins_n, height=cable_length)
                                mesh_ins_n.visual.face_colors = bom_color_neutral_rgba
                                all_3d_meshes.append(mesh_ins_n)

                    except Exception as e:
                        _logger.error(f"Error creating 3D neutral sector for layer {index}: {e}")

            # ['sheath', 'filler', 'tape'] layers
            elif layer_type in ['sheath', 'filler', 'tape']:
                sheath_color_hex = layer.product_template_id.layer_color_fill or '#1f1f1f'
                try:
                    sheath_color_rgba = trimesh.visual.color.hex_to_rgba(sheath_color_hex)
                except ValueError:
                    sheath_color_rgba = [31, 31, 31, 255]  # Default dark gray

                sheath_outer_radius = layer.product_template_id.custom_diameter / 2 if layer.product_template_id.custom_diameter > 0 else diameter / 2
                sheath_outer_radius = max(0.0, sheath_outer_radius)

                # Assume sheath covers everything inside it. Model as solid cylinder.
                if sheath_outer_radius > 1e-6:
                    mesh = trimesh.primitives.Cylinder(radius=sheath_outer_radius, height=cable_length, sections=64)
                    # Handle strip color if present (more complex - overlaying another mesh?)
                    # Simple approach: Ignore strip for 3D for now.
                    # Advanced: Create a thin wedge mesh for the strip and add it.
                    mesh.visual.face_colors = sheath_color_rgba
                    all_3d_meshes.append(mesh)

            # armour layer
            elif layer_type == 'armour':
                prev_diameter = 0.0
                if index > 0: prev_diameter = layers[index - 1].product_template_id.custom_diameter if layers[
                                                                                                           index - 1].product_template_id.custom_diameter > 0 else \
                layers[index - 1].diameter
                current_diameter = layer.product_template_id.custom_diameter if layer.product_template_id.custom_diameter > 0 else diameter
                thickness_armour = max(0.0, (current_diameter - prev_diameter) / 2)
                armour_outer_radius = current_diameter / 2
                armour_placement_radius = max(0.0,
                                              armour_outer_radius - thickness_armour / 2)  # Radius where centers of armour elements sit

                armour_color_hex = layer.product_template_id.layer_color_fill or '#b0b0b0'
                try:
                    armour_color_rgba = trimesh.visual.color.hex_to_rgba(armour_color_hex)
                except ValueError:
                    armour_color_rgba = [176, 176, 176, 255]  # Default light gray

                armour_type_shape = ''
                armour_tape_width = 0
                for attr_val in layer.product_template_attribute_value_ids:
                    attr_name = attr_val.attribute_id.name.lower()
                    if 'armour type shape' in attr_name:
                        armour_type_shape = attr_val.product_attribute_value_id.name.lower()
                    elif 'tape width' in attr_name:
                        try:
                            armour_tape_width = layer.product_template_id.custom_armour_tape_width if layer.product_template_id.custom_armour_tape_width > 0 else float(
                                attr_val.product_attribute_value_id.name)
                        except (ValueError, TypeError):
                            armour_tape_width = 0

                if 'round' in armour_type_shape:
                    wire_radius = thickness_armour / 2
                    if wire_radius > 1e-6 and armour_placement_radius > 0:
                        num_wires = int(2 * np.pi * armour_placement_radius / (2 * wire_radius))
                        num_wires = max(1, num_wires)
                        angles_armour = np.linspace(0, 2 * np.pi, num_wires, endpoint=False)
                        for angle_armour in angles_armour:
                            x_armour = center_x + armour_placement_radius * np.cos(angle_armour)
                            y_armour = center_y + armour_placement_radius * np.sin(angle_armour)
                            # Create small cylinder for each wire
                            mesh_wire = trimesh.primitives.Cylinder(radius=wire_radius, height=cable_length,
                                                                    sections=16)  # Fewer sections for small wires
                            transform_wire = trimesh.transformations.translation_matrix([x_armour, y_armour, 0])
                            mesh_wire.apply_transform(transform_wire)
                            mesh_wire.visual.face_colors = armour_color_rgba
                            all_3d_meshes.append(mesh_wire)
                else:  # Tape armour
                    # Model as a solid cylinder representing the armour layer volume
                    armour_inner_radius = max(0.0, armour_outer_radius - thickness_armour)
                    if armour_outer_radius > armour_inner_radius:
                        # Option 1: Simple solid cylinder
                        # mesh = trimesh.primitives.Cylinder(radius=armour_outer_radius, height=cable_length, sections=64)
                        # mesh.visual.face_colors = armour_color_rgba
                        # all_3d_meshes.append(mesh)
                        # Option 2: Extruded Annulus (like tape)
                        try:
                            annulus_poly_armour = Polygon([(0, 0)]).buffer(armour_outer_radius).difference(
                                Polygon([(0, 0)]).buffer(armour_inner_radius))
                            if annulus_poly_armour.exterior:
                                vertices_2d_armour = np.array(annulus_poly_armour.exterior.xy).T
                                if len(vertices_2d_armour) >= 3:
                                    mesh = trimesh.creation.extrude_polygon(vertices_2d_armour, height=cable_length)
                                    mesh.visual.face_colors = armour_color_rgba
                                    all_3d_meshes.append(mesh)
                                else:
                                    _logger.warning(
                                        f"Armour tape layer {index}: Not enough vertices for annulus polygon.")
                            else:
                                _logger.warning(f"Armour tape layer {index}: Could not create annulus polygon.")
                        except Exception as e:
                            _logger.error(f"Error creating 3D armour tape layer {index} via extrusion: {e}. Skipping.")

            else:
                _logger.info(f"Skipping layer type '{layer_type}' in 3D generation.")
                continue

        # --- Post-processing and Combining Meshes ---
        if not all_3d_meshes:
            _logger.warning("No 3D meshes were generated for the cable.")
            return None

        # Center all meshes vertically before combining
        centered_meshes = []
        for mesh in all_3d_meshes:
            if mesh is None or not hasattr(mesh, 'bounds'): continue  # Skip invalid meshes
            try:
                z_min, z_max = mesh.bounds[:, 2]
                center_z_offset = -(z_min + z_max) / 2.0
                # Only apply Z offset if significant
                if abs(center_z_offset) > 1e-6:
                    transform_z = trimesh.transformations.translation_matrix([0, 0, center_z_offset])
                    mesh.apply_transform(transform_z)
                centered_meshes.append(mesh)
            except Exception as e:
                _logger.error(f"Error centering mesh: {e}. Skipping mesh.")

        if not centered_meshes:
            _logger.warning("No valid meshes remained after centering.")
            return None

        # Combine all centered meshes
        try:
            _logger.info(f"Concatenating {len(centered_meshes)} individual 3D meshes...")
            final_mesh = trimesh.util.concatenate(centered_meshes)
            # Optional: Clean up the mesh (can be slow)
            # final_mesh.process()
            _logger.info(
                f"Final combined mesh has {len(final_mesh.vertices)} vertices and {len(final_mesh.faces)} faces.")
        except Exception as e:
            _logger.error(f"Failed to concatenate 3D meshes: {e}")
            # Optionally return the list of meshes or raise error
            return None  # Return None if concatenation fails

        return final_mesh
