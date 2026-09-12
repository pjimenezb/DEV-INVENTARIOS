import os
import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.lib.colors import red, black

def generate_pdf_batch(marbetes_batch, start_folio, config_coords, output_dir, debug_mode=False, is_blank=False):
    """
    Generates a single PDF containing up to 3 marbetes (1 page).
    Returns the next starting folio.
    """
    if not marbetes_batch:
        return start_folio

    # Calculate folio range for filename
    end_folio = start_folio + len(marbetes_batch) - 1
    start_str = str(start_folio).zfill(5)
    end_str = str(end_folio).zfill(5)
    
    if start_folio == end_folio:
        filename = f"{start_str}.pdf"
    else:
        # e.g., 00001-00002-00003.pdf or 00001-00002.pdf
        folios_str = "-".join([str(f).zfill(5) for f in range(start_folio, end_folio + 1)])
        filename = f"{folios_str}.pdf"
        
    filepath = os.path.join(output_dir, filename)
    
    c = canvas.Canvas(filepath, pagesize=letter)
    
    # Coords from config
    # El usuario proporcionó valores base (98, 272)
    # y los siguientes desfases físicos (hacia abajo, por lo que hay que sumar para subir):
    # Marbete 1: 0.5 cm = ~14.17 pt
    # Marbete 2: 0.7 cm = ~19.84 pt
    # Marbete 3: 1.0 cm = ~28.35 pt
    
    # Coords from config
    global_row_offset_y = config_coords.get('global_row_offset_y', 272)
    base_y = config_coords.get('base_y', 98)
    
    adj_m1 = config_coords.get('ajuste_m1_y', 0)
    adj_m2 = config_coords.get('ajuste_m2_y', 0)
    adj_m3 = config_coords.get('ajuste_m3_y', 0)
    
    font_size = config_coords.get('font_size', 10)
    
    # Cálculo lineal + Ajuste individual manual
    exact_y_positions = [
        base_y + adj_m1, 
        base_y + global_row_offset_y + adj_m2, 
        base_y + (global_row_offset_y * 2) + adj_m3
    ]
    
    c1_x = config_coords.get('col1', {}).get('x', 30)
    c2_x = config_coords.get('col2', {}).get('x', 230)
    c3_x = c2_x + config_coords.get('col3', {}).get('x_offset_from_col2', 200)
    
    elements = config_coords.get('elements', {})
    
    current_date = datetime.datetime.now().strftime("%B %Y").upper()

    folio_counter = start_folio

    for i, marbete in enumerate(marbetes_batch):
        # Usar las posiciones Y exactas calculadas para cada fila (0, 1, 2)
        current_y = exact_y_positions[i] if i < len(exact_y_positions) else exact_y_positions[-1]
        
        folio_str = str(folio_counter).zfill(5)
        marbete['folio'] = folio_str # <--- INYECCIÓN QUIRÚRGICA
        np_str = marbete['np']
        almacen = marbete['almacen']
        
        # --- Column 1 (Rotated) ---
        c.saveState()
        c.translate(c1_x, current_y)
        c.rotate(90)
        
        c1_np_el = elements.get('col1_np', {})
        if c1_np_el.get('enabled', True):
            c.setFont("Helvetica-Bold", font_size + c1_np_el.get('font_size_add', 4))
            draw_x_np = c1_np_el.get('x_add', 100)
            draw_y_np = c1_np_el.get('y_offset', 0)
            c.drawCentredString(draw_x_np, draw_y_np, np_str)
            if debug_mode:
                c.setFillColor(red)
                c.setFont("Helvetica", 5)
                c.drawString(draw_x_np, draw_y_np + 2, "col1_np")
                c.setFillColor(black)

        c1_fol_el = elements.get('col1_folio', {})
        if c1_fol_el.get('enabled', True):
            c.setFont("Helvetica-Bold", font_size + c1_fol_el.get('font_size_add', 4))
            draw_x_fol = c1_fol_el.get('x_add', 100)
            draw_y_fol = c1_fol_el.get('y_offset', -20)
            c.drawCentredString(draw_x_fol, draw_y_fol, folio_str)
            if debug_mode:
                c.setFillColor(red)
                c.setFont("Helvetica", 5)
                c.drawString(draw_x_fol, draw_y_fol + 2, "col1_folio")
                c.setFillColor(black)

        c.restoreState()

        # Helper function for Col 2 and Col 3
        def draw_conteo_block(x_offset, title, is_col3=False):
            # Helper to get element properties safely
            def get_el(name):
                return elements.get(name, {})
                
            def set_font(is_bold=False, add_size=0):
                font_name = "Helvetica-Bold" if is_bold else "Helvetica"
                c.setFont(font_name, font_size + add_size)
                
            def debug_lbl(name, x, y):
                if debug_mode and not is_col3: # Only draw debug labels on Col 2 to avoid clutter
                    c.saveState()
                    c.setFillColor(red)
                    c.setFont("Helvetica", 5)
                    c.drawString(x, y + 2, name)
                    c.restoreState()

            c.setFillColor(black)

            def draw_el_text(key, text_val, is_bold=False, default_x=0, default_y=0, align='left'):
                el = get_el(key)
                if not el.get('enabled', True): return
                set_font(is_bold, el.get('font_size_add', 0))
                draw_x = x_offset + el.get('x_add', default_x)
                draw_y = current_y + el.get('y_offset', default_y)
                
                # Forzar conversión a string por si viene un float o int de la BD
                text_val_str = str(text_val) if text_val is not None else ""
                
                if align == 'center':
                    c.drawCentredString(draw_x, draw_y, text_val_str)
                else:
                    c.drawString(draw_x, draw_y, text_val_str)
                debug_lbl(key, draw_x, draw_y)

            def draw_el_rect(key, default_x, default_y, default_w, default_h):
                el = get_el(key)
                if not el.get('enabled', True): return
                draw_x = x_offset + el.get('x_add', default_x)
                draw_y = current_y + el.get('y_offset', default_y)
                c.rect(draw_x, draw_y, el.get('w', default_w), el.get('h', default_h))
                debug_lbl(key, draw_x, draw_y + el.get('h', default_h))

            # Title & Headers
            draw_el_text('titulo', title, True, 0, 120)
            draw_el_text('fecha', f"{current_date}", False, 0, 105)
            # Folio Horizontal (Bold, without "Folio: ")
            draw_el_text('folio_horizontal', folio_str, True, 0, 95)
            
            # Clave
            draw_el_text('lbl_clave', "Clave:", False, 0, 85)
            draw_el_rect('rect_clave', 0, 65, 150, 18)
            draw_el_text('val_clave', np_str, False, 5, 70)
            
            # Unidad
            draw_el_text('lbl_unidad', "Unidad:", False, 0, 45)
            draw_el_rect('rect_unidad', 40, 40, 40, 15)
            # Fetch from DB logic (marbete dict) if available, otherwise blank
            val_u_text = str(marbete.get('unidad', ''))
            draw_el_text('val_unidad', val_u_text, False, 60, 42, 'center')
            
            # Empaque
            draw_el_text('lbl_empaque', "Empaque:", False, 90, 45)
            draw_el_rect('rect_empaque', 140, 40, 40, 15)
            val_e_text = str(marbete.get('empaque', ''))
            draw_el_text('val_empaque', val_e_text, False, 160, 42, 'center')
            
            # Almacen
            draw_el_text('lbl_almacen', "Almacén:", False, 0, 20)
            draw_el_rect('rect_almacen', 0, 0, 150, 18)
            draw_el_text('val_almacen', almacen, False, 5, 5)
            
            # Cantidad
            draw_el_text('lbl_cantidad', "Cantidad:", False, 0, -15)
            draw_el_rect('rect_cantidad', 50, -20, 100, 15)
            val_qty_text = str(marbete.get('cantidad', ''))
            draw_el_text('val_cantidad', val_qty_text, False, 100, -18, 'center')
            
            # Contado por
            draw_el_text('lbl_contado', "Contado por:", False, 0, -40)
            draw_el_rect('rect_contado', 65, -45, 85, 15)
            val_cnt_text = str(marbete.get('contado_por', ''))
            draw_el_text('val_contado', val_cnt_text, False, 107, -43, 'center')

        # --- Column 2 (Segundo Conteo) ---
        draw_conteo_block(c2_x, "SEGUNDO CONTEO")
        
        # --- Column 3 (Primer Conteo) ---
        draw_conteo_block(c3_x, "PRIMER CONTEO", is_col3=True)

        folio_counter += 1
        
    c.save()
    return folio_counter

def create_all_pdfs(marbetes, config_coords, base_output_dir, start_folio=1, group_by_field='sheet', is_blank=False):
    pdf_count = 0
    folio_counter = start_folio
    
    # Keep track of unique groups in order
    groups = []
    for m in marbetes:
        grp = m.get(group_by_field, 'GENERAL')
        if not grp: grp = 'GENERAL'
        if grp not in groups:
            groups.append(grp)
            
    for grp in groups:
        grp_dir = os.path.join(base_output_dir, str(grp))
        os.makedirs(grp_dir, exist_ok=True)
        
        grp_marbetes = [m for m in marbetes if m.get(group_by_field, 'GENERAL') == grp]
        batch = []
        for m in grp_marbetes:
            batch.append(m)
            if len(batch) == 3:
                folio_counter = generate_pdf_batch(batch, folio_counter, config_coords, grp_dir, is_blank=is_blank)
                pdf_count += 1
                batch = []
                
        if batch:
            folio_counter = generate_pdf_batch(batch, folio_counter, config_coords, grp_dir, is_blank=is_blank)
            pdf_count += 1
            
    return pdf_count
