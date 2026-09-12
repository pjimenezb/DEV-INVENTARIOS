import re

with open('app.py', 'r') as f:
    content = f.read()

new_routes = """
# ============ MÓDULO PT: CONSOLIDADO CEDIS 1 ============

@app.route('/pt/consolidado_cedis1')
def pt_consolidado_cedis1_view():
    from core.local_db import init_db
    init_db()
    return render_template('pt_consolidado_cedis1.html')

@app.route('/api/pt/consolidado_cedis1/data')
def api_pt_consolidado_cedis1_data():
    from core.local_db import get_pt_consolidado_cedis1, get_pt_metadata
    return jsonify({
        'data': get_pt_consolidado_cedis1(),
        'last_update': get_pt_metadata('consolidado_cedis1_last_update')
    })

@app.route('/api/pt/consolidado_cedis1/reload', methods=['POST'])
def api_pt_consolidado_cedis1_reload():
    from core.local_db import get_pt_cedis1_odoo_data, get_pt_wms1_data, load_pt_consolidado_cedis1, get_pt_metadata
    
    odoo_data = get_pt_cedis1_odoo_data()
    wms_data = get_pt_wms1_data()
    
    if not odoo_data and not wms_data:
        return jsonify({'success': False, 'msg': 'No hay datos de Odoo ni WMS cargados para consolidar.'})

    # Encontrar columnas clave
    odoo_key_col = 'default_code'
    if odoo_data:
        first_odoo = odoo_data[0]
        cands = ['np', 'sku', 'clave', 'codigo', 'default_code', 'referencia']
        for cand in cands:
            for k in first_odoo.keys():
                if cand == k.lower():
                    odoo_key_col = k
                    break
            else: continue
            break
        else:
            odoo_key_col = list(first_odoo.keys())[0]

    wms_key_col = 'sku'
    if wms_data:
        first_wms = wms_data[0]
        cands = ['np', 'sku', 'clave', 'codigo', 'default_code', 'referencia', 'producto']
        for cand in cands:
            for k in first_wms.keys():
                if cand == k.lower():
                    wms_key_col = k
                    break
            else: continue
            break
        else:
            wms_key_col = list(first_wms.keys())[0]

    # Encontrar columnas QTY
    odoo_qty_col = 'qty'
    if odoo_data:
        first_odoo = odoo_data[0]
        cands = ['cantidad', 'qty', 'stock', 'existencia', 'quantity']
        for cand in cands:
            for k in first_odoo.keys():
                if cand in k.lower():
                    odoo_qty_col = k
                    break
            else: continue
            break

    wms_qty_col = 'qty'
    if wms_data:
        first_wms = wms_data[0]
        cands = ['cantidad', 'qty', 'stock', 'existencia', 'quantity']
        for cand in cands:
            for k in first_wms.keys():
                if cand in k.lower():
                    wms_qty_col = k
                    break
            else: continue
            break

    odoo_map = {}
    for r in odoo_data:
        k = str(r.get(odoo_key_col, '')).strip().upper()
        if not k: continue
        try:
            qty = float(r.get(odoo_qty_col, 0) or 0)
        except:
            qty = 0.0
        
        if k not in odoo_map:
            odoo_map[k] = dict(r)
            odoo_map[k]['_qty_sum_'] = qty
        else:
            odoo_map[k]['_qty_sum_'] += qty
            
    wms_map = {}
    for r in wms_data:
        k = str(r.get(wms_key_col, '')).strip().upper()
        if not k: continue
        try:
            qty = float(r.get(wms_qty_col, 0) or 0)
        except:
            qty = 0.0
            
        if k not in wms_map:
            wms_map[k] = dict(r)
            wms_map[k]['_qty_sum_'] = qty
        else:
            wms_map[k]['_qty_sum_'] += qty

    all_keys = set(odoo_map.keys()).union(set(wms_map.keys()))
    consolidado = []
    
    odoo_cols = list(odoo_data[0].keys()) if odoo_data else []
    wms_cols = list(wms_data[0].keys()) if wms_data else []
    
    for k in sorted(all_keys):
        in_odoo = k in odoo_map
        in_wms = k in wms_map
        
        estado = "AMBOS"
        if in_odoo and not in_wms:
            estado = "SOLO ODOO"
        elif in_wms and not in_odoo:
            estado = "SOLO WMS"
            
        rec = {
            'np_consolidado': k,
            'estado_consolidado': estado
        }
        
        qty_odoo_sum = odoo_map[k]['_qty_sum_'] if in_odoo else 0.0
        qty_wms_sum = wms_map[k]['_qty_sum_'] if in_wms else 0.0
        
        if in_odoo:
            odoo_row = odoo_map[k]
            for col in odoo_cols:
                rec[f'odoo_{col}'] = odoo_row.get(col, '')
        else:
            for col in odoo_cols:
                rec[f'odoo_{col}'] = ''
                
        if in_wms:
            wms_row = wms_map[k]
            for col in wms_cols:
                rec[f'wms_{col}'] = wms_row.get(col, '')
        else:
            for col in wms_cols:
                rec[f'wms_{col}'] = ''
                
        rec['qty_odoo_total'] = qty_odoo_sum
        rec['qty_wms_total'] = qty_wms_sum
        rec['diff_qty'] = qty_odoo_sum - qty_wms_sum
        
        consolidado.append(rec)
        
    success, msg = load_pt_consolidado_cedis1(consolidado)
    
    return jsonify({
        'success': success, 
        'msg': msg, 
        'data': consolidado,
        'last_update': get_pt_metadata('consolidado_cedis1_last_update') if success else ''
    })
"""

# Insert before '# ============ MÓDULO PT: CARGA ARCHIVOS WMS 1 ============'
content = content.replace('# ============ MÓDULO PT: CARGA ARCHIVOS WMS 1 ============', new_routes + '\n# ============ MÓDULO PT: CARGA ARCHIVOS WMS 1 ============')

with open('app.py', 'w') as f:
    f.write(content)

