import os
import json
import re
from collections import defaultdict
from flask import Flask, render_template, request, jsonify, Response
from werkzeug.utils import secure_filename
import time

from core.db_manager import DBManager
from core.excel_parser import parse_excel_for_marbetes, extract_unique_nps
from core.local_db import get_next_folio, init_db, insert_query, insert_cruce, get_all_query, get_all_cruce, insert_existencias, get_all_existencias, get_pool_nps, update_pool_location, update_pool_descriptions, get_wms_nps, update_wms_uom_empaque, update_wms_location, log_module_action, transfer_module_to_pool, empty_pool_final, connect
from core.pdf_engine import create_all_pdfs, generate_pdf_batch
from core.printer import get_printers, state, print_batch_job, print_pdf

app = Flask(__name__)
app.json.sort_keys = False
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['PDF_FOLDER'] = os.path.join(os.path.dirname(__file__), 'pdfs')
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.json')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['PDF_FOLDER'], exist_ok=True)



@app.after_request
def no_cache(resp):
    if resp.content_type and resp.content_type.startswith('text/html'):
        resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    return resp

@app.route('/')
def seleccion_inicio():
    return render_template('seleccion.html')

@app.route('/inventario_mp')
def configuraciones():
    config = load_config()
    return render_template('configuraciones.html', config=config)

@app.route('/inventario_pt')
def configuraciones_pt():
    config = load_config()
    return render_template('configuraciones_pt.html',
                           pt_queries=config.get('pt_queries', {}),
                           pt_wms=config.get('pt_wms', {}))

@app.route('/ejecuciones')
def ejecuciones():
    return render_template('ejecuciones.html')

@app.route('/pool_final')
def pool_final_view():
    return render_template('pool_final.html')

@app.route('/matriz')
def matriz_view():
    return render_template('matriz.html')

@app.route('/wms')
def wms_view():
    from core.local_db import init_db
    init_db()
    return render_template('wms.html')

@app.route('/api/wms/data')
def api_wms_data():
    from core.local_db import get_wms_data
    return jsonify({'data': get_wms_data()})

@app.route('/api/wms/update', methods=['POST'])
def api_wms_update():
    from core.local_db import update_wms_records
    payload = _module_payload('wms')
    if payload is None:
        return _module_denied('wms')
    records = payload.get('records', [])
    if not records:
        return jsonify({'success': False, 'msg': 'No se recibieron registros.'})
    success, msg = update_wms_records(records)
    log_module_action('wms', request.path, f"update -> {msg}")
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/wms/upload', methods=['POST'])
def api_wms_upload():
    """Recibe hasta 3 archivos (B1, CEDIS 4, NAVE 5), los parsea a estructura pool_final,
    vacía wms_data y la vuelve a llenar."""
    if request.form.get('module') != 'wms':
        return _module_denied('wms')
    import pandas as pd
    from core.local_db import load_wms_data

    sheet_config = {
        'b1': 'WMS-B1',
        'cedis4': 'WMS-CEDIS 4',
        'nave5': 'WMS-NAVE 5',
    }

    def _first(row, *headers):
        for h in headers:
            if h in row and row[h] is not None:
                try:
                    if pd.isna(row[h]):
                        continue
                except Exception:
                    pass
                if str(row[h]).strip():
                    return str(row[h]).strip()
        return ''

    records = []
    errors = []
    for key, sheet in sheet_config.items():
        f = request.files.get(key)
        if not f or not f.filename:
            continue
        try:
            df = pd.read_excel(f)
            if df.empty:
                errors.append(f'{sheet}: archivo vacío')
                continue
            # Mapear columnas de los archivos WMS a la estructura de pool_final
            # (folio queda siempre vacío en la sección WMS). Los archivos nuevos
            # traen 'Número de parte' (np) y 'CEDIS' (almacén); los viejos usaban
            # 'Código' y 'Ubicación'. Se soportan ambos.
            ZONE_BY_CEDIS = {'B1': 'WMS-B1', 'CEDIS 4': 'WMS-CEDIS 4', 'NAVE 5': 'WMS-NAVE 5'}
            for _, row in df.iterrows():
                np_val = _first(row, 'Número de parte', 'Numero de parte', 'No. de parte', 'Código', 'Codigo').upper()
                if not np_val:
                    continue  # descartar filas sin NP (totales/pie de página)
                cedis = _first(row, 'CEDIS', 'Cedis', 'cedis', 'Ubicación', 'Ubicacion')
                sheet_val = ZONE_BY_CEDIS.get(cedis, sheet)
                records.append({
                    'np': np_val,
                    'sheet': sheet_val,
                    'descripcion': _first(row, 'Descripción', 'Descripcion', 'Descripción del material'),
                    'unidad': _first(row, 'U/M', 'UM', 'Unidad'),
                    'empaque': '',
                    'almacen': cedis,
                    'cantidad': '' if row.get('Cantidad') is None else str(row.get('Cantidad')),
                    'contado_por': '',
                    'estado': 'OK',
                    'folio': '',
                    'almacen_pool': '',
                    'varias_ubicaciones': 0,
                    'layout': 1,
                })
        except Exception as e:
            errors.append(f'{sheet}: {str(e)}')

    if not records:
        return jsonify({'success': False, 'msg': 'No se pudo leer ningún archivo válido. ' + ' | '.join(errors) if errors else ''})

    success, msg = load_wms_data(records)
    if not success:
        return jsonify({'success': False, 'msg': msg})
    log_module_action('wms', request.path, f"upload -> {len(records)} registros en wms_data")

    per_sheet = {}
    for r in records:
        per_sheet[r['sheet']] = per_sheet.get(r['sheet'], 0) + 1
    detail = ' | '.join(f'{k}: {v}' for k, v in per_sheet.items())
    if errors:
        msg += f' | Avisos: {"; ".join(errors)}'
    return jsonify({'success': True, 'msg': f'{msg} | Desglose: {detail}'})

@app.route('/saldos')
def saldos_view():
    from core.local_db import init_db
    init_db()
    return render_template('saldos.html')

@app.route('/api/saldos/data')
def api_saldos_data():
    from core.local_db import get_saldos_data
    return jsonify({'data': get_saldos_data()})

@app.route('/api/saldos/update', methods=['POST'])
def api_saldos_update():
    from core.local_db import update_saldos_records
    payload = _module_payload('saldos')
    if payload is None:
        return _module_denied('saldos')
    records = payload.get('records', [])
    if not records:
        return jsonify({'success': False, 'msg': 'No se recibieron registros.'})
    success, msg = update_saldos_records(records)
    log_module_action('saldos', request.path, f"update -> {msg}")
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/saldos/upload', methods=['POST'])
def api_saldos_upload():
    """Recibe el archivo de Saldos (con encabezados o en formato viejo sin encabezados),
    lo parsea a estructura pool_final, vacía saldos_data y la vuelve a llenar. El sheet
    queda fijo en 'Saldos' (o toma 'Pestaña' si la trae)."""
    if request.form.get('module') != 'saldos':
        return _module_denied('saldos')
    import pandas as pd
    from core.local_db import load_saldos_data

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'msg': 'No se recibió ningún archivo.'})

    records = []
    errors = []

    def _sval(row, *headers):
        for h in headers:
            if h in row and row[h] is not None:
                try:
                    if pd.isna(row[h]):
                        continue
                except Exception:
                    pass
                if str(row[h]).strip():
                    return str(row[h]).strip()
        return ''

    try:
        df = pd.read_excel(f)
        if df.empty:
            return jsonify({'success': False, 'msg': 'El archivo está vacío.'})

        if 'NP' in df.columns:
            # FORMATO CON ENCABEZADOS: mapeo por nombre de columna.
            for _, row in df.iterrows():
                np_val = _sval(row, 'NP', 'Clave', 'Clave Producto', 'Código', 'Codigo').upper()
                if not np_val:
                    continue  # descartar filas sin NP (totales/pie de página)
                records.append({
                    'np': np_val,
                    'sheet': _sval(row, 'Pestaña', 'Sheet') or 'Saldos',
                    'descripcion': _sval(row, 'Descripción', 'Descripcion', 'Descripción del material'),
                    'unidad': _sval(row, 'Unidad', 'U/M', 'UM'),
                    'empaque': _sval(row, 'Empaque'),
                    'almacen': _sval(row, 'Almacén', 'Almacen'),
                    'cantidad': _sval(row, 'Cantidad'),
                    'contado_por': _sval(row, 'Contado Por', 'Contado_Por', 'Contado por'),
                    'estado': 'OK',
                    'folio': '',
                    'almacen_pool': '',
                    'varias_ubicaciones': 0,
                    'layout': 1,
                })
        else:
            # FORMATO VIEJO SIN ENCABEZADOS: parseo por posición.
            df = pd.read_excel(f, header=None)
            for _, row in df.iterrows():
                if len(row) < 6:
                    continue
                np_val = str(row[2]) if pd.notna(row[2]) else ''
                np_val = np_val.strip().upper()
                if np_val in ('NAN', 'SALDOS', '', 'NP', 'CLAVE', 'CÓDIGO', 'CODIGO'):
                    continue
                if len(np_val) <= 2:
                    continue
                records.append({
                    'np': np_val,
                    'sheet': 'Saldos',
                    'descripcion': str(row[4]).strip() if pd.notna(row[4]) else '',
                    'unidad': '',
                    'empaque': '',
                    'almacen': '',
                    'cantidad': str(row[5]) if pd.notna(row[5]) else '',
                    'contado_por': '',
                    'estado': 'OK',
                    'folio': '',
                    'almacen_pool': '',
                    'varias_ubicaciones': 0,
                    'layout': 1,
                })
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error leyendo el archivo: {str(e)}'})

    if not records:
        return jsonify({'success': False, 'msg': 'No se encontraron filas válidas en el archivo. ' + (' | '.join(errors) if errors else '')})

    success, msg = load_saldos_data(records)
    if not success:
        return jsonify({'success': False, 'msg': msg})
    log_module_action('saldos', request.path, f"upload -> {len(records)} registros en saldos_data")

    return jsonify({'success': True, 'msg': f'{msg} | Pestaña: Saldos'})

@app.route('/api/pool/copy', methods=['POST'])
def api_pool_copy():
    from core.local_db import copy_to_pool_final
    success, msg = copy_to_pool_final()
    return jsonify({'success': success, 'msg': msg})


@app.route('/api/pool/delete_selected', methods=['POST'])
def api_pool_delete_selected():
    folios = request.json.get('folios', [])
    if not folios:
        return jsonify({'success': False, 'msg': 'No se enviaron folios para eliminar.'})
    
    from core.local_db import delete_selected_pool
    success, msg = delete_selected_pool(folios)
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/pool/restore_backup', methods=['POST'])
def api_pool_restore():
    from core.local_db import restore_pool_from_backup
    success, msg = restore_pool_from_backup()
    return jsonify({'success': success, 'msg': msg})

def _normalize_name(txt):
    import unicodedata
    t = unicodedata.normalize('NFKD', str(txt))
    t = ''.join(ch for ch in t if not unicodedata.combining(ch))
    return t.lower().replace(' ', '').replace('_', '').replace('-', '')

def _infer_query_cols(row):
    """Infiera la columna de clave (SKU) y de ubicación a partir de los nombres reales de columnas."""
    norm_keys = {_normalize_name(k): k for k in row.keys()}
    # Clave: candidatos en orden de prioridad
    key_candidates = ['defaultcode', 'clave', 'clavesolicitada', 'codigo', 'materiaprima', 'sku', 'defaultcodesolicitado']
    key_col = None
    for cand in key_candidates:
        if cand in norm_keys:
            key_col = norm_keys[cand]
            break
    if key_col is None:
        key_col = list(row.keys())[0]
    # Ubicación: candidatos en orden de prioridad
    loc_candidates = ['ubicacioncompleta', 'nombrecompletoubicacion', 'ubicacion', 'completename',
                      'completelocationname', 'location', 'almacen', 'name', 'ubicacionfisica']
    loc_col = None
    for cand in loc_candidates:
        if cand in norm_keys:
            loc_col = norm_keys[cand]
            break
    return key_col, loc_col

def _split_locations(value):
    """Normaliza el valor de ubicación que puede venir como lista/array de Postgres {A, B} o cadena simple.
    Devuelve (primera_ubicacion, varias, ubicaciones_completas) donde varias=True si existe más de una ubicación."""
    if value is None:
        return '', False, []
    if isinstance(value, (list, tuple, set)):
        locations = [str(x).strip() for x in value if str(x).strip()]
    else:
        raw = str(value).strip()
        if raw.startswith('{') and raw.endswith('}'):
            raw = raw[1:-1]
        locations = [part.strip() for part in raw.split(',') if part.strip()]
    if not locations:
        return '', False, []
    return locations[0], len(locations) > 1, locations

def _extract_location_map(rows):
    """Convierte una lista de filas (dicts) en {clave: {'ubicacion': primera, 'varias': bool, 'locations': [...]}}.
    Solo claves con ubicación no vacía."""
    if not rows:
        return {}
    key_col, loc_col = _infer_query_cols(rows[0])
    result = {}
    for r in rows:
        clave = str(r.get(key_col, '')).strip()
        primera, varias, locations = _split_locations(r.get(loc_col, '') if loc_col else None)
        if clave and primera:
            result[clave] = {'ubicacion': primera, 'varias': varias, 'locations': locations}
    return result

def _module_payload(expected):
    """GUARDA DE AISLAMIENTO ENTRE MÓDULOS.
    Cada endpoint de llenado/actualización exige que el body sea JSON con 'module' == expected.
    Así, ningún botón de un módulo puede disparar accidentalmente la escritura de otro (p.ej.
    Saldos nunca puede escribir pool_final; solo el módulo pool puede hacerlo)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict) or data.get('module') != expected:
        return None
    return data

def _module_denied(module):
    return jsonify({
        'success': False,
        'msg': f"Acción rechazada: origen de módulo inválido. Se esperaba 'module': \"{module}\" para evitar tocar tablas de otro módulo."
    }), 400

@app.route('/api/pool/fill_location', methods=['POST'])
def api_pool_fill_location():
    if _module_payload('pool') is None:
        return _module_denied('pool')
    nps = get_pool_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en Pool Final para procesar.'})

    config = load_config()
    db = DBManager(config)

    np_map = {}

    # FASE 1: Query maestro (Query 1)
    updated_q1 = 0
    query = config.get('query', '')
    if query:
        db_results = db.execute_query(query, nps)
        if db_results:
            np_map = _extract_location_map(db_results)
            updated_q1 = len(np_map)

    # FASE 2: Query 3 (Pool Data) — SOBREESCRIBE siempre, incluso si ya existía dato
    updated_q3 = 0
    q3 = config.get('query_pool', '')
    if nps and q3 and q3.strip():
        try:
            q3_results = db.execute_query(q3, nps)
        except Exception:
            q3_results = None
        if q3_results:
            q3_map = _extract_location_map(q3_results)
            for clave, info in q3_map.items():
                np_map[clave] = info
            updated_q3 = len(q3_map)

    updated = update_pool_location(np_map)
    log_module_action('pool', request.path, f"fill_location -> {updated} filas en pool_final ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'filled_q1': updated_q1,
        'filled_q3': updated_q3,
        'still_blank': len([np for np in nps if not (np_map.get(np) or {}).get('ubicacion')])
    })

@app.route('/api/pool/fill_location_q2', methods=['POST'])
def api_pool_fill_location_q2():
    """Ubica los NPs del Pool Final usando SOLO el Query 2 (query_existencias).
    La columna 'Ubicación Completa' viene como array de Postgres {Loc1, Loc2} o lista.
    Se toma SIEMPRE la primera ubicación del array y se activa varias_ubicaciones=True
    cuando el array contiene más de un dato."""
    if _module_payload('pool') is None:
        return _module_denied('pool')
    nps = get_pool_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en Pool Final para procesar.'})

    config = load_config()
    db = DBManager(config)

    q2 = config.get('query_existencias', '')
    if not q2 or not q2.strip():
        return jsonify({'success': False, 'msg': 'El Query 2 (query_existencias) está vacío en la configuración.'})

    try:
        q2_results = db.execute_query(q2, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 2: {str(e)}'})

    if not q2_results:
        return jsonify({'success': False, 'msg': 'El Query 2 no devolvió resultados.'})

    np_map = {}
    q2_map = _extract_location_map(q2_results)
    for clave, info in q2_map.items():
        if clave:
            np_map[clave] = info

    with_varias = len([i for i in np_map.values() if i.get('varias')])
    updated = update_pool_location(np_map)
    log_module_action('pool', request.path, f"fill_location_q2 -> {updated} filas en pool_final ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q2': len(np_map),
        'with_varias': with_varias,
        'still_blank': len([np for np in nps if not (np_map.get(np) or {}).get('ubicacion')])
    })

def _extract_uom_empaque_map(rows):
    """Convierte filas del Query 1 en {clave: {'unidad': u, 'empaque': e}}.
    Solo claves con clave no vacía."""
    if not rows:
        return {}
    norm_keys = {_normalize_name(k): k for k in rows[0].keys()}
    key_candidates = ['clavesolicitada', 'clave', 'defaultcode', 'codigo', 'materiaprima', 'sku']
    key_col = None
    for cand in key_candidates:
        if cand in norm_keys:
            key_col = norm_keys[cand]
            break
    if key_col is None:
        key_col = list(rows[0].keys())[0]
    unidad_col = norm_keys.get('unidad')
    empaque_col = norm_keys.get('empaque')
    result = {}
    for r in rows:
        clave = str(r.get(key_col, '')).strip()
        if not clave:
            continue
        entry = result.setdefault(clave, {'unidad': '', 'empaque': ''})
        if unidad_col and r.get(unidad_col) is not None:
            val = str(r.get(unidad_col)).strip()
            if val and not entry['unidad']:
                entry['unidad'] = val
        if empaque_col and r.get(empaque_col) is not None:
            val = str(r.get(empaque_col)).strip()
            if val and not entry['empaque']:
                entry['empaque'] = val
    return result

def _extract_description_map(rows):
    """Convierte filas del Query 1 en {clave: descripcion}.
    Solo claves con clave no vacía y descripción no vacía."""
    if not rows:
        return {}
    norm_keys = {_normalize_name(k): k for k in rows[0].keys()}
    key_candidates = ['clavesolicitada', 'clave', 'defaultcode', 'codigo', 'materiaprima', 'sku', 'defaultcodesolicitado']
    key_col = None
    for cand in key_candidates:
        if cand in norm_keys:
            key_col = norm_keys[cand]
            break
    if key_col is None:
        key_col = list(rows[0].keys())[0]
    desc_candidates = ['descripcion', 'nombreproducto', 'productname', 'nombre', 'name',
                       'descripcionproducto', 'descripcioncorta', 'descripcioncompleta', 'producttmplid']
    desc_col = None
    for cand in desc_candidates:
        if cand in norm_keys:
            desc_col = norm_keys[cand]
            break
    if desc_col is None:
        return {}
    result = {}
    for r in rows:
        clave = str(r.get(key_col, '')).strip()
        if not clave:
            continue
        desc = r.get(desc_col)
        if desc is None:
            continue
        desc = str(desc).strip()
        if desc:
            result[clave] = desc
    return result

@app.route('/api/wms/fill_uom_empaque', methods=['POST'])
def api_wms_fill_uom_empaque():
    """Completa unidad y empaque de wms_data usando el Query 1 (query maestro) contra Odoo."""
    if _module_payload('wms') is None:
        return _module_denied('wms')
    nps = get_wms_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en wms_data para procesar.'})

    config = load_config()
    db = DBManager(config)

    query = config.get('query', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query 1 (query) está vacío en la configuración.'})

    try:
        db_results = db.execute_query(query, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 1: {str(e)}'})

    if not db_results:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió resultados.'})

    np_map = _extract_uom_empaque_map(db_results)
    if not np_map:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió unidad/empaque para ningún NP.'})

    updated = update_wms_uom_empaque(np_map)
    with_uom = len([i for i in np_map.values() if i.get('unidad')])
    with_emp = len([i for i in np_map.values() if i.get('empaque')])
    log_module_action('wms', request.path, f"fill_uom_empaque -> {updated} filas en wms_data ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q1': len(np_map),
        'with_uom': with_uom,
        'with_empaque': with_emp,
    })

@app.route('/api/wms/fill_locations_q2', methods=['POST'])
def api_wms_fill_locations_q2():
    """Ubica los NPs de wms_data usando SOLO el Query 2 (query_existencias).
    Toma la primera ubicación del array y activa varias_ubicaciones=True cuando hay más de una.
    Llena la columna almacen_pool de wms_data."""
    if _module_payload('wms') is None:
        return _module_denied('wms')
    nps = get_wms_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en wms_data para procesar.'})

    config = load_config()
    db = DBManager(config)

    q2 = config.get('query_existencias', '')
    if not q2 or not q2.strip():
        return jsonify({'success': False, 'msg': 'El Query 2 (query_existencias) está vacío en la configuración.'})

    try:
        q2_results = db.execute_query(q2, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 2: {str(e)}'})

    if not q2_results:
        return jsonify({'success': False, 'msg': 'El Query 2 no devolvió resultados.'})

    np_map = {}
    q2_map = _extract_location_map(q2_results)
    for clave, info in q2_map.items():
        if clave:
            np_map[clave] = info

    with_varias = len([i for i in np_map.values() if i.get('varias')])
    updated = update_wms_location(np_map)
    log_module_action('wms', request.path, f"fill_locations_q2 -> {updated} filas en wms_data ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q2': len(np_map),
        'with_varias': with_varias,
        'still_blank': len([np for np in nps if not (np_map.get(np) or {}).get('ubicacion')])
    })

@app.route('/api/saldos/fill_uom_empaque', methods=['POST'])
def api_saldos_fill_uom_empaque():
    """Completa unidad y empaque de saldos_data usando el Query 1 (query maestro) contra Odoo."""
    if _module_payload('saldos') is None:
        return _module_denied('saldos')
    from core.local_db import get_saldos_nps, update_saldos_uom_empaque
    nps = get_saldos_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en saldos_data para procesar.'})

    config = load_config()
    db = DBManager(config)

    query = config.get('query', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query 1 (query) está vacío en la configuración.'})

    try:
        db_results = db.execute_query(query, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 1: {str(e)}'})

    if not db_results:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió resultados.'})

    np_map = _extract_uom_empaque_map(db_results)
    if not np_map:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió unidad/empaque para ningún NP.'})

    updated = update_saldos_uom_empaque(np_map)
    with_uom = len([i for i in np_map.values() if i.get('unidad')])
    with_emp = len([i for i in np_map.values() if i.get('empaque')])
    log_module_action('saldos', request.path, f"fill_uom_empaque -> {updated} filas en saldos_data ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q1': len(np_map),
        'with_uom': with_uom,
        'with_empaque': with_emp,
    })

@app.route('/api/saldos/fill_locations_q2', methods=['POST'])
def api_saldos_fill_locations_q2():
    """Ubica los NPs de saldos_data usando SOLO el Query 2 (query_existencias).
    Llena la columna almacen_pool de saldos_data e indica varias_ubicaciones."""
    if _module_payload('saldos') is None:
        return _module_denied('saldos')
    from core.local_db import get_saldos_nps, update_saldos_location
    nps = get_saldos_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en saldos_data para procesar.'})

    config = load_config()
    db = DBManager(config)

    q2 = config.get('query_existencias', '')
    if not q2 or not q2.strip():
        return jsonify({'success': False, 'msg': 'El Query 2 (query_existencias) está vacío en la configuración.'})

    try:
        q2_results = db.execute_query(q2, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 2: {str(e)}'})

    if not q2_results:
        return jsonify({'success': False, 'msg': 'El Query 2 no devolvió resultados.'})

    np_map = {}
    q2_map = _extract_location_map(q2_results)
    for clave, info in q2_map.items():
        if clave:
            np_map[clave] = info

    with_varias = len([i for i in np_map.values() if i.get('varias')])
    updated = update_saldos_location(np_map)
    log_module_action('saldos', request.path, f"fill_locations_q2 -> {updated} filas en saldos_data ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q2': len(np_map),
        'with_varias': with_varias,
        'still_blank': len([np for np in nps if not (np_map.get(np) or {}).get('ubicacion')])
    })

@app.route('/etqmang')
def etqmang_view():
    from core.local_db import init_db
    init_db()
    return render_template('etqmang.html')

@app.route('/api/etqmang/data')
def api_etqmang_data():
    from core.local_db import get_etqmang_data
    return jsonify({'data': get_etqmang_data()})

@app.route('/api/etqmang/update', methods=['POST'])
def api_etqmang_update():
    from core.local_db import update_etqmang_records
    payload = _module_payload('etqmang')
    if payload is None:
        return _module_denied('etqmang')
    records = payload.get('records', [])
    if not records:
        return jsonify({'success': False, 'msg': 'No se recibieron registros.'})
    success, msg = update_etqmang_records(records)
    log_module_action('etqmang', request.path, f"update -> {msg}")
    return jsonify({'success': success, 'msg': msg})

def _parse_etqmang_xlsx(file_stream, only_sheet=None):
    """ANÁLISIS PROFUNDO del archivo INVENTARIO ETIQUETAS 2026.xlsx.
    Recorre TODAS las pestañas excepto 'ODOO' (o solo `only_sheet` si se indica) y aplica:
    - sheet = 'LayEtqMag-' + nombre de la pestaña (ejm 'LayEtqMag-ACDELCO').
    - Cantidad = columna 'FISICO' (detectada dinámicamente por encabezado).
    - Almacen = nombre de la pestaña; al detectar una SUBCATEGORÍA pasa a
      'pestaña + subcategoría' (ejm 'ACDELCO MAZDA').
    - Recorrido de diferencia: la tercera columna es la 'Descripción'; se recorre
      mientras esté llena y se revisan las 10 columnas subsecuentes de la fila:
        * 0 celdas llenas  -> se define una SUBCATEGORÍA (afecta al Almacén).
        * >= 3 celdas llenas -> es un PRODUCTO y se guarda.
    Pestañas SIN fila de encabezados (ejm. POTENCO, layout heredado) se infieren:
    NP en col1, Descripción en col2 y FISICO en col8.
    Devuelve (records, sheets, errors)."""
    import pandas as pd

    ETQ_SUBCATEGORY_MIN = 3
    records = []
    errors = []

    xls = pd.ExcelFile(file_stream)
    sheets = [s for s in xls.sheet_names if s.strip().upper() != 'ODOO']
    if only_sheet:
        match = [s for s in sheets if s.strip().upper() == only_sheet.strip().upper()]
        if not match:
            return [], only_sheet, [f'{only_sheet}: pestaña no encontrada en el archivo.']
        sheets = match

    for sheet in sheets:
        try:
            df = pd.read_excel(xls, sheet_name=sheet, header=None)
        except Exception as e:
            errors.append(f'{sheet}: {str(e)}')
            continue
        if df.empty:
            continue

        # Localizar fila de encabezados y columnas de interés
        header_row = None
        for idx, row in df.iterrows():
            vals = [str(v).strip().upper().replace('Í', 'I') for v in row if pd.notna(v)]
            if any('FISICO' in v for v in vals):
                header_row = idx
                break
        if header_row is None:
            for idx, row in df.iterrows():
                vals = [str(v).strip().upper().replace('Í', 'I') for v in row if pd.notna(v)]
                if any('DESCRIPCION' in v for v in vals):
                    header_row = idx
                    break

        if header_row is None:
            # FALLO: pestaña sin fila de encabezados (POTENCO y similares).
            # Inferir layout conocido: col1=NP, col2=Descripción, col8=FISICO.
            candidates = [str(df.iloc[i][1]).strip() for i in range(len(df))
                          if pd.notna(df.iloc[i][1]) and len(str(df.iloc[i][1]).strip()) > 2]
            if len(candidates) < 3:
                errors.append(f'{sheet}: no se encontró fila de encabezados (FISICO/Descripción) ni datos inferibles.')
                continue
            np_col, desc_col, fisico_col = 1, 2, 8
            data_start = 0
            subcategoria = ''
            for idx in range(data_start, len(df)):
                row = df.iloc[idx]
                val_desc = row[desc_col]
                if not pd.notna(val_desc) or str(val_desc).strip() == '':
                    continue
                desc_str = str(val_desc).strip()
                if _normalize_name(desc_str) in ('descripcion', 'noparte', 'no.parte'):
                    continue
                window = row[desc_col + 1: desc_col + 11]
                filled = sum(1 for v in window if pd.notna(v) and str(v).strip() not in ('', 'nan', 'None'))
                if filled == 0:
                    subcategoria = desc_str
                    continue
                if filled < ETQ_SUBCATEGORY_MIN:
                    continue
                np_val = str(df.iloc[idx][np_col]).strip().upper() if pd.notna(df.iloc[idx][np_col]) else ''
                if not np_val or np_val in ('NAN', 'NONE'):
                    continue
                if _normalize_name(np_val) in ('no.parte', 'noparte', 'codigo', 'clave', 'parte'):
                    continue
                if len(np_val) <= 2:
                    continue
                cant_raw = df.iloc[idx][fisico_col]
                cant_str = str(cant_raw).strip().split()[0] if pd.notna(cant_raw) and str(cant_raw).strip() else ''
                almacen = f"{sheet} {subcategoria}".strip() if subcategoria else sheet
                records.append({
                    'np': np_val,
                    'sheet': f'LayEtqMag-{sheet}',
                    'descripcion': desc_str,
                    'unidad': '',
                    'empaque': '',
                    'almacen': almacen,
                    'cantidad': cant_str,
                    'contado_por': '',
                    'estado': 'OK',
                    'folio': '',
                    'almacen_pool': '',
                    'varias_ubicaciones': 0,
                    'layout': 1,
                })
            continue

        hdr = df.iloc[header_row]
        fisico_col = None
        np_col = None
        desc_col = None
        for c_idx, val in hdr.items():
            v = str(val).strip().upper().replace('Í', 'I') if pd.notna(val) else ''
            if fisico_col is None and 'FISICO' in v:
                fisico_col = c_idx
            elif np_col is None and ('PARTE' in v or 'CODIGO' in v or 'CLAVE' in v):
                np_col = c_idx
            elif desc_col is None and 'DESCRIPCION' in v:
                desc_col = c_idx
        if fisico_col is None:
            errors.append(f'{sheet}: columna FISICO no encontrada.')
            continue
        if desc_col is None:
            desc_col = 2  # tercer columna por defecto

        # Detección dinámica del ancho: revisar 10 columnas subsecuentes a la descripción
        win_start = desc_col + 1
        win_end = desc_col + 11

        subcategoria = ''
        for idx in range(header_row + 1, len(df)):
            row = df.iloc[idx]
            val_desc = row[desc_col]
            if not pd.notna(val_desc) or str(val_desc).strip() == '':
                continue
            desc_str = str(val_desc).strip()
            if _normalize_name(desc_str) in ('descripcion', 'noparte', 'no.parte'):
                continue

            window = row[win_start:win_end]
            filled = 0
            for v in window:
                if pd.notna(v) and str(v).strip() not in ('', 'nan', 'None'):
                    filled += 1

            if filled == 0:
                subcategoria = desc_str
                continue
            if filled < ETQ_SUBCATEGORY_MIN:
                continue

            np_val = ''
            if np_col is not None and pd.notna(row[np_col]):
                np_val = str(row[np_col]).strip().upper()
            if not np_val or np_val in ('NAN', 'NONE'):
                continue
            if _normalize_name(np_val) in ('no.parte', 'noparte', 'codigo', 'clave', 'codigo', 'parte'):
                continue
            if len(np_val) <= 2:
                continue

            cantidad = str(row[fisico_col]) if pd.notna(row[fisico_col]) else ''
            almacen = f"{sheet} {subcategoria}".strip() if subcategoria else sheet
            records.append({
                'np': np_val,
                'sheet': f'LayEtqMag-{sheet}',
                'descripcion': desc_str,
                'unidad': '',
                'empaque': '',
                'almacen': almacen,
                'cantidad': cantidad,
                'contado_por': '',
                'estado': 'OK',
                'folio': '',
                'almacen_pool': '',
                'varias_ubicaciones': 0,
                'layout': 1,
            })

    return records, sheets, errors

@app.route('/api/etqmang/upload', methods=['POST'])
def api_etqmang_upload():
    """Recibe el archivo INVENTARIO ETIQUETAS (xlsx multi-pestaña), aplica el análisis
    profundo (subcategorías + 10 columnas) y llena etqmang_data.
    Si el archivo trae encabezados estándar (NP, Pestaña, Descripción, ...) se usa el
    mapeo directo por columna (formato export); si no, el parser profundo de subcategorías.
    Si el form incluye 'sheet' (ejm 'POTENCO') SOLO se procesa esa pestaña y se
    reemplazan únicamente sus registros, conservando las demás."""
    if request.form.get('module') != 'etqmang':
        return _module_denied('etqmang')
    import io
    import pandas as pd
    from core.local_db import load_etqmang_data

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'msg': 'No se recibió ningún archivo.'})

    only_sheet = request.form.get('sheet', '') or None

    def _sval(row, *headers):
        for h in headers:
            if h in row and row[h] is not None:
                try:
                    if pd.isna(row[h]):
                        continue
                except Exception:
                    pass
                if str(row[h]).strip():
                    return str(row[h]).strip()
        return ''

    # Intento 1: formato con encabezados (NP, Pestaña, ...) — reemplazo total.
    if not only_sheet:
        try:
            df = pd.read_excel(f)
            if 'NP' in df.columns and not df.empty:
                records = []
                for _, row in df.iterrows():
                    np_val = _sval(row, 'NP', 'Clave', 'Clave Producto', 'Código', 'Codigo').upper()
                    if not np_val:
                        continue
                    records.append({
                        'np': np_val,
                        'sheet': _sval(row, 'Pestaña', 'Sheet') or 'LayEtqMag',
                        'descripcion': _sval(row, 'Descripción', 'Descripcion', 'Descripción del material'),
                        'unidad': _sval(row, 'Unidad', 'U/M', 'UM'),
                        'empaque': _sval(row, 'Empaque'),
                        'almacen': _sval(row, 'Almacén', 'Almacen'),
                        'cantidad': _sval(row, 'Cantidad'),
                        'contado_por': _sval(row, 'Contado Por', 'Contado_Por', 'Contado por'),
                        'estado': 'OK',
                        'folio': '',
                        'almacen_pool': '',
                        'varias_ubicaciones': 0,
                        'layout': 1,
                    })
                if records:
                    success, msg = load_etqmang_data(records)
                    if not success:
                        return jsonify({'success': False, 'msg': msg})
                    log_module_action('etqmang', request.path, f"upload (headers) -> {len(records)} registros en etqmang_data")
                    return jsonify({'success': True, 'msg': f'{msg} | Formato: export con encabezados.'})
        except Exception:
            pass
        f.seek(0)

    try:
        records, sheets, errors = _parse_etqmang_xlsx(f, only_sheet=only_sheet)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error leyendo el archivo: {str(e)}'})

    if not records:
        return jsonify({'success': False, 'msg': 'No se encontraron filas de producto válidas. ' + (' | '.join(errors) if errors else '')})

    success, msg = load_etqmang_data(records, replace_sheet=only_sheet)
    if not success:
        return jsonify({'success': False, 'msg': msg})
    log_module_action('etqmang', request.path, f"upload -> {len(records)} registros en etqmang_data (pestañas: {', '.join(sheets) if only_sheet else str(len(sheets)) + ' totales, ODOO excluida'})")

    detail = f'Pestañas procesadas: {", ".join(sheets) if only_sheet else str(len(sheets)) + " (ODOO excluida)"}.'
    if errors:
        detail += f' Avisos: {"; ".join(errors[:5])}'
    return jsonify({'success': True, 'msg': f'{msg} | {detail}'})

@app.route('/api/etqmang/fill_uom_empaque', methods=['POST'])
def api_etqmang_fill_uom_empaque():
    """Completa unidad y empaque de etqmang_data usando el Query 1 (query maestro) contra Odoo."""
    if _module_payload('etqmang') is None:
        return _module_denied('etqmang')
    from core.local_db import get_etqmang_nps, update_etqmang_uom_empaque
    nps = get_etqmang_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en etqmang_data para procesar.'})

    config = load_config()
    db = DBManager(config)

    query = config.get('query', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query 1 (query) está vacío en la configuración.'})

    try:
        db_results = db.execute_query(query, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 1: {str(e)}'})

    if not db_results:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió resultados.'})

    np_map = _extract_uom_empaque_map(db_results)
    if not np_map:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió unidad/empaque para ningún NP.'})

    updated = update_etqmang_uom_empaque(np_map)
    with_uom = len([i for i in np_map.values() if i.get('unidad')])
    with_emp = len([i for i in np_map.values() if i.get('empaque')])
    log_module_action('etqmang', request.path, f"fill_uom_empaque -> {updated} filas en etqmang_data ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q1': len(np_map),
        'with_uom': with_uom,
        'with_empaque': with_emp,
    })

@app.route('/api/etqmang/fill_locations_q2', methods=['POST'])
def api_etqmang_fill_locations_q2():
    """Ubica los NPs de etqmang_data usando SOLO el Query 2 (query_existencias).
    Llena la columna almacen_pool de etqmang_data e indica varias_ubicaciones."""
    if _module_payload('etqmang') is None:
        return _module_denied('etqmang')
    from core.local_db import get_etqmang_nps, update_etqmang_location
    nps = get_etqmang_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en etqmang_data para procesar.'})

    config = load_config()
    db = DBManager(config)

    q2 = config.get('query_existencias', '')
    if not q2 or not q2.strip():
        return jsonify({'success': False, 'msg': 'El Query 2 (query_existencias) está vacío en la configuración.'})

    try:
        q2_results = db.execute_query(q2, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 2: {str(e)}'})

    if not q2_results:
        return jsonify({'success': False, 'msg': 'El Query 2 no devolvió resultados.'})

    np_map = {}
    q2_map = _extract_location_map(q2_results)
    for clave, info in q2_map.items():
        if clave:
            np_map[clave] = info

    with_varias = len([i for i in np_map.values() if i.get('varias')])
    updated = update_etqmang_location(np_map)
    log_module_action('etqmang', request.path, f"fill_locations_q2 -> {updated} filas en etqmang_data ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q2': len(np_map),
        'with_varias': with_varias,
        'still_blank': len([np for np in nps if not (np_map.get(np) or {}).get('ubicacion')])
    })

@app.route('/api/pool/empty', methods=['POST'])
def api_pool_empty():
    """Vacía TODA la tabla pool_final.
    La confirmación estricta (teclear 'VACIAR') se hace en el frontend;
    aquí la guarda de módulo evita disparos accidentales de otro módulo."""
    if _module_payload('pool') is None:
        return _module_denied('pool')
    removed = empty_pool_final()
    log_module_action('pool', request.path, f"empty_pool_final -> {removed} registros eliminados de pool_final (snapshot guardado en backup)")
    return jsonify({'success': True, 'removed': removed})


@app.route('/api/pool/export')
def api_pool_export():
    import pandas as pd
    import io
    from flask import send_file

    try:
        conn = connect()
        query = "SELECT folio as Folio, np as NP, sheet as Pestana, descripcion as Descripcion, unidad as Unidad, empaque as Empaque, almacen as Almacen, almacen_pool as Ubicacion, cantidad as Cantidad, contado_por as Contado_Por FROM pool_final ORDER BY folio DESC"
        df = pd.read_sql_query(query, conn)
        conn.close()
        
        # Guardar a buffer en memoria
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Pool_Final')
        
        output.seek(0)
        return send_file(output, download_name="Historial_Pool_Final.xlsx", as_attachment=True)
    except Exception as e:
        return str(e), 500

@app.route('/api/pool/export_csv')
def api_pool_export_csv():
    import pandas as pd
    import io
    from flask import send_file

    try:
        conn = connect()
        query = ("SELECT folio as \"Folio Físico\", np as \"NP\", sheet as \"Pestaña\", "
                 "descripcion as \"Descripción\", unidad as \"Unidad\", empaque as \"Empaque\", "
                 "almacen as \"Almacén\", almacen_pool as \"Ubicación\", varias_ubicaciones as \"Varias\", "
                 "layout as \"Layout\", cantidad as \"Cantidad\", contado_por as \"Contado Por\", "
                 "auditoria as \"Auditoría\", estado as \"Estado\" "
                 "FROM pool_final ORDER BY CAST(folio AS INTEGER) DESC")
        df = pd.read_sql_query(query, conn)
        conn.close()

        output = io.BytesIO()
        df.to_csv(output, index=False, encoding='utf-8-sig')
        output.seek(0)
        return send_file(output, mimetype='text/csv', download_name="CVS Pool Data.csv", as_attachment=True)
    except Exception as e:
        return str(e), 500

@app.route('/api/pool/data')
def api_pool_data():
    from core.local_db import get_pool_final
    return jsonify({'data': get_pool_final()})

@app.route('/api/pool/matrix')
def api_pool_matrix():
    """Construye la matriz dinámica de ubicaciones.
    1. Toma SOLO los NPs de pool_final con varias_ubicaciones=1.
    2. Corren el Query 2 (query_existencias) contra Odoo para esos NPs.
    3. Del array de ubicaciones de cada NP, marca con 'X' las celdas presentes."""
    from core.local_db import get_pool_nps_varias

    nps_varias = get_pool_nps_varias()
    if not nps_varias:
        return jsonify({'columns': [], 'rows': [], 'source': 'Varias=True',
                        'nps_used': 0, 'msg': 'Ningún NP tiene varias_ubicaciones=1.'})

    config = load_config()
    db = DBManager(config)
    q2 = config.get('query_existencias', '')

    # Mapa np -> lista de ubicaciones (todas, no solo la primera)
    np_locations = {}

    if q2 and q2.strip():
        try:
            q2_results = db.execute_query(q2, nps_varias)
        except Exception:
            q2_results = None
        if q2_results:
            q2_map = _extract_location_map(q2_results)
            for clave, info in q2_map.items():
                if clave:
                    np_locations[clave] = info.get('locations') or [info.get('ubicacion')]

    if not np_locations:
        return jsonify({'columns': [], 'rows': [], 'source': 'Varias=True',
                        'nps_used': len(nps_varias),
                        'msg': f'Query 2 no devolvió ubicaciones para {len(nps_varias)} NPs.'})

    # Filtrar solo los que efectivamente tienen 2+ ubicaciones (matriz)
    rows = []
    for np, locations in np_locations.items():
        clean_locs = [l for l in locations if l]
        if len(clean_locs) > 1:
            rows.append({'np': np, 'locations': sorted(set(clean_locs))})
    rows.sort(key=lambda r: r['np'])

    # Columnas dinámicas: todas las ubicaciones distintas encontradas
    all_locs = set()
    for r in rows:
        all_locs.update(r['locations'])
    if rows:
        # Ordenar de manera lógica para que agrupe ubicaciones principales
        columns = sorted(all_locs)
    else:
        columns = []

    return jsonify({'columns': columns, 'rows': rows, 'source': 'Varias=True (Query 2)',
                    'nps_used': len(nps_varias)})

@app.route('/api/pool/update', methods=['POST'])
def api_pool_update():
    from core.local_db import update_pool_records
    payload = _module_payload('pool')
    if payload is None:
        return _module_denied('pool')
    records = payload.get('records', [])
    if not records:
        return jsonify({'success': False, 'msg': 'No se recibieron registros.'})
    success, msg = update_pool_records(records)
    log_module_action('pool', request.path, f"update -> {msg}")
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/pool/update_descriptions', methods=['POST'])
def api_pool_update_descriptions():
    """Actualiza la descripción de TODOS los NPs del Pool Final usando el Query 1 (query maestro) contra Odoo."""
    if _module_payload('pool') is None:
        return _module_denied('pool')

    nps = get_pool_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en Pool Final para procesar.'})

    config = load_config()
    db = DBManager(config)

    query = config.get('query', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query 1 (query) está vacío en la configuración.'})

    try:
        db_results = db.execute_query(query, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 1: {str(e)}'})

    if not db_results:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió resultados.'})

    np_map = _extract_description_map(db_results)
    if not np_map:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió descripciones para ningún NP.'})

    updated = update_pool_descriptions(np_map)
    log_module_action('pool', request.path, f"update_descriptions -> {updated} filas en pool_final ({len(nps)} NPs procesados)")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q1': len(np_map),
        'with_desc': len([d for d in np_map.values() if d])
    })

MODULE_TRANSFER_TABLE = {'wms': 'wms_data', 'saldos': 'saldos_data', 'etqmang': 'etqmang_data', 'epts': 'epts_data'}

# ============ MÓDULO EPTS ============

@app.route('/epts')
def epts_view():
    from core.local_db import init_db
    init_db()
    return render_template('epts.html')

@app.route('/api/epts/data')
def api_epts_data():
    from core.local_db import get_epts_data
    return jsonify({'data': get_epts_data()})

@app.route('/api/epts/comparativo')
def api_epts_comparativo_data():
    from core.local_db import get_epts_comparativo
    return jsonify({'data': get_epts_comparativo()})

@app.route('/api/epts/update', methods=['POST'])
def api_epts_update():
    from core.local_db import update_epts_records
    payload = _module_payload('epts')
    if payload is None:
        return _module_denied('epts')
    records = payload.get('records', [])
    if not records:
        return jsonify({'success': False, 'msg': 'No se recibieron registros.'})
    success, msg = update_epts_records(records)
    log_module_action('epts', request.path, f"update -> {msg}")
    return jsonify({'success': success, 'msg': msg})

# ============ EXPORTAR EXCEL Y ELIMINAR SELECCIONADOS (WMS/SALDOS/ETQMANG/EPTS) ============

_MODULE_EXPORT_CFG = {
    'wms':     {'table': 'wms_data',     'label': 'Cargas_WMS.xlsx',            'extra_sels': ''},
    'saldos':  {'table': 'saldos_data',  'label': 'Cargas_Saldos.xlsx',         'extra_sels': ''},
    'etqmang': {'table': 'etqmang_data', 'label': 'Etiquetas_y_Mangas.xlsx',    'extra_sels': ''},
}

@app.route('/api/wms/export')
def api_wms_export():
    return _export_module_excel('wms')

@app.route('/api/saldos/export')
def api_saldos_export():
    return _export_module_excel('saldos')

@app.route('/api/etqmang/export')
def api_etqmang_export():
    return _export_module_excel('etqmang')

@app.route('/api/epts/export')
def api_epts_export():
    return _export_module_excel('epts')

@app.route('/api/epts/generar_ajuste_carga', methods=['POST'])
def api_epts_generar_ajuste_carga():
    """Genera 'ajuste-ept-carga.csv' en la carpeta archivocargaetp con la misma estructura
    del archivo de carga de referencia. Toma las filas del bloque EPT del modelo Análisis
    Final (cargadas del Archivo de Inventario MP -> pestaña EPTS) y calcula la Acción con las
    mismas reglas de la UI. Solo incluye Acción en (AUMENTO, SIN CAMBIO, DISMINUYO); las filas
    BAJA quedan fuera (se reportan). Para EPT, line_ids/product_qty es SIEMPRE el QTY Conteo
    (la regla de AJUSTE aplica solo para almacenes que no son EPT). Elimina el archivo anterior
    y crea el nuevo."""
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    import csv as _csv
    from core.local_db import get_analisis_final

    ept_rows = [r for r in get_analisis_final() if r.get('bloque') == 'EPT']
    incluida = []
    bajas = 0
    for r in ept_rows:
        odo = float(r.get('qty_odoo') or 0)
        con = float(r.get('qty_conteo') or 0)
        accion = _epts_accion(odo, con)
        if accion == 'BAJA':
            bajas += 1
            continue
        incluida.append({
            'np': r.get('np') or '',
            'unidad': r.get('unidad') or '',
            'lote': r.get('lote') or '',
            'qty': con,
        })
    incluida.sort(key=lambda x: (str(x['np']), str(x['lote'])))

    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'archivocargaetp')
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, 'ajuste-ept-carga.csv')

    header = [
        'Inventory of', 'Inventory Reference', 'location_id', 'Inventories / Location',
        'Inventories / Product', 'Inventories / Product Unit of Measure',
        'line_ids/prod_lot_id', 'line_ids/product_qty',
    ]

    if os.path.exists(path):
        os.remove(path)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = _csv.writer(f)
        w.writerow(header)
        for i, r in enumerate(incluida):
            w.writerow([
                'none' if i == 0 else '',
                'INV-ANUAL-MP-EPTs-2026' if i == 0 else '',
                'Physical Locations/AMP/Stock/EPTs' if i == 0 else '',
                'Physical Locations/AMP/Stock/EPTs',
                r['np'], r['unidad'], r['lote'], str(r['qty']),
            ])

    total = len(ept_rows)
    log_module_action('analisis_final', request.path,
                      f"generar_ajuste_carga -> {len(incluida)} fila(s) al archivo, {bajas} excluidas (BAJA), total {total}")
    return jsonify({
        'ok': True,
        'msg': f"Archivo 'ajuste-ept-carga.csv' generado con {len(incluida)} fila(s).",
        'filas': len(incluida), 'bajas': bajas, 'total': total, 'ruta': os.path.basename(path),
    })

# ============ ARCHIVOS DE CARGA PROP. CLIENTE (Análisis Final) ============

def _fmt_propcli_qty(n):
    """Formato de cantidades de los layouts Prop. Cliente: 2 decimales planos (0.00, -380.00)."""
    try:
        return f"{float(n):.2f}"
    except (TypeError, ValueError):
        return "0.00"

def _propcli_unidad(unidad):
    """Mapea la UDM del modelo a la nomenclatura de los layouts Prop. Cliente."""
    u = str(unidad or '').strip()
    if u.lower() == 'unit(s)':
        return 'Unidades'
    if u.lower() == 'liter(s)':
        return 'Litro(s)'
    return u

def _af_agregado_bloque(bloque):
    """Agrega el modelo Análisis Final por NP dentro de un bloque: suma QTY Odoo y QTY Conteo
    por NP (B&A tiene varios lotes por NP) y calcula Acción/Ajuste sobre los totales."""
    from core.local_db import get_analisis_final
    agg = {}
    for r in get_analisis_final():
        if r.get('bloque') != bloque:
            continue
        npv = str(r.get('np') or '')
        if npv not in agg:
            agg[npv] = {'odoo': 0.0, 'conteo': 0.0, 'unidad': r.get('unidad') or ''}
        agg[npv]['odoo'] += float(r.get('qty_odoo') or 0)
        agg[npv]['conteo'] += float(r.get('qty_conteo') or 0)
    out = {}
    for npv, v in agg.items():
        accion = _epts_accion(v['odoo'], v['conteo'])
        out[npv] = {'accio': accion, 'ajuste': _epts_ajuste(accion, v['odoo'] - v['conteo']),
                    'odoo': v['odoo'], 'conteo': v['conteo'], 'unidad': v['unidad']}
    return out

def _audit_files(bloque, archivos):
    """Auditoría: relee los CSV generados (carga/baja) y los compara contra el modelo
    Análisis Final del bloque dado (agregado por NP). 'archivos' es una lista de dicts:
    {'key': 'carga'|'baja', 'path': ruta_absoluta, 'col': 'line_ids/stock_update_qty'|'line_ids/product_qty',
     'fn': callable(m) que devuelve el valor esperado (ajuste / qty_odoo)}.
    Compara contra el valor del modelo redondeado a 2 decimales (formato del layout)."""
    import csv as _csv
    base = os.path.dirname(os.path.abspath(__file__))
    model = _af_agregado_bloque(bloque)

    def parse_qty(s):
        try:
            return float(str(s or '').replace(',', ''))
        except (TypeError, ValueError):
            return None

    def check(path, col, fn):
        res = {'generado': False, 'filas': 0, 'discrepancias': 0, 'items': []}
        if not os.path.exists(path):
            return res
        disc = []
        filas = 0
        with open(path, newline='', encoding='utf-8') as f:
            for r in _csv.DictReader(f):
                np_v = (r.get('Inventories / Product') or '').strip()
                m = model.get(np_v)
                if m is None:
                    continue
                filas += 1
                expected = fn(m)
                if expected is None:
                    continue
                got = parse_qty(r.get(col))
                expected_2dp = round(float(expected), 2)
                if got is None or abs(got - expected_2dp) > 1e-9:
                    disc.append({'np': np_v, 'archivo': got, 'modelo': expected})
        res.update({'generado': True, 'filas': filas, 'discrepancias': len(disc), 'items': disc})
        return res

    out = {}
    for a in archivos:
        out[a['key']] = check(a['path'], a['col'], a['fn'])
    return out

def _audit_propcli_files():
    base = os.path.dirname(os.path.abspath(__file__))
    return _audit_files('Prop. Cliente', [
        {'key': 'carga', 'path': os.path.join(base, 'archivocargapropcliente', 'ajuste-propcli-carga.csv'),
         'col': 'line_ids/stock_update_qty', 'fn': lambda m: m['ajuste']},
        {'key': 'baja', 'path': os.path.join(base, 'archivobajaprocliente', 'ajuste-propcli-baja.csv'),
         'col': 'line_ids/product_qty', 'fn': lambda m: m['odoo']},
    ])

def _audit_ba_files():
    base = os.path.dirname(os.path.abspath(__file__))
    return _audit_files('B&A', [
        {'key': 'carga', 'path': os.path.join(base, 'archivocargaba', 'ajuste-ba-carga.csv'),
         'col': 'line_ids/stock_update_qty', 'fn': lambda m: m['ajuste']},
        {'key': 'baja', 'path': os.path.join(base, 'archivobajaba', 'ajuste-ba-baja.csv'),
         'col': 'line_ids/product_qty', 'fn': lambda m: m['odoo']},
    ])

def _audit_insumos_files():
    base = os.path.dirname(os.path.abspath(__file__))
    return _audit_files('Insumos', [
        {'key': 'carga', 'path': os.path.join(base, 'archivocargaba', 'ajuste-insumos-carga.csv'),
         'col': 'line_ids/stock_update_qty', 'fn': lambda m: m['ajuste']},
        {'key': 'baja', 'path': os.path.join(base, 'archivobajaba', 'ajuste-insumos-baja.csv'),
         'col': 'line_ids/product_qty', 'fn': lambda m: m['odoo']},
    ])

@app.route('/api/analisis_final/generar_propcli', methods=['POST'])
def api_analisis_final_generar_propcli():
    """Genera los archivos de carga Prop. Cliente según el tipo:
    - tipo 'carga': Acción IN (AUMENTO, DISMINUYO) -> line_ids/stock_update_qty = AJUSTE
      (Inventory Reference INV-ANUAL-MP-PROPCLI-UPDATE-2026, estructura ajuste/ept update).
    - tipo 'baja' : Acción BAJA -> line_ids/product_qty = QTY Odoo
      (Inventory Reference INV-ANUAL-MP-PROPCLI-DOWN-2026, estructura eliminar base cero).
    Crea el archivo en la carpeta de su layout (borrando el anterior) y devuelve la auditoría."""
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    import csv as _csv
    from core.local_db import get_analisis_final

    payload = request.get_json(silent=True) or {}
    tipo = str(payload.get('tipo', '')).strip()
    specs = {
        'carga': {
            'folder': 'archivocargapropcliente', 'file': 'ajuste-propcli-carga.csv',
            'ref': 'INV-ANUAL-MP-PROPCLI-UPDATE-2026',
            'header': ['Inventory of', 'Inventory Reference', 'Iniciar sin Existencias', 'location_id',
                       'Inventories / Location', 'Inventories / Product', 'line_ids/prod_lot_id',
                       'Inventories / Product Unit of Measure', 'line_ids/stock_update_qty'],
            'acciones': ('AUMENTO', 'DISMINUYO'),
        },
        'baja': {
            'folder': 'archivobajaprocliente', 'file': 'ajuste-propcli-baja.csv',
            'ref': 'INV-ANUAL-MP-PROPCLI-DOWN-2026',
            'header': ['Inventory of', 'Inventory Reference', 'Iniciar sin Existencias', 'location_id',
                       'Inventories / Location', 'Inventories / Product',
                       'Inventories / Product Unit of Measure', 'line_ids/product_qty'],
            'acciones': ('BAJA',),
        },
    }
    spec = specs.get(tipo)
    if not spec:
        return jsonify({'ok': False, 'msg': "tipo inválido (debe ser 'carga' o 'baja')."})

    rows = [r for r in get_analisis_final() if r.get('bloque') == 'Prop. Cliente']
    out = []
    total = len(rows)
    for r in rows:
        odo = float(r.get('qty_odoo') or 0)
        con = float(r.get('qty_conteo') or 0)
        accion = _epts_accion(odo, con)
        if accion not in spec['acciones']:
            continue
        if accion == 'BAJA':
            qty = odo
        else:
            ajuste = _epts_ajuste(accion, odo - con)
            qty = ajuste if ajuste is not None else 0.0
        out.append({'np': r.get('np') or '', 'unidad': _propcli_unidad(r.get('unidad')), 'qty': qty})
    out.sort(key=lambda x: x['np'])

    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), spec['folder'])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, spec['file'])
    if os.path.exists(path):
        os.remove(path)

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = _csv.writer(f)
        w.writerow(spec['header'])
        for i, r in enumerate(out):
            fila = [
                'none' if i == 0 else '',
                spec['ref'] if i == 0 else '',
                '1' if i == 0 else '',
                'Physical Locations/AMP/Stock/Prop. Cte.' if i == 0 else '',
                'Physical Locations/AMP/Stock/Prop. Cte.',
                r['np'],
            ]
            if tipo == 'carga':
                fila += ['', r['unidad'], _fmt_propcli_qty(r['qty'])]
            else:
                fila += [r['unidad'], _fmt_propcli_qty(r['qty'])]
            w.writerow(fila)

    audit = _audit_propcli_files()
    log_module_action('analisis_final', request.path,
                      f"generar_propcli({tipo}) -> {len(out)} fila(s): {spec['file']}")
    return jsonify({
        'ok': True,
        'msg': f"Archivo '{spec['file']}' generado con {len(out)} fila(s).",
        'filas': len(out), 'total': total, 'ruta': spec['file'], 'tipo': tipo, 'audit': audit,
    })

@app.route('/api/analisis_final/generar_ba', methods=['POST'])
def api_analisis_final_generar_ba():
    """Genera los archivos de carga Básicos y Aditivos (bloque 'B&A') según el tipo:
    - tipo 'carga': Acción IN (AUMENTO, DISMINUYO) -> line_ids/stock_update_qty = AJUSTE
      (Inventory Reference INV-2025 MP PROPC.-ACTUALIZACION, estructura update 9 cols con lote).
    - tipo 'baja' : Acción BAJA -> line_ids/product_qty = QTY Odoo
      (Inventory Reference INV-ANUAL-MP-BA-DOWN-2026, estructura eliminar base cero 9 cols con lote).
    Crea el archivo en la carpeta de su layout (borrando el anterior) y devuelve la auditoría."""
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    import csv as _csv
    from core.local_db import get_analisis_final

    payload = request.get_json(silent=True) or {}
    tipo = str(payload.get('tipo', '')).strip()
    specs = {
        'carga': {
            'folder': 'archivocargaba', 'file': 'ajuste-ba-carga.csv',
            'ref': 'INV-2025 MP PROPC.-ACTUALIZACION',
            'header': ['Inventory of', 'Inventory Reference', 'Iniciar sin Existencias', 'location_id',
                       'Inventories / Location', 'Inventories / Product', 'line_ids/prod_lot_id',
                       'Inventories / Product Unit of Measure', 'line_ids/stock_update_qty'],
            'acciones': ('AUMENTO', 'DISMINUYO'),
        },
        'baja': {
            'folder': 'archivobajaba', 'file': 'ajuste-ba-baja.csv',
            'ref': 'INV-ANUAL-MP-BA-DOWN-2026',
            'header': ['Inventory of', 'Inventory Reference', 'Iniciar sin Existencias', 'location_id',
                       'Inventories / Location', 'Inventories / Product', 'line_ids/prod_lot_id',
                       'Inventories / Product Unit of Measure', 'line_ids/product_qty'],
            'acciones': ('BAJA',),
        },
    }
    spec = specs.get(tipo)
    if not spec:
        return jsonify({'ok': False, 'msg': "tipo inválido (debe ser 'carga' o 'baja')."})

    rows = [r for r in get_analisis_final() if r.get('bloque') == 'B&A']
    out = []
    total = len(rows)
    for npv, m in _af_agregado_bloque('B&A').items():
        if m['accio'] not in spec['acciones']:
            continue
        if m['accio'] == 'BAJA':
            qty = m['odoo']
        else:
            qty = m['ajuste'] if m['ajuste'] is not None else 0.0
        out.append({'np': npv, 'unidad': _propcli_unidad(m['unidad']), 'qty': qty})
    out.sort(key=lambda x: x['np'])

    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), spec['folder'])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, spec['file'])
    if os.path.exists(path):
        os.remove(path)

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = _csv.writer(f)
        w.writerow(spec['header'])
        for i, r in enumerate(out):
            fila = [
                'none' if i == 0 else '',
                spec['ref'] if i == 0 else '',
                '1' if i == 0 else '',
                'Physical Locations/AMP/Stock/B&A' if i == 0 else '',
                'Physical Locations/AMP/Stock/B&A',
                r['np'],
                '',
                r['unidad'],
                _fmt_propcli_qty(r['qty']),
            ]
            w.writerow(fila)

    audit = _audit_ba_files()
    log_module_action('analisis_final', request.path,
                      f"generar_ba({tipo}) -> {len(out)} fila(s): {spec['file']}")
    return jsonify({
        'ok': True,
        'msg': f"Archivo '{spec['file']}' generado con {len(out)} fila(s).",
        'filas': len(out), 'total': total, 'ruta': spec['file'], 'tipo': tipo, 'audit': audit,
    })

@app.route('/api/analisis_final/generar_insumos', methods=['POST'])
def api_analisis_final_generar_insumos():
    """Genera los archivos de carga Insumos (bloque 'Insumos') según el tipo:
    - tipo 'carga': Acción IN (AUMENTO, DISMINUYO) -> line_ids/stock_update_qty = AJUSTE
      (Inventory Reference INV-ANUAL-MP-insumos-UPDATE-2026, estructura update 9 cols con lote).
    - tipo 'baja' : Acción BAJA -> line_ids/product_qty = QTY Odoo
      (Inventory Reference INV-ANUAL-MP-insumos-DOWN-2026, estructura eliminar base cero 9 cols con lote).
    Crea el archivo en la carpeta de su layout (borrando el anterior) y devuelve la auditoría."""
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    import csv as _csv
    from core.local_db import get_analisis_final

    payload = request.get_json(silent=True) or {}
    tipo = str(payload.get('tipo', '')).strip()
    specs = {
        'carga': {
            'folder': 'archivocargaba', 'file': 'ajuste-insumos-carga.csv',
            'ref': 'INV-ANUAL-MP-insumos-UPDATE-2026',
            'header': ['Inventory of', 'Inventory Reference', 'Iniciar sin Existencias', 'location_id',
                       'Inventories / Location', 'Inventories / Product', 'line_ids/prod_lot_id',
                       'Inventories / Product Unit of Measure', 'line_ids/stock_update_qty'],
            'acciones': ('AUMENTO', 'DISMINUYO'),
        },
        'baja': {
            'folder': 'archivobajaba', 'file': 'ajuste-insumos-baja.csv',
            'ref': 'INV-ANUAL-MP-insumos-DOWN-2026',
            'header': ['Inventory of', 'Inventory Reference', 'Iniciar sin Existencias', 'location_id',
                       'Inventories / Location', 'Inventories / Product', 'line_ids/prod_lot_id',
                       'Inventories / Product Unit of Measure', 'line_ids/product_qty'],
            'acciones': ('BAJA',),
        },
    }
    spec = specs.get(tipo)
    if not spec:
        return jsonify({'ok': False, 'msg': "tipo inválido (debe ser 'carga' o 'baja')."})

    rows = [r for r in get_analisis_final() if r.get('bloque') == 'Insumos']
    total = len(rows)
    out = []
    for r in rows:
        odo = float(r.get('qty_odoo') or 0)
        con = float(r.get('qty_conteo') or 0)
        accion = _epts_accion(odo, con)
        if accion not in spec['acciones']:
            continue
        if accion == 'BAJA':
            qty = odo
        else:
            ajuste = _epts_ajuste(accion, odo - con)
            qty = ajuste if ajuste is not None else 0.0
        out.append({'np': r.get('np') or '', 'unidad': _propcli_unidad(r.get('unidad')), 'qty': qty})
    out.sort(key=lambda x: x['np'])

    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), spec['folder'])
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, spec['file'])
    if os.path.exists(path):
        os.remove(path)

    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = _csv.writer(f)
        w.writerow(spec['header'])
        for i, r in enumerate(out):
            fila = [
                'none' if i == 0 else '',
                spec['ref'] if i == 0 else '',
                '1' if i == 0 else '',
                'Physical Locations/AMP/Stock/Insumos' if i == 0 else '',
                'Physical Locations/AMP/Stock/Insumos',
                r['np'],
                '',
                r['unidad'],
                _fmt_propcli_qty(r['qty']),
            ]
            w.writerow(fila)

    audit = _audit_insumos_files()
    log_module_action('analisis_final', request.path,
                      f"generar_insumos({tipo}) -> {len(out)} fila(s): {spec['file']}")
    return jsonify({
        'ok': True,
        'msg': f"Archivo '{spec['file']}' generado con {len(out)} fila(s).",
        'filas': len(out), 'total': total, 'ruta': spec['file'], 'tipo': tipo, 'audit': audit,
    })

@app.route('/api/epts/comparativo/export')
def api_epts_comparativo_export():
    """Exporta el Comparativo EPTS (Query EPTS vs Datos EPTS) a Excel conservando el
    estilo de color de la UI: badges de Procedencia/Acción/Varias/Layout y el color de
    DIFF/Ajuste según su signo."""
    import io
    from flask import send_file
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from core.local_db import get_epts_comparativo

    rows = get_epts_comparativo()
    if not rows:
        rows = []

    headers = [
        'Procedencia', 'NP', 'Lote', 'Descripción', 'Unidad', 'Empaque', 'Almacén',
        'Ubicación', 'Varias', 'Layout', 'QTY Odoo', 'QTY Conteo', 'DIFF', 'Acción', 'Ajuste',
    ]
    keys = [
        'procedencia', 'np', 'lote', 'descripcion', 'unidad', 'empaque', 'almacen',
        'almacen_pool', 'varias_ubicaciones', 'layout', 'qty_odoo', 'qty_conteo', 'diff', 'accion', 'ajuste',
    ]

    _PROC_STYLE = {
        'AMBOS':      (PatternFill('solid', start_color='198754'), 'FFFFFF'),  # verde / blanco
        'SOLO ODOO':  (PatternFill('solid', start_color='31D2F2'), '212529'),  # azul info / oscuro
        'SOLO CONTEO':(PatternFill('solid', start_color='FFC107'), '212529'),  # ámbar / oscuro
    }
    _ACCION_STYLE = {
        'BAJA':      (PatternFill('solid', start_color='DC3545'), 'FFFFFF'),  # rojo / blanco
        'DISMINUYO': (PatternFill('solid', start_color='FFC107'), '212529'),  # ámbar / oscuro
        'AUMENTO':   (PatternFill('solid', start_color='198754'), 'FFFFFF'),  # verde / blanco
        'SIN CAMBIO':(PatternFill('solid', start_color='6C757D'), 'FFFFFF'),  # gris / blanco
    }
    _YES_FILL = PatternFill('solid', start_color='FFC107')
    _YES_FONT = Font(bold=True, color='212529')
    _YES_FILL_G = PatternFill('solid', start_color='198754')
    _YES_FONT_G = Font(bold=True, color='FFFFFF')
    _NO_FILL = PatternFill('solid', start_color='6C757D')
    _NO_FONT = Font(color='FFFFFF')

    wb = Workbook()
    ws = wb.active
    ws.title = 'Comparativo_EPTS'

    header_fill = PatternFill('solid', start_color='454D55')
    header_font = Font(bold=True, color='FFFFFF')

    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=ci, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    num_fmt = '#,##0.####'
    for ri, r in enumerate(rows, start=2):
        proc = str(r.get('procedencia', '') or '')
        accion = str(r.get('accion', '') or '')
        for ci, k in enumerate(keys, start=1):
            val = r.get(k)
            cell = ws.cell(row=ri, column=ci)
            if k in ('varias_ubicaciones', 'layout'):
                on = int(val or 0) == 1
                label = 'SÍ' if on else 'NO'
                if k == 'varias_ubicaciones':
                    cell.value = label
                    cell.fill = _YES_FILL if on else _NO_FILL
                    cell.font = _YES_FONT if on else _NO_FONT
                else:
                    cell.value = label
                    cell.fill = _YES_FILL_G if on else _NO_FILL
                    cell.font = _YES_FONT_G if on else _NO_FONT
                cell.alignment = Alignment(horizontal='center')
                continue
            if k in ('qty_odoo', 'qty_conteo', 'diff', 'ajuste'):
                try:
                    n = float(val or 0)
                except (TypeError, ValueError):
                    n = 0.0
                cell.value = n
                cell.number_format = num_fmt
                if k == 'diff':
                    cell.font = Font(bold=True, color='DC3545') if n != 0 else Font(color='6C757D')
                elif k == 'ajuste':
                    cell.font = Font(bold=True, color='DC3545') if n < 0 else (Font(bold=True, color='198754') if n > 0 else Font(color='6C757D'))
                cell.alignment = Alignment(horizontal='right')
                continue
            if k == 'procedencia':
                cell.value = proc
                st = _PROC_STYLE.get(proc)
                if st:
                    cell.fill, fcolor = st
                    cell.font = Font(bold=True, color=fcolor)
                cell.alignment = Alignment(horizontal='center')
                continue
            if k == 'accion':
                cell.value = accion
                st = _ACCION_STYLE.get(accion)
                if st:
                    cell.fill, fcolor = st
                    cell.font = Font(bold=True, color=fcolor)
                cell.alignment = Alignment(horizontal='center')
                continue
            cell.value = '' if val is None else val

    thin = Side(style='thin', color='DEE2E6')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for row_cells in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=len(headers)):
        for cell in row_cells:
            cell.border = border

    widths = [13, 10, 10, 40, 9, 10, 12, 12, 8, 8, 11, 12, 11, 12, 11]
    for ci, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = w

    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(headers)).column_letter}{max(ws.max_row, 1)}"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    log_module_action('epts', request.path, f"export comparativo -> {len(rows)} fila(s) a Excel")
    return send_file(output, download_name="Comparativo_EPTS.xlsx", as_attachment=True)

def _export_module_excel(module):
    """Exporta la tabla del módulo a Excel dinámicamente según sus columnas.
    EPTS incluye 'Lote' y 'Unidad Archivo' (columnas propias del modelo)."""
    import pandas as pd
    import io
    from flask import send_file

    if module == 'epts':
        cols = ("np as \"NP\", lote as \"Lote\", sheet as \"Pestaña\", "
                "descripcion as \"Descripción\", unidad as \"Unidad\", empaque as \"Empaque\", "
                "almacen as \"Almacén\", almacen_pool as \"Ubicación\", "
                "cantidad as \"Cantidad\", unidad_file as \"Unidad Archivo\", "
                "contado_por as \"Contado Por\", auditoria as \"Auditoría\"")
        fname = "EPTS.xlsx"
        sheet = "EPTS"
    else:
        cfg = _MODULE_EXPORT_CFG[module]
        cols = ("np as \"NP\", sheet as \"Pestaña\", descripcion as \"Descripción\", "
                "unidad as \"Unidad\", empaque as \"Empaque\", almacen as \"Almacén\", "
                "almacen_pool as \"Ubicación\", cantidad as \"Cantidad\", "
                "contado_por as \"Contado Por\", auditoria as \"Auditoría\"")
        fname = cfg['label']
        sheet = module.upper()
    try:
        conn = connect()
        query = f"SELECT {cols} FROM {_MODULE_EXPORT_CFG[module]['table'] if module != 'epts' else 'epts_data'} ORDER BY CAST(np AS TEXT) ASC"
        df = pd.read_sql_query(query, conn)
        conn.close()
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name=sheet)
        output.seek(0)
        return send_file(output, download_name=fname, as_attachment=True)
    except Exception as e:
        return str(e), 500

_MODULE_DELETE_CFG = {
    'wms':     'delete_wms_records',
    'saldos':  'delete_saldos_records',
    'etqmang': 'delete_etqmang_records',
    'epts':    'delete_epts_records',
}

@app.route('/api/wms/delete', methods=['POST'])
def api_wms_delete():
    return _delete_module_selected('wms')

@app.route('/api/saldos/delete', methods=['POST'])
def api_saldos_delete():
    return _delete_module_selected('saldos')

@app.route('/api/etqmang/delete', methods=['POST'])
def api_etqmang_delete():
    return _delete_module_selected('etqmang')

@app.route('/api/epts/delete', methods=['POST'])
def api_epts_delete():
    return _delete_module_selected('epts')

def _delete_module_selected(module):
    """BORRADO DEFINITIVO (por rowid) de los registros seleccionados del módulo."""
    from core import local_db as ldb
    payload = _module_payload(module)
    if payload is None:
        return _module_denied(module)
    ids = payload.get('ids', [])
    fn = getattr(ldb, _MODULE_DELETE_CFG[module])
    success, msg = fn(ids)
    log_module_action(module, request.path, f"delete -> {msg}")
    return jsonify({'success': success, 'msg': msg})

def _parse_epts_xlsx(file_stream, only_sheet=None):
    """ANÁLISIS de INVENTARIO DE EPT'S .xlsx (multi-pestaña).
    Recorre las pestañas (o SOLO `only_sheet` si se indica); en cada una busca
    dinámicamente la fila de encabezados localizando la columna 'CARGA EN SISTEMA' y mapea:
    - np         <- 'Referencia Producto (EPT)'
    - descripcion<- 'Descripcion'
    - lote       <- 'Lote (10 digitos)'
    - cantidad   <- 'CARGA EN SISTEMA'
    - unidad_file<- 'Unidad de Medida'
    - almacen    <- 'Nave' (o el nombre de la pestaña si no existe la columna)
    Devuelve (records, sheets, errors)."""
    import pandas as pd

    EPT_HEADERS = {
        'np': 'REFERENCIA',
        'desc': 'DESCRIPCION',
        'lote': 'LOTE',
        'cant': 'CARGA EN SISTEMA',
        'unidad_file': 'UNIDAD DE MEDIDA',
        'nave': 'NAVE',
    }
    records = []
    errors = []

    xls = pd.ExcelFile(file_stream)
    sheets = [only_sheet] if only_sheet else xls.sheet_names

    for sheet in sheets:
        if sheet not in xls.sheet_names:
            errors.append(f'{sheet}: pestaña no existe en el archivo.')
            continue
        try:
            df = pd.read_excel(xls, sheet_name=sheet, header=None)
        except Exception as e:
            errors.append(f'{sheet}: {str(e)}')
            continue
        if df.empty:
            continue

        # Localizar fila de encabezados: debe existir 'CARGA EN SISTEMA'
        header_row = None
        for idx, row in df.iterrows():
            vals = [str(v).strip().upper().replace('Í', 'I') for v in row if pd.notna(v)]
            if any('CARGA EN SISTEMA' in v for v in vals):
                header_row = idx
                break
        if header_row is None:
            continue  # pestaña sin el layout esperado (no es inventario de EPT's)

        hdr = df.iloc[header_row]
        cols = {k: None for k in EPT_HEADERS}
        for c_idx, val in hdr.items():
            v = str(val).strip().upper().replace('Í', 'I') if pd.notna(val) else ''
            for key, needle in EPT_HEADERS.items():
                if cols[key] is None and needle in v:
                    cols[key] = c_idx

        if cols['cant'] is None or cols['np'] is None:
            errors.append(f'{sheet}: pestaña con CARGA EN SISTEMA pero sin columna de referencia/referencia de producto.')
            continue
        if cols['desc'] is None:
            cols['desc'] = cols['np'] + 1

        for idx in range(header_row + 1, len(df)):
            row = df.iloc[idx]
            np_val = str(row[cols['np']]).strip().upper() if pd.notna(row[cols['np']]) else ''
            if not np_val or np_val in ('NAN', 'NONE', 'NP', 'CLAVE', 'CODIGO', 'CÓDIGO', 'NO.PARTE', 'NOPARTE'):
                continue
            if len(np_val) <= 2:
                continue
            desc_str = str(row[cols['desc']]).strip() if cols['desc'] is not None and pd.notna(row[cols['desc']]) else ''
            lote_raw = row[cols['lote']] if cols['lote'] is not None and pd.notna(row[cols['lote']]) else ''
            cant_str = str(row[cols['cant']]) if pd.notna(row[cols['cant']]) else ''
            unidad_file = str(row[cols['unidad_file']]).strip() if cols['unidad_file'] is not None and pd.notna(row[cols['unidad_file']]) else ''
            nave = str(row[cols['nave']]).strip() if cols['nave'] is not None and pd.notna(row[cols['nave']]) else ''
            almacen = nave if nave else sheet
            records.append({
                'np': np_val,
                'sheet': 'EPTS',
                'descripcion': desc_str,
                'unidad': '',
                'empaque': '',
                'almacen': almacen,
                'cantidad': str(cant_str).strip(),
                'contado_por': '',
                'estado': 'OK',
                'folio': '',
                'almacen_pool': '',
                'varias_ubicaciones': 0,
                'layout': 0,
                'lote': str(lote_raw).strip() if str(lote_raw).strip() not in ('nan', 'None', '') else '',
                'unidad_file': unidad_file,
            })

    return records, sheets, errors

@app.route('/api/epts/upload', methods=['POST'])
def api_epts_upload():
    """Recibe el archivo de inventario de EPT's (xlsx multi-pestaña), lo parsea y
    reemplaza TODO el contenido de epts_data (vaciando primero la tabla).
    Si el form incluye 'sheet' (ejm 'Septiembre 2026') SOLO se procesa esa pestaña."""
    if request.form.get('module') != 'epts':
        return _module_denied('epts')
    from core.local_db import load_epts_data

    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'msg': 'No se recibió ningún archivo.'})

    only_sheet = request.form.get('sheet', '') or None

    try:
        records, sheets, errors = _parse_epts_xlsx(f, only_sheet=only_sheet)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error leyendo el archivo: {str(e)}'})

    if not records:
        return jsonify({'success': False, 'msg': 'No se encontraron filas de producto válidas. ' + (' | '.join(errors) if errors else '')})

    success, msg = load_epts_data(records)
    if not success:
        return jsonify({'success': False, 'msg': msg})
    log_module_action('epts', request.path, f"upload -> {len(records)} registros en epts_data (pestaña: {only_sheet or 'todas'})")

    detail = f'Pestaña procesada: {only_sheet}.' if only_sheet else f'Pestañas revisadas: {len(sheets)}.'
    if errors:
        detail += f' Avisos: {"; ".join(errors[:5])}'
    return jsonify({'success': True, 'msg': f'{msg} | {detail}'})

@app.route('/api/epts/empty', methods=['POST'])
def api_epts_empty():
    """VACÍA SOLO la tabla epts_data (pensado para sustituir el inventario por uno definitivo)."""
    if _module_payload('epts') is None:
        return _module_denied('epts')
    from core.local_db import clear_epts_data
    success, msg = clear_epts_data()
    if success:
        log_module_action('epts', request.path, f"empty -> {msg}")
    return jsonify({'success': success, 'msg': msg})

# ============ COMPARATIVO EPTS (Query EPTS vs Datos EPTS) ============

_EPTS_COL_HINTS = {
    'np': ('NP', 'SKU', 'CLAVE', 'CODIGO', 'REFERENCIA', 'DEFAULT_CODE', 'PRODUCTO', 'PARTE', 'EPT'),
    'lote': ('LOTE', 'LOT', 'BATCH', 'SERIAL', 'NUMERO DE LOTE'),
    'qty': ('CANTIDAD', 'QTY', 'QUANTITY', 'QUANT', 'STOCK', 'EXISTENCIA', 'DISPONIBLE'),
    'descripcion': ('DESCRIPCION', 'NOMBRE', 'NAME'),
    'unidad': ('UNIDAD', 'UOM', 'MEDIDA'),
    'almacen': ('ALMACEN', 'BODEGA', 'NAVE', 'UBICACION', 'WAREHOUSE'),
}

def _resolve_epts_cols(row):
    """Detección flexible de columnas del query EPTS por nombre (insensible a mayúsculas/acentos)."""
    pick = {}
    caps = []
    for col in row.keys():
        c = str(col).strip().upper().replace('Í', 'I')
        if (c, col) not in caps:
            caps.append((c, col))
    for field, hints in _EPTS_COL_HINTS.items():
        found = None
        for h in hints:
            hh = h.upper().replace('Í', 'I')
            for c, col in caps:
                if hh == c or hh in c:
                    found = col
                    break
            if found:
                break
        pick[field] = found
    return pick

def _to_qty(v):
    """Convierte un valor (str/num) a float; inválidos/NaN → 0."""
    if v is None:
        return 0.0
    s = str(v).strip().replace(',', '')
    if not s or s.upper() in ('NAN', 'NONE', 'NULL', '-', 'N/A'):
        return 0.0
    try:
        return float(s)
    except ValueError:
        m = re.search(r'[-+]?[0-9]*\.?[0-9]+', s)
        return float(m.group()) if m else 0.0

def _epts_key(np_val, lote_val):
    return (str(np_val or '').strip().upper(), str(lote_val or '').strip())

def _epts_accion(qty_odoo, qty_conteo):
    """Regla de Acción del Comparativo EPTS:
    - QTY Odoo > QTY Conteo y QTY Conteo = 0  -> BAJA
    - QTY Odoo > QTY Conteo y QTY Conteo > 0  -> DISMINUYO
    - QTY Odoo < QTY Conteo                    -> AUMENTO
    - iguales                                  -> SIN CAMBIO"""
    if qty_odoo > qty_conteo and qty_conteo == 0:
        return 'BAJA'
    if qty_odoo > qty_conteo and qty_conteo > 0:
        return 'DISMINUYO'
    if qty_odoo < qty_conteo:
        return 'AUMENTO'
    return 'SIN CAMBIO'

def _epts_ajuste(accion, diff):
    """Regla de Ajuste del Comparativo EPTS:
    - BAJA              -> diff
    - AUMENTO           -> diff * -1
    - DISMINUYO         -> diff * -1
    - SIN CAMBIO        -> 0
    - cualquier otra    -> None (no contemplada)"""
    if accion == 'BAJA':
        return round(diff, 4)
    if accion in ('AUMENTO', 'DISMINUYO'):
        return round(diff * -1, 4)
    if accion == 'SIN CAMBIO':
        return 0.0
    return None

@app.route('/api/epts/compare', methods=['POST'])
def api_epts_compare():
    """Ejecuta el Query EPTS contra Odoo (config query_epts) y construye el comparativo
    contra epts_data. La tabla epts_comparativo se BORRA y se VUELVE A CARGAR en cada ejecución.
    Procedencia por llave (SKU + Lote):
    - AMBOS: existe en query y en Datos EPTS
    - SOLO ODOO: solo en el query
    - SOLO CONTEO: solo en Datos EPTS
    diFF = QTY Odoo - QTY Conteo."""
    if _module_payload('epts') is None:
        return _module_denied('epts')
    from core.local_db import get_epts_data, clear_epts_comparativo, load_epts_comparativo, get_epts_comparativo

    config = load_config()
    query = config.get('query_epts', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query EPTS está vacío en Configuraciones. Guárdalo en el módulo de Configuraciones.'})

    conteo_rows = get_epts_data()

    conteo_by_key = defaultdict(float)
    conteo_ref = {}
    for r in conteo_rows:
        k = _epts_key(r.get('np'), r.get('lote'))
        conteo_by_key[k] += _to_qty(r.get('cantidad'))
        conteo_ref.setdefault(k, r)

    db = DBManager(config)
    try:
        db_rows = db.execute_raw(query)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando el Query EPTS contra Odoo: {str(e)}'})

    if not db_rows:
        return jsonify({'success': False, 'msg': 'El Query EPTS no devolvió resultados contra Odoo.'})

    odoo_by_key = defaultdict(float)
    odoo_ref = {}
    for row in db_rows:
        cols = _resolve_epts_cols(row)
        np_val = row.get(cols['np']) if cols['np'] else ''
        if not str(np_val or '').strip():
            continue
        lote_val = row.get(cols['lote']) if cols['lote'] else ''
        k = _epts_key(np_val, lote_val)
        qty = _to_qty(row.get(cols['qty'])) if cols['qty'] else 0.0
        odoo_by_key[k] += qty
        odoo_ref.setdefault(k, {'row': row, 'cols': cols, 'np': str(np_val).strip().upper(), 'lote': str(lote_val or '').strip()})

    if not odoo_by_key:
        return jsonify({'success': False, 'msg': 'El Query EPTS no devolvió filas con producto (NP) válido.'})

    records = []
    unknown_accions = []
    for k in set(odoo_by_key) | set(conteo_by_key):
        in_odoo = k in odoo_by_key
        in_conteo = k in conteo_by_key
        if in_odoo and in_conteo:
            procedencia = 'AMBOS'
        elif in_odoo:
            procedencia = 'SOLO ODOO'
        else:
            procedencia = 'SOLO CONTEO'

        qty_odoo = round(odoo_by_key.get(k, 0.0), 4)
        qty_conteo = round(conteo_by_key.get(k, 0.0), 4)
        diff = round(qty_odoo - qty_conteo, 4)

        if in_odoo:
            ref = odoo_ref[k]
            row, cols = ref['row'], ref['cols']
            rec = {
                'np': ref['np'],
                'lote': ref['lote'],
                'descripcion': str(row.get(cols['descripcion']) if cols['descripcion'] else '') or '',
                'unidad': str(row.get(cols['unidad']) if cols['unidad'] else '') or '',
                'empaque': '',
                'almacen': str(row.get(cols['almacen']) if cols['almacen'] else '') or '',
                'contado_por': '',
                'estado': 'OK',
                'sheet': '',
                'almacen_pool': '',
                'varias_ubicaciones': 0,
                'layout': 0,
                'unidad_file': '',
            }
            if in_conteo:
                cr = conteo_ref[k]
                rec['descripcion'] = rec['descripcion'] or cr.get('descripcion', '')
                rec['unidad'] = rec['unidad'] or cr.get('unidad', '')
                rec['empaque'] = cr.get('empaque', '')
                rec['almacen'] = rec['almacen'] or cr.get('almacen', '')
                rec['sheet'] = cr.get('sheet', '')
                rec['almacen_pool'] = cr.get('almacen_pool', '')
                rec['varias_ubicaciones'] = 1 if cr.get('varias_ubicaciones') else 0
                rec['layout'] = 1 if cr.get('layout') else 0
                rec['unidad_file'] = cr.get('unidad_file', '')
        else:
            cr = conteo_ref[k]
            rec = {
                'np': k[0],
                'lote': k[1],
                'descripcion': cr.get('descripcion', ''),
                'unidad': cr.get('unidad', ''),
                'empaque': cr.get('empaque', ''),
                'almacen': cr.get('almacen', ''),
                'contado_por': cr.get('contado_por', ''),
                'estado': 'OK',
                'sheet': cr.get('sheet', ''),
                'almacen_pool': cr.get('almacen_pool', ''),
                'varias_ubicaciones': 1 if cr.get('varias_ubicaciones') else 0,
                'layout': 1 if cr.get('layout') else 0,
                'unidad_file': cr.get('unidad_file', ''),
            }

        rec['cantidad'] = str(qty_odoo)
        rec['procedencia'] = procedencia
        rec['qty_odoo'] = qty_odoo
        rec['qty_conteo'] = qty_conteo
        rec['diff'] = diff
        rec['accion'] = _epts_accion(qty_odoo, qty_conteo)
        ajuste = _epts_ajuste(rec['accion'], diff)
        if ajuste is None:
            unknown_accions.append((rec['np'], rec['lote'], rec['accion']))
            ajuste = 0.0
        rec['ajuste'] = ajuste
        records.append(rec)

    success, msg = clear_epts_comparativo()
    if not success:
        return jsonify({'success': False, 'msg': msg})
    success, msg = load_epts_comparativo(records)
    if not success:
        return jsonify({'success': False, 'msg': msg})
    log_module_action('epts', request.path, f"compare -> {len(records)} registros en epts_comparativo")

    totals = {
        'total': len(records),
        'ambos': sum(1 for r in records if r['procedencia'] == 'AMBOS'),
        'solo_odoo': sum(1 for r in records if r['procedencia'] == 'SOLO ODOO'),
        'solo_conteo': sum(1 for r in records if r['procedencia'] == 'SOLO CONTEO'),
    }
    msg_main = f'Comparativo EPTS generado: {len(records)} registro(s).'
    warning = None
    if unknown_accions:
        sample = ', '.join(f"{np}|{lote}|{a}" for np, lote, a in unknown_accions[:5])
        warning = f"Acciones NO contempladas en la regla de Ajuste: {len(unknown_accions)} fila(s) -> {sample}"
        msg_main += ' ' + warning
    return jsonify({'success': True, 'msg': msg_main, 'warning': warning, 'data': get_epts_comparativo(), 'totals': totals})

@app.route('/api/epts/fill_uom_empaque', methods=['POST'])
def api_epts_fill_uom_empaque():
    """Completa unidad y empaque de epts_data usando el Query 1 (query maestro) contra Odoo."""
    if _module_payload('epts') is None:
        return _module_denied('epts')
    from core.local_db import get_epts_nps, update_epts_uom_empaque, sync_epts_comparativo_from_datos
    nps = get_epts_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en epts_data para procesar.'})

    config = load_config()
    db = DBManager(config)

    query = config.get('query', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query 1 (query) está vacío en la configuración.'})

    try:
        db_results = db.execute_query(query, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 1: {str(e)}'})

    if not db_results:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió resultados.'})

    np_map = _extract_uom_empaque_map(db_results)
    if not np_map:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió unidad/empaque para ningún NP.'})

    updated = update_epts_uom_empaque(np_map)
    with_uom = len([i for i in np_map.values() if i.get('unidad')])
    with_emp = len([i for i in np_map.values() if i.get('empaque')])
    sync_ok, sync_msg = sync_epts_comparativo_from_datos()
    log_module_action('epts', request.path, f"fill_uom_empaque -> {updated} filas en epts_data ({len(nps)} NPs procesados) | comparativo: {sync_msg}")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q1': len(np_map),
        'with_uom': with_uom,
        'with_empaque': with_emp,
        'sync': {'success': sync_ok, 'msg': sync_msg},
    })

@app.route('/api/epts/fill_locations_q2', methods=['POST'])
def api_epts_fill_locations_q2():
    """Ubica los NPs de epts_data usando SOLO el Query 2 (query_existencias).
    Llena la columna almacen_pool de epts_data e indica varias_ubicaciones."""
    if _module_payload('epts') is None:
        return _module_denied('epts')
    from core.local_db import get_epts_nps, update_epts_location, sync_epts_comparativo_from_datos
    nps = get_epts_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en epts_data para procesar.'})

    config = load_config()
    db = DBManager(config)

    query = config.get('query_existencias', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query 2 (query_existencias) está vacío en la configuración.'})

    try:
        q2_results = db.execute_query(query, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 2: {str(e)}'})

    if not q2_results:
        return jsonify({'success': False, 'msg': 'El Query 2 no devolvió resultados.'})

    np_map = {}
    q2_map = _extract_location_map(q2_results)
    for clave, info in q2_map.items():
        if clave:
            np_map[clave] = info

    with_varias = len([i for i in np_map.values() if i.get('varias')])
    updated = update_epts_location(np_map)
    sync_ok, sync_msg = sync_epts_comparativo_from_datos()
    log_module_action('epts', request.path, f"fill_locations_q2 -> {updated} filas en epts_data ({len(nps)} NPs procesados) | comparativo: {sync_msg}")
    return jsonify({
        'success': True,
        'updated': updated,
        'processed': len(nps),
        'matched_q2': len(np_map),
        'with_varias': with_varias,
        'still_blank': len([np for np in nps if not (np_map.get(np) or {}).get('ubicacion')]),
        'sync': {'success': sync_ok, 'msg': sync_msg},
    })

@app.route('/api/epts/transfer', methods=['POST'])
def api_epts_transfer():
    return _do_transfer_to_pool('epts')

# =================== ANÁLISIS FINAL ===================

_AF_UBICACION_BLOQUE = {
    'Physical Locations/AMP/Stock/B&A': 'B&A',
    'Physical Locations/AMP/Stock/Insumos': 'Insumos',
    "Physical Locations/AMP/Stock/Prop. Cte.": 'Prop. Cliente',
}

def _parse_analisis_final_xlsx(file_stream):
    """Parsea INVENTARIO MP 2026.xlsx (pestañas MP y EPT) para Análisis Final.
    MP: clasifica por Ubicación (excluye EPTs).
    EPT: todas las filas con bloque='EPT'.
    Retorna (records, stats)."""
    import pandas as pd

    records = []
    stats = {'mp_total': 0, 'mp_loaded': 0, 'ept_total': 0, 'bloques': {}}

    xls = pd.ExcelFile(file_stream)

    if 'MP' in xls.sheet_names:
        df_mp = pd.read_excel(xls, sheet_name='MP')
        stats['mp_total'] = len(df_mp)
        for _, row in df_mp.iterrows():
            ubicacion = str(row.get('Ubicación', '') or '').strip()
            bloque = _AF_UBICACION_BLOQUE.get(ubicacion)
            if bloque is None:
                continue
            np_val = str(row.get('z', '') or '').strip()
            if not np_val:
                continue
            try:
                qty_odoo = float(row.get('Cantidad Odoo', 0) or 0)
            except (TypeError, ValueError):
                qty_odoo = 0.0
            try:
                qty_conteo = float(row.get('Cantidad Conteo', 0) or 0)
            except (TypeError, ValueError):
                qty_conteo = 0.0
            records.append({
                'np': np_val,
                'descripcion': str(row.get('Descrición', '') or '').strip(),
                'bloque': bloque,
                'unidad': str(row.get('UdM', '') or '').strip(),
                'lote': str(row.get('Lote', '') or '').strip(),
                'qty_odoo': qty_odoo,
                'qty_conteo': qty_conteo,
                'empaque': str(row.get('Material_type', '') or '').strip(),
                'almacen': ubicacion,
                'procedencia': str(row.get('Origen', '') or '').strip(),
                'sheet': 'MP',
            })
            stats['bloques'][bloque] = stats['bloques'].get(bloque, 0) + 1
        stats['mp_loaded'] = sum(stats['bloques'].values())

    if 'EPT' in xls.sheet_names:
        df_ept = pd.read_excel(xls, sheet_name='EPT')
        stats['ept_total'] = len(df_ept)
        loaded = 0
        skipped_total = 0
        for _, row in df_ept.iterrows():
            np_val = str(row.get('NP', '') or '').strip()
            np_low = np_val.lower()
            if not np_val or np_low in ('nan', 'none', 'n/a', 'nulo', 'null'):
                # Fila TOTAL/sin código real de la hoja EPT: se descarta (sin SKU ni descripción real).
                skipped_total += 1
                continue
            try:
                qty_odoo = float(row.get('QTY Odoo', 0) or 0)
            except (TypeError, ValueError):
                qty_odoo = 0.0
            try:
                qty_conteo = float(row.get('QTY Conteo', 0) or 0)
            except (TypeError, ValueError):
                qty_conteo = 0.0
            records.append({
                'np': np_val,
                'descripcion': str(row.get('Descripción', '') or row.get('Descrición', '') or '').strip(),
                'bloque': 'EPT',
                'unidad': str(row.get('Unidad', '') or '').strip(),
                'lote': str(row.get('Lote', '') or '').strip(),
                'qty_odoo': qty_odoo,
                'qty_conteo': qty_conteo,
                'empaque': str(row.get('Empaque', '') or '').strip(),
                'almacen': str(row.get('Ubicación', '') or '').strip(),
                'procedencia': str(row.get('Procedencia', '') or '').strip(),
                'sheet': 'EPT',
            })
            loaded += 1
        stats['ept_loaded'] = loaded
        stats['ept_skipped_total'] = skipped_total
        stats['bloques']['EPT'] = loaded

    return records, stats

@app.route('/analisis_final')
def analisis_final_view():
    from core.local_db import init_db
    init_db()
    return render_template('analisis_final.html')

# ============ MÓDULO PT: CARGA CATÁLOGOS CEDIS 1 ============

@app.route('/pt/carga_cedis1')
def pt_carga_cedis1_view():
    from core.local_db import init_db
    init_db()
    return render_template('pt_carga_cedis1.html')

@app.route('/api/pt/carga_cedis1/odoo/data')
def api_pt_carga_cedis1_odoo_data():
    from core.local_db import get_pt_cedis1_odoo_data, get_pt_metadata
    return jsonify({
        'data': get_pt_cedis1_odoo_data(),
        'last_update': get_pt_metadata('cedis1_odoo_last_update')
    })

@app.route('/api/pt/carga_cedis1/wms/data')
def api_pt_carga_cedis1_wms_data():
    from core.local_db import get_pt_wms1_data, get_pt_metadata
    return jsonify({
        'data': get_pt_wms1_data(),
        'last_update': get_pt_metadata('wms1_last_update')
    })

def _reload_cedis1_odoo_rows():
    """Ejecuta la query de catálogo de Odoo CEDIS 1 y devuelve (success, msg, rows).
    No escribe nada: solo consulta. Devuelve False si no se puede consultar."""
    config = load_config()
    query = config.get('pt_queries', {}).get('cedis1_odoo', {}).get('query', '')
    if not query.strip():
        return False, 'Query CEDIS 1 (Odoo) no configurado.', []
    from core.db_manager import DBManager
    try:
        db = DBManager(config)
        rows = db.execute_raw(query)
    except Exception as e:
        return False, f'Error ejecutando query Odoo CEDIS 1: {str(e)}', []
    return True, f'Odoo CEDIS 1: {len(rows)} registros.', rows

def _reload_cedis1_wms_rows():
    """Ejecuta la query de catálogo de WMS 1 (CEDIS 1) y devuelve (success, msg, rows).
    No escribe nada: solo consulta. Devuelve False si no se puede consultar."""
    config = load_config()
    query = config.get('pt_queries', {}).get('wms1', {}).get('query', '')
    if not query.strip():
        return False, 'Query WMS 1 (CEDIS 1) no configurado.', []
    pt_wms = config.get('pt_wms', {}).get('wms1')
    if not pt_wms:
        return False, 'Credenciales de WMS 1 no configuradas.', []
    from core.db_manager import DBManagerMySQL
    try:
        db = DBManagerMySQL(pt_wms)
        rows = db.execute_raw(query)
    except Exception as e:
        return False, f'Error ejecutando query WMS 1: {str(e)}', []
    return True, f'WMS 1 (CEDIS 1): {len(rows)} registros.', rows

@app.route('/api/pt/carga_cedis1/odoo/reload', methods=['POST'])
def api_pt_carga_cedis1_odoo_reload():
    from core.local_db import load_pt_cedis1_odoo_data, get_pt_metadata
    success, msg, rows = _reload_cedis1_odoo_rows()
    if not success:
        return jsonify({'success': False, 'msg': msg, 'data': []})
    success, msg = load_pt_cedis1_odoo_data(rows)
    return jsonify({
        'success': success, 
        'msg': msg, 
        'data': rows if success else [],
        'last_update': get_pt_metadata('cedis1_odoo_last_update') if success else ''
    })

@app.route('/api/pt/carga_cedis1/wms/reload', methods=['POST'])
def api_pt_carga_cedis1_wms_reload():
    from core.local_db import load_pt_wms1_data, get_pt_metadata
    success, msg, rows = _reload_cedis1_wms_rows()
    if not success:
        return jsonify({'success': False, 'msg': msg, 'data': []})
    success, msg = load_pt_wms1_data(rows)
    return jsonify({
        'success': success, 
        'msg': msg, 
        'data': rows if success else [],
        'last_update': get_pt_metadata('wms1_last_update') if success else ''
    })

def _do_pt_actualizacion(records, key_col='np'):
    if not records:
        return False, "No hay datos en la tabla para actualizar.", []
        
    # Identificar la columna NP
    first_rec = records[0]
    exist_key_col = key_col
    candidates = ['np', 'sku', 'clave', 'codigo', 'default_code', 'referencia', 'producto']
    for cand in candidates:
        for k in first_rec.keys():
            if cand == k.lower():
                exist_key_col = k
                break
    else:
        if exist_key_col not in first_rec:
             exist_key_col = list(first_rec.keys())[0]

    nps = []
    for r in records:
        val = str(r.get(exist_key_col, '')).strip().upper()
        if val and val not in nps:
            nps.append(val)
            
    if not nps:
        return False, "No se encontraron claves (NPs) válidas en los datos.", []
        
    config = load_config()
    query = config.get('pt_queries', {}).get('actualizacion_datos', {}).get('query', '')
    if not query.strip() or ('{NPs}' not in query and '{NP}' not in query):
        return False, "Query 'Actualización de Datos' no configurado o no contiene el placeholder {NPs} o {NP}.", []
        
    from core.db_manager import DBManager
    try:
        db = DBManager(config)
        update_rows = db.execute_query(query, nps)
    except Exception as e:
        return False, f"Error ejecutando query de actualización: {str(e)}", []
        
    if not update_rows:
        return True, "El query se ejecutó pero no devolvió resultados para los NPs actuales.", records
        
    from core.local_db import merge_pt_data
    updated_records, count = merge_pt_data(records, update_rows, key_col='np')
    
    return True, f"Se enriquecieron {count} registros exitosamente.", updated_records

@app.route('/api/pt/carga_cedis1/odoo/update', methods=['POST'])
def api_pt_carga_cedis1_odoo_update():
    from core.local_db import get_pt_cedis1_odoo_data, load_pt_cedis1_odoo_data
    records = get_pt_cedis1_odoo_data()
    success, msg, updated_records = _do_pt_actualizacion(records)
    if success and updated_records:
        load_pt_cedis1_odoo_data(updated_records)
    return jsonify({'success': success, 'msg': msg, 'data': updated_records})

@app.route('/api/pt/carga_cedis1/wms/update', methods=['POST'])
def api_pt_carga_cedis1_wms_update():
    from core.local_db import get_pt_wms1_data, load_pt_wms1_data
    records = get_pt_wms1_data()
    success, msg, updated_records = _do_pt_actualizacion(records)
    if success and updated_records:
        load_pt_wms1_data(updated_records)
    return jsonify({'success': success, 'msg': msg, 'data': updated_records})


# ============ MÓDULO PT: CONSOLIDADO CEDIS 1 ============

@app.route('/pt/consolidado_cedis1')
def pt_consolidado_cedis1_view():
    from core.local_db import init_db
    init_db()
    return render_template('pt_consolidado_cedis1.html')

@app.route('/api/pt/consolidado_cedis1/data')
def api_pt_consolidado_cedis1_data():
    from core.local_db import get_pt_consolidado_cedis1, get_pt_metadata
    records = get_pt_consolidado_cedis1()
    # Blindaje: si alguna fila guardada no trae DIFF/Acción, calcularlos al vuelo
    for r in records:
        try:
            m_f_odoo = float(r.get('QTY ODOO FINAL', 0) or 0)
            m_f_wms = float(r.get('QTY WMS FINAL', 0) or 0)
        except Exception:
            m_f_odoo = m_f_wms = 0.0
        m_diff = round(m_f_odoo - m_f_wms, 4)
        r['DIFF'] = m_diff
        r['Acción'] = _calc_consolidado_accion(m_f_odoo, m_f_wms, m_diff)
    return jsonify({
        'data': records,
        'last_update': get_pt_metadata('consolidado_cedis1_last_update'),
        'campos': _get_preparados_campos(),
        'obsoleto': _consolidado_obsoleto(),
    })

_REMS_BLOQUES = [
    {'bloque': 'Remisionado No embarcado', 'campo': 'Remisionado no Embarcado'},
    {'bloque': 'Remisionado No documentado', 'campo': 'Remisionado no Documentado'},
    {'bloque': 'Zar Kruse', 'campo': 'Zar Kruse'},
    {'bloque': 'Otra Ubicación', 'campo': 'Otra Ubicación'},
    {'bloque': 'Transferencias', 'campo': 'Transferencias'},
    {'bloque': 'Propiedad de cliente', 'campo': 'Propiedad de cliente'},
]

def _calc_consolidado_accion(qty_odoo_final, qty_wms_final, diff):
    """Calcula la Acción del Consolidado CEDIS 1.
    ERROR si cualquiera de los finales es negativo; si no, la regla normal."""
    if qty_odoo_final < 0 or qty_wms_final < 0:
        return 'ERROR'
    if diff < 0 and qty_odoo_final == 0:
        return 'ALTA'
    if diff < 0 and qty_odoo_final > 0:
        return 'AUMENTO'
    if diff > 0 and qty_wms_final > 0:
        return 'DECREMENTO'
    if diff > 0 and qty_wms_final == 0:
        return 'BAJA'
    return 'NO HAGO NADA'

def _get_preparados_campos():
    """Devuelve la lista de bloques dinámicos con su config actual:
    [{campo, dest, op, has_data}]. Se usa para calcular columnas y para
    el frontend (color por dest y signo +/− por op)."""
    from core.local_db import group_sum_pt_wms1_archivos, get_pt_metadata
    campos = []
    for cfg in _REMS_BLOQUES:
        bloque = cfg['bloque']
        mapa = group_sum_pt_wms1_archivos(bloque)
        dest = (get_pt_metadata(f'conf_wms1_dest_{bloque}') or 'odoo').lower()
        op = (get_pt_metadata(f'conf_wms1_op_{bloque}') or 'sumar').lower()
        campos.append({
            'campo': cfg['campo'],
            'dest': dest,
            'op': op,
            'has_data': bool(mapa),
        })
    return campos

def _apply_remisionado(records):
    """Agrega/actualiza los campos de bloques tipo remisionado ('Remisionado …',
    'Zar Kruse', 'Otra Ubicación', 'Transferencias'), más 'QTY ODOO FINAL' y
    'QTY WMS FINAL', a los registros del Consolidado.
    Por cada bloque:
    - destino 'odoo' => su campo va justo después de QTY ODOO; 'wms' => después de QTY WMS.
    - Si el bloque no trae datos, se omite su campo.
    - Los Finales acumulan ±valor de todos los bloques según su destino,
      respetando la operación Sumar/Restar de cada config."""
    from core.local_db import group_sum_pt_wms1_archivos, get_pt_metadata

    preparados = []
    for cfg in _REMS_BLOQUES:
        bloque = cfg['bloque']
        mapa = group_sum_pt_wms1_archivos(bloque)
        dest = (get_pt_metadata(f'conf_wms1_dest_{bloque}') or 'odoo').lower()
        op = (get_pt_metadata(f'conf_wms1_op_{bloque}') or 'sumar').lower()
        sign = -1 if op == 'restar' else 1
        preparados.append({
            'campo': cfg['campo'],
            'mapa': mapa,
            'dest': dest,
            'sign': sign,
            'has_data': bool(mapa),
        })

    out = []
    for r in records:
        clave = str(r.get('CLAVE', '')).strip().upper()
        try:
            qty_odoo = float(r.get('QTY ODOO', 0) or 0)
        except Exception:
            qty_odoo = 0.0
        try:
            qty_wms = float(r.get('QTY WMS', 0) or 0)
        except Exception:
            qty_wms = 0.0

        valores = []
        for p in preparados:
            val = None
            if p['has_data']:
                val = p['mapa'].get(clave)
            valores.append(val)

        rec = {
            'CLAVE': r.get('CLAVE', clave),
            'DESCRIPCION': r.get('DESCRIPCION', ''),
            'FAMILIA': r.get('FAMILIA', ''),
            'PRESENTACION': r.get('PRESENTACION', ''),
            'UDM': r.get('UDM', ''),
            'ALMACEN': r.get('ALMACEN', ''),
            'ORIGEN': r.get('ORIGEN', ''),
            'UDV': r.get('UDV', ''),
        }
        rec['QTY ODOO'] = round(qty_odoo, 4)
        for p, val in zip(preparados, valores):
            if p['has_data'] and p['dest'] == 'odoo':
                rec[p['campo']] = round(val, 4) if val is not None else ''
        rec['QTY WMS'] = round(qty_wms, 4)
        for p, val in zip(preparados, valores):
            if p['has_data'] and p['dest'] == 'wms':
                rec[p['campo']] = round(val, 4) if val is not None else ''

        add_odoo = 0.0
        add_wms = 0.0
        for p, val in zip(preparados, valores):
            if val is None:
                continue
            if p['dest'] == 'odoo':
                add_odoo += p['sign'] * val
            elif p['dest'] == 'wms':
                add_wms += p['sign'] * val
        rec['QTY ODOO FINAL'] = round(qty_odoo + add_odoo, 4)
        rec['QTY WMS FINAL'] = round(qty_wms + add_wms, 4)
        rec['DIFF'] = round((qty_odoo + add_odoo) - (qty_wms + add_wms), 4)
        rec['Acción'] = _calc_consolidado_accion(rec['QTY ODOO FINAL'], rec['QTY WMS FINAL'], rec['DIFF'])
        out.append(rec)
    return out

def _parse_qty(value):
    """Parsea una cantidad de forma robusta (acepta coma decimal y miles).
    Devuelve float, o None si no es un número válido."""
    s = str(value).strip().replace(' ', '').replace('$', '').replace('%', '')
    if not s:
        return None
    def _fin(f):
        if f != f or abs(f) == float('inf'):
            return None
        return f
    try:
        return _fin(float(s))
    except ValueError:
        pass
    # Coma decimal sin punto (ej. '1,5')
    if ',' in s and '.' not in s:
        try:
            return _fin(float(s.replace(',', '.')))
        except ValueError:
            pass
    # Ambos separadores: miles con coma o con punto (ej. '1,500.50' o '1.500,50')
    if ',' in s and '.' in s:
        if s.rfind('.') > s.rfind(','):
            s2 = s.replace(',', '')
        else:
            s2 = s.replace('.', '').replace(',', '.')
        try:
            return _fin(float(s2))
        except ValueError:
            pass
    return None

def _refresh_consolidado_after_archivo():
    """Re-aplica los campos de bloques y los Finales al consolidado almacenado
    (sin tocar catálogos) tras subir/vaciar archivos o cambiar config.
    Actualiza consolidado_cedis1_last_update."""
    from core.local_db import get_pt_consolidado_cedis1, load_pt_consolidado_cedis1
    records = get_pt_consolidado_cedis1()
    if not records:
        return False, 'No hay consolidado aún; ejecuta "Recargar" primero.'
    records = _apply_remisionado(records)
    ok, msg = load_pt_consolidado_cedis1(records)
    return ok, msg

def _consolidado_obsoleto():
    """Detecta fuentes (catálogos) más nuevas que el consolidado."""
    from core.local_db import get_pt_metadata
    cons = get_pt_metadata('consolidado_cedis1_last_update') or ''
    fuentes = [('Catálogo Odoo CEDIS 1', 'cedis1_odoo_last_update'), ('Catálogo WMS 1', 'wms1_last_update')]
    stale = []
    for nombre, k in fuentes:
        t = get_pt_metadata(k) or ''
        if t and t > cons:
            stale.append(nombre)
    return stale

def run_update_consolidado_cedis1():
    """Función secuencial autónoma para actualizar el Consolidado.
    Diseñada para poder ser ejecutada tanto por UI como por futuros Cron Jobs.
    Sigue una secuencia estricta de 5 pasos, incluyendo la inyección y el forzado de ALMACEN."""
    from core.local_db import get_pt_consolidado_cedis1, load_pt_consolidado_cedis1, set_pt_metadata, backup_db
    import datetime

    backup_db()

    # Paso 1: Lectura
    records = get_pt_consolidado_cedis1()
    if not records:
        return False, "No hay datos en el consolidado para actualizar.", []

    nps = []
    for r in records:
        clave = str(r.get('CLAVE', '')).strip().upper()
        if clave and clave not in nps:
            nps.append(clave)

    if not nps:
        return False, "No se encontraron claves válidas en el consolidado.", []

    # Paso 2: Inyección y Ejecución
    config = load_config()
    query = config.get('pt_queries', {}).get('actualizacion_datos', {}).get('query', '')
    if not query.strip() or ('{NPs}' not in query and '{NP}' not in query):
        return False, "Query 'Actualización de Datos' no configurado o le falta el tag {NP}.", []

    from core.db_manager import DBManager
    try:
        db = DBManager(config)
        update_rows = db.execute_query(query, nps)
    except Exception as e:
        return False, f"Error en query de actualización: {str(e)}", []

    if not update_rows:
        # Si no hay match, al menos forzamos el almacén
        for r in records:
            r['ALMACEN'] = "Physical Locations/APT/Stock/Cedis I"
        records = _apply_remisionado(records)
        load_pt_consolidado_cedis1(records)
        set_pt_metadata('consolidado_cedis1_last_update', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        return True, "No hubo coincidencias nuevas en Odoo. Se forzó el almacén.", records

    # Paso 3: Cruce / Merge
    from core.local_db import merge_pt_data
    # merge_pt_data ya hace match case-insensitive
    updated_records, count = merge_pt_data(records, update_rows, key_col='CLAVE')

    # Paso 4: Sobreescritura Forzada de Almacén
    for r in updated_records:
        r['ALMACEN'] = "Physical Locations/APT/Stock/Cedis I"

    # Paso 4.5: Campos remisionado + finales
    updated_records = _apply_remisionado(updated_records)

    # Paso 5: Persistencia
    load_pt_consolidado_cedis1(updated_records)
    set_pt_metadata('consolidado_cedis1_last_update', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

    return True, f"Consolidado actualizado: {count} registros enriquecidos y almacenes forzados.", updated_records

@app.route('/api/pt/consolidado_cedis1/update', methods=['POST'])
def api_pt_consolidado_cedis1_update():
    from core.local_db import get_pt_metadata
    success, msg, updated_records = run_update_consolidado_cedis1()
    return jsonify({
        'success': success, 
        'msg': msg, 
        'data': updated_records,
        'last_update': get_pt_metadata('consolidado_cedis1_last_update'),
        'campos': _get_preparados_campos(),
        'obsoleto': _consolidado_obsoleto(),
    })

@app.route('/api/pt/consolidado_cedis1/reload', methods=['POST'])
def api_pt_consolidado_cedis1_reload():
    from core.local_db import load_pt_cedis1_odoo_data, load_pt_wms1_data, load_pt_consolidado_cedis1, get_pt_metadata, backup_db
    
    backup_db()
    
    # ——— PASO 1 (LO PRIMERO LO PRIMERO): cargar catálogos frescos desde los
    # servidores. Se consultan AMBOS sin escribir; si cualquiera falla se aborta
    # la operación completa sin guardar nada (evita cruces híbridos). ———
    ok_o, msg_o, odoo_data = _reload_cedis1_odoo_rows()
    if not ok_o:
        return jsonify({'success': False, 'msg': '❌ Catálogos NO actualizados — no se guardó nada. ' + msg_o})
    ok_w, msg_w, wms_data = _reload_cedis1_wms_rows()
    if not ok_w:
        return jsonify({'success': False, 'msg': '❌ Catálogos NO actualizados — no se guardó nada. ' + msg_w})
    
    if not odoo_data and not wms_data:
        return jsonify({'success': False, 'msg': 'Ambos catálogos vinieron vacíos; no se guardó nada.'})
    
    # ——— PASO 2: persistir los catálogos (ambas consultas OK) ———
    load_pt_cedis1_odoo_data(odoo_data)
    load_pt_wms1_data(wms_data)
    
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
        if not k or k in ('NONE', 'NAN', 'NULL', 'N/A'): continue
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
        if not k or k in ('NONE', 'NAN', 'NULL', 'N/A'): continue
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
    
    # Extraer nombres reales de las columnas en Odoo ignorando case
    def get_odoo_val(row_dict, target_col):
        if not row_dict: return ''
        for k, v in row_dict.items():
            if k.lower() == target_col.lower():
                return v
        return ''
        
    for k in sorted(all_keys):
        in_odoo = k in odoo_map
        in_wms = k in wms_map
        
        estado = "AMBOS"
        if in_odoo and not in_wms:
            estado = "SOLO ODOO"
        elif in_wms and not in_odoo:
            estado = "SOLO WMS"
            
        qty_odoo_sum = odoo_map[k]['_qty_sum_'] if in_odoo else 0.0
        qty_wms_sum = wms_map[k]['_qty_sum_'] if in_wms else 0.0
        
        # Determine source for descriptive fields
        if estado in ["AMBOS", "SOLO ODOO"]:
            source_row = odoo_map.get(k, {})
            # Look for exact Odoo names
            desc = get_odoo_val(source_row, 'descripcion')
            almacen = get_odoo_val(source_row, 'almacen')
            familia = get_odoo_val(source_row, 'familia')
            presentacion = get_odoo_val(source_row, 'presentacion')
            udm = get_odoo_val(source_row, 'udm')
            udv = get_odoo_val(source_row, 'udv')
        else:
            source_row = wms_map.get(k, {})
            # Flexible lookups for WMS (since it's SOLO WMS)
            def find_wms_val(*hints):
                for key_name, val in source_row.items():
                    k_low = key_name.lower()
                    for h in hints:
                        if h in k_low: return val
                return ''
                
            desc = find_wms_val('descripcion', 'desc', 'product_name', 'producto', 'name')
            almacen = find_wms_val('almacen', 'ubicacion', 'location', 'nave')
            familia = find_wms_val('familia', 'category', 'categoria')
            presentacion = find_wms_val('presentacion', 'empaque', 'package')
            udm = find_wms_val('udm', 'uom', 'unidad')
            udv = find_wms_val('udv')

        # Orden estricto según la especificación:
        # 1. CLAVE, 2. DESCRIPCION, 3. FAMILIA, 4. PRESENTACION, 5. UDM
        # 6. ALMACEN, 7. ORIGEN, 8. UDV, 9. QTY ODOO, 10. QTY WMS
        rec = {
            'CLAVE': k,
            'DESCRIPCION': str(desc),
            'FAMILIA': str(familia),
            'PRESENTACION': str(presentacion),
            'UDM': str(udm),
            'ALMACEN': str(almacen),
            'ORIGEN': estado,
            'UDV': str(udv),
            'QTY ODOO': round(qty_odoo_sum, 4),
            'QTY WMS': round(qty_wms_sum, 4)
        }
        
        consolidado.append(rec)
        
    consolidado = _apply_remisionado(consolidado)
    
    success, msg = load_pt_consolidado_cedis1(consolidado)
    
    if success:
        msg = f'✅ Catálogos ({msg_o} | {msg_w}) → {msg}'
    
    return jsonify({
        'success': success, 
        'msg': msg, 
        'data': consolidado,
        'last_update': get_pt_metadata('consolidado_cedis1_last_update') if success else '',
        'campos': _get_preparados_campos(),
        'obsoleto': _consolidado_obsoleto(),
    })

# ============ MÓDULO PT: ACTUALIZAR WMS (AJUSTE DE CANTIDAD) ============

def _mysql_str(s):
    """Escapa una cadena para usarla como literal dentro de un query MySQL
    (backslash y comilla simple), evitando inyección SQL."""
    return str(s).replace('\\', '\\\\').replace("'", "''")

def _validar_update_directa(query):
    """Valida la estructura del query 'Actualización Directa WMS 1' antes de usarlo."""
    if not query or not query.strip():
        return False, "Query 'Actualización Directa WMS 1' no configurado."
    q_upper = query.upper()
    if not q_upper.strip().startswith('UPDATE'):
        return False, 'El query de Actualización debe iniciar con UPDATE.'
    if 'SET' not in q_upper or 'WHERE' not in q_upper:
        return False, 'El query de Actualización debe contener SET y WHERE.'
    if '{NUEVA_CANTIDAD}' not in query:
        return False, 'El query debe contener el tag {NUEVA_CANTIDAD}.'
    if '{ID_LOTE}' not in query:
        return False, 'El query debe contener el tag {ID_LOTE}.'
    return True, ''

def _wms1_info_query(config, ubicacion):
    """Construye el query de info de rack sustituyendo la ubicación (con escape)."""
    qcfg = config.get('pt_queries', {}).get('wms1_info_ubicacion_rack', {})
    query = qcfg.get('query', '')
    if not query.strip():
        return None, 'Query de info de rack (OBTENER INFO UBICACIÓN RACK) no configurado.'
    if '{NOMBRE_DE_LA_UBICACION}' not in query:
        return None, 'El query de info no contiene el tag {NOMBRE_DE_LA_UBICACION}.'
    return query.replace('{NOMBRE_DE_LA_UBICACION}', _mysql_str(ubicacion)), None

@app.route('/pt/actualizar_wms')
def pt_actualizar_wms_view():
    from core.local_db import init_db
    init_db()
    return render_template('actualizar_wms.html')

@app.route('/api/pt/actualizar_wms/info', methods=['POST'])
def api_pt_actualizar_wms_info():
    """Busca la información de los productos/lotes contenidos en una ubicación
    ejecutando el query 'OBTENER INFO UBICACIÓN RACK' (estructura WMS 1)."""
    data = request.get_json(silent=True) or {}
    ubicacion = str(data.get('ubicacion', '')).strip()
    if not ubicacion:
        return jsonify({'success': False, 'msg': 'Indica la ubicación.'})

    config = load_config()
    qcfg = config.get('pt_queries', {}).get('wms1_info_ubicacion_rack', {})
    pt_wms = config.get('pt_wms', {}).get(qcfg.get('conexion', 'wms1'))
    if not pt_wms:
        return jsonify({'success': False, 'msg': 'Credenciales de WMS 1 no configuradas.'})

    final_query, err = _wms1_info_query(config, ubicacion)
    if err:
        return jsonify({'success': False, 'msg': err})

    from core.db_manager import DBManagerMySQL
    try:
        db = DBManagerMySQL(pt_wms)
        rows = db.execute_raw(final_query)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando query de info: {e}'})

    lotes = [r for r in rows if r.get('lote') is not None]
    return jsonify({
        'success': True,
        'ubicacion_id': rows[0].get('ubicacion') if rows else None,
        'rows': rows,
        'con_lotes': bool(lotes),
    })

@app.route('/api/pt/actualizar_wms/producto', methods=['POST'])
def api_pt_actualizar_wms_producto():
    """Rellena los datos de un SKU no encontrado en la ubicación usando el query
    'Actualización de Datos (Odoo)'. Se usa para el INSERT del lote (fallback)."""
    data = request.get_json(silent=True) or {}
    sku = str(data.get('sku', '')).strip()
    if not sku:
        return jsonify({'success': False, 'msg': 'Ingresa el SKU.'})

    config = load_config()
    qcfg = config.get('pt_queries', {}).get('actualizacion_datos', {})
    query = qcfg.get('query', '')
    if not query.strip() or ('{NP}' not in query and '{NPs}' not in query):
        return jsonify({'success': False, 'msg': "Query 'Actualización de Datos (Odoo)' no configurado o le falta el tag {NP}."})

    from core.db_manager import DBManager
    try:
        db = DBManager(config)
        rows = db.execute_query(query, [sku])
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error consultando Odoo: {e}'})
    if not rows:
        return jsonify({'success': False, 'msg': f'El SKU "{sku}" no se encontró en Odoo (Actualización de Datos).'})
    return jsonify({'success': True, 'producto': rows[0]})

@app.route('/api/pt/actualizar_wms/guardar', methods=['POST'])
def api_pt_actualizar_wms_guardar():
    """Aplica el ajuste: por cada renglón con lote ejecuta el UPDATE 'Actualización
    Directa WMS 1' (por ul.id); sin lote hace INSERT en ubicacionlotes (fallback).
    Luego re-ejecuta el query de info como confirmación y marca el consolidado
    como obsoleto (alerta de recarga)."""
    data = request.get_json(silent=True) or {}
    ubicacion = str(data.get('ubicacion', '')).strip()
    edits = data.get('edits', []) or []
    if not ubicacion:
        return jsonify({'success': False, 'msg': 'Indica la ubicación.'})
    if not edits:
        return jsonify({'success': False, 'msg': 'No hay renglones con nueva cantidad.'})

    normalized = []
    for e in edits:
        sku = str(e.get('sku') or '').strip().upper()
        qty = _parse_qty(str(e.get('nueva_cantidad') or ''))
        if qty is None:
            return jsonify({'success': False, 'msg': f"SKU '{sku}': la cantidad no es un número válido."})
        if qty < 0 or not float(qty).is_integer():
            return jsonify({'success': False, 'msg': f"SKU '{sku}': la cantidad debe ser un entero >= 0 ({qty})."})
        lote_id = None
        lote_raw = e.get('lote')
        if lote_raw is not None and str(lote_raw).strip():
            try:
                lote_id = int(lote_raw)
            except Exception:
                return jsonify({'success': False, 'msg': f"SKU '{sku}': el lote no es válido."})
        normalized.append({
            'sku': _mysql_str(sku),
            'qty': int(qty),
            'lote_id': lote_id,
            'ubicacion_id': e.get('ubicacion_id'),
            'product_name': _mysql_str(str(e.get('product_name') or '')),
            'uom': _mysql_str(str(e.get('uom') or '')),
            'udv': float(e.get('udv') or 0),
            'pieces': int(float(e.get('pieces') or 0)),
        })

    config = load_config()
    pt_wms = config.get('pt_wms', {}).get('wms1')
    if not pt_wms:
        return jsonify({'success': False, 'msg': 'Credenciales de WMS 1 no configuradas.'})
    up_q = config.get('pt_queries', {}).get('actualizacion_directa_wms1', {}).get('query', '')
    ok_update, err_update = _validar_update_directa(up_q)
    if not ok_update:
        return jsonify({'success': False, 'msg': err_update})

    from core.local_db import backup_db, set_pt_metadata, log_module_action
    import datetime
    backup_db()

    from core.db_manager import DBManagerMySQL
    db = DBManagerMySQL(pt_wms)
    resumen = []
    try:
        for e in normalized:
            if e['lote_id'] is not None:
                final = (up_q.replace('{NUEVA_CANTIDAD}', str(e['qty']))
                            .replace('{ID_LOTE}', str(e['lote_id'])))
                afectadas, _ = db.execute_write(final)
            else:
                if not e['ubicacion_id']:
                    return jsonify({'success': False, 'msg': f"SKU '{e['sku']}': no se pudo determinar el id de la ubicación (¿la ubicación existe en WMS?)."})
                ins = (
                    "INSERT INTO ubicacionlotes "
                    "(idUbicacion, producto, product_name, uom, udv, pieces, platform, cantidad, fecha_lote) "
                    f"VALUES ({int(e['ubicacion_id'])}, '{e['sku']}', '{e['product_name']}', "
                    f"'{e['uom']}', {e['udv']}, {e['pieces']}, 0, {e['qty']}, NOW())"
                )
                afectadas, _ = db.execute_write(ins, get_last_id=True)
            resumen.append({'sku': e['sku'], 'lote': e['lote_id'], 'afectadas': int(afectadas)})
        set_pt_metadata('wms1_last_update', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error en la actualización: {e}'})

    final_info, err_info = _wms1_info_query(config, ubicacion)
    conf = []
    if not err_info:
        try:
            conf = db.execute_raw(final_info)
        except Exception:
            conf = []

    log_module_action('pt_actualizar_wms', request.path,
                      f"ubicacion='{ubicacion}' cambios={json.dumps(resumen, ensure_ascii=False)}")
    total = sum(r['afectadas'] for r in resumen)
    return jsonify({
        'success': True,
        'msg': f'Ajuste aplicado en WMS 1: {total} fila(s) afectada(s).',
        'resumen': resumen,
        'confirmacion': conf,
    })

@app.route('/api/pt/actualizar_wms/vaciar', methods=['POST'])
def api_pt_actualizar_wms_vaciar():
    """Vacía una ubicación: borra todos sus lotes y deja el Estado como
    'disponible'. Ambas sentencias corren en una sola transacción (o ninguna).
    Solo toca la ubicación indicada; el resto de la base queda igual."""
    data = request.get_json(silent=True) or {}
    ubicacion = str(data.get('ubicacion', '')).strip()
    if not ubicacion:
        return jsonify({'success': False, 'msg': 'Indica la ubicación.'})

    config = load_config()
    qcfg = config.get('pt_queries', {}).get('vaciar_ubicacion_wms1', {})
    query = qcfg.get('query', '')
    if not query.strip():
        return jsonify({'success': False, 'msg': 'Query de vaciar ubicación no configurado.'})
    if '{NOMBRE_DE_LA_UBICACION}' not in query:
        return jsonify({'success': False, 'msg': 'El query no contiene el tag {NOMBRE_DE_LA_UBICACION}.'})
    if not query.upper().strip().startswith('DELETE') or 'WHERE' not in query.upper():
        return jsonify({'success': False, 'msg': 'El query de vaciar debe ser un DELETE con WHERE.'})

    # Confirmar que la ubicación existe y obtener su id (sin tocar nada)
    info_q, err_info = _wms1_info_query(config, ubicacion)
    if err_info:
        return jsonify({'success': False, 'msg': err_info})
    pt_wms = config.get('pt_wms', {}).get(qcfg.get('conexion', 'wms1'))
    if not pt_wms:
        return jsonify({'success': False, 'msg': 'Credenciales de WMS 1 no configuradas.'})

    from core.db_manager import DBManagerMySQL
    try:
        db = DBManagerMySQL(pt_wms)
        check = db.execute_raw(info_q)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error verificando la ubicación: {e}'})
    if not check:
        return jsonify({'success': False, 'msg': f'La ubicación "{ubicacion}" no existe en la base WMS 1.'})
    ubicacion_id = check[0].get('ubicacion')
    if not ubicacion_id:
        return jsonify({'success': False, 'msg': f'No se pudo determinar el id de la ubicación "{ubicacion}".'})

    from core.local_db import backup_db, set_pt_metadata, log_module_action
    import datetime
    backup_db()

    del_q = query.replace('{NOMBRE_DE_LA_UBICACION}', _mysql_str(ubicacion))
    reset_q = f"UPDATE ubicaciones SET EstadoUbicacion='disponible' WHERE id = {int(ubicacion_id)};"
    try:
        afectadas = db.execute_many_write([del_q, reset_q])
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error vaciando la ubicación: {e}'})

    set_pt_metadata('wms1_last_update', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    log_module_action('pt_actualizar_wms', request.path,
                      f"VACIAR ubicacion='{ubicacion}' id={ubicacion_id} delete={afectadas[0]} reset_estado={afectadas[1]}")

    # Confirmación: re-extraer la ubicación (debe quedar sin lotes y disponible)
    conf = []
    try:
        conf = db.execute_raw(info_q)
    except Exception:
        conf = []
    return jsonify({
        'success': True,
        'msg': f'Ubicación "{ubicacion}" vaciada: {afectadas[0]} lote(s) eliminado(s) y Estado en "disponible".',
        'afectadas': afectadas,
        'confirmacion': conf,
    })

# ============ MÓDULO PT: CARGA ARCHIVOS WMS 1 ============

@app.route('/pt/carga_archivos_wms1')
def pt_carga_archivos_wms1_view():
    from core.local_db import init_db, get_pt_metadata
    init_db()
    # Preparar responsables por defecto
    responsables = {
        'Remisionado No embarcado': get_pt_metadata('resp_wms1_Remisionado No embarcado') or 'Calixto',
        'Remisionado No documentado': get_pt_metadata('resp_wms1_Remisionado No documentado') or 'TI',
        'Zar Kruse': get_pt_metadata('resp_wms1_Zar Kruse') or 'Eulogio',
        'Otra Ubicación': get_pt_metadata('resp_wms1_Otra Ubicación') or 'Eulogio',
        'Transferencias': get_pt_metadata('resp_wms1_Transferencias') or 'Gerardo',
        'Propiedad de cliente': get_pt_metadata('resp_wms1_Propiedad de cliente') or 'Eulogio',
    }
    # Preparar configuraciones operativas
    configs = {}
    for bloque in responsables.keys():
        configs[bloque] = {
            'operacion': get_pt_metadata(f'conf_wms1_op_{bloque}') or 'sumar',
            'destino': get_pt_metadata(f'conf_wms1_dest_{bloque}') or 'odoo'
        }
    return render_template('pt_carga_archivos_wms1.html', responsables=responsables, configs=configs)

@app.route('/api/pt/wms1_archivos/plantilla/<bloque>')
def api_pt_wms1_archivos_plantilla(bloque):
    import io
    import csv
    output = io.StringIO()
    writer = csv.writer(output)
    if bloque == 'Otra Ubicación':
        writer.writerow(['SKU', 'Cantidad', 'Ubicación'])
    else:
        writer.writerow(['SKU', 'Cantidad'])
    output.seek(0)
    
    # Limpiar el nombre del bloque para usarlo en el nombre del archivo
    safe_bloque = "".join(c if c.isalnum() else "_" for c in bloque)
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=plantilla_{safe_bloque}.csv"}
    )

@app.route('/api/pt/wms1_archivos/responsable', methods=['POST'])
def api_pt_wms1_archivos_responsable():
    from core.local_db import set_pt_metadata
    data = request.get_json(silent=True) or {}
    bloque = str(data.get('bloque', '')).strip()
    responsable = str(data.get('responsable', '')).strip()
    if not bloque:
        return jsonify({'success': False, 'msg': 'Falta el bloque'})
    set_pt_metadata(f'resp_wms1_{bloque}', responsable)
    return jsonify({'success': True})

@app.route('/api/pt/wms1_archivos/config', methods=['POST'])
def api_pt_wms1_archivos_config():
    from core.local_db import set_pt_metadata, backup_db
    data = request.get_json(silent=True) or {}
    bloque = str(data.get('bloque', '')).strip()
    operacion = str(data.get('operacion', '')).strip()
    destino = str(data.get('destino', '')).strip()
    if not bloque:
        return jsonify({'success': False, 'msg': 'Falta el bloque'})
    if operacion:
        set_pt_metadata(f'conf_wms1_op_{bloque}', operacion)
    if destino:
        set_pt_metadata(f'conf_wms1_dest_{bloque}', destino)
    # ——— BLINDAJE: conservar el consolidado y re-aplicar los bloques ———
    backup_db()
    ok_ref, msg_ref = _refresh_consolidado_after_archivo()
    msg = 'Configuración guardada'
    if msg_ref:
        msg += f" | {msg_ref}"
    if not ok_ref:
        msg += ' (el consolidado se re-aplicó al recargar)'
    return jsonify({'success': True, 'msg': msg})

@app.route('/api/pt/wms1_archivos/clear', methods=['POST'])
def api_pt_wms1_archivos_clear():
    from core.local_db import clear_pt_wms1_archivo, set_pt_metadata, backup_db
    data = request.get_json(silent=True) or {}
    bloque = str(data.get('bloque', '')).strip()
    if not bloque:
        return jsonify({'success': False, 'msg': 'Falta el bloque'})
    if bloque not in [c['bloque'] for c in _REMS_BLOQUES]:
        return jsonify({'success': False, 'msg': f'Bloque desconocido: {bloque}'})
    success, msg = clear_pt_wms1_archivo(bloque)
    if not success:
        return jsonify({'success': False, 'msg': msg})
    # ——— BLINDAJE ———
    import datetime
    backup_db()
    set_pt_metadata(f'upload_wms1_{bloque}', '')
    ok_ref, msg_ref = _refresh_consolidado_after_archivo()
    if msg_ref:
        msg += f" | {msg_ref}"
    return jsonify({'success': True, 'msg': msg})

@app.route('/api/pt/wms1_archivos/data/<bloque>')
def api_pt_wms1_archivos_data(bloque):
    from core.local_db import get_pt_wms1_archivos
    return jsonify({'data': get_pt_wms1_archivos(bloque)})

@app.route('/api/pt/wms1_archivos/upload', methods=['POST'])
def api_pt_wms1_archivos_upload():
    bloque = request.form.get('bloque')
    if not bloque:
        return jsonify({'success': False, 'msg': 'No se especificó el bloque destino.'})
    
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'msg': 'No se recibió ningún archivo.'})
        
    import pandas as pd
    from core.local_db import load_pt_wms1_archivo, backup_db
    
    try:
        # Detectar el formato (.csv vs .xlsx)
        if f.filename.lower().endswith('.csv'):
            df = pd.read_csv(f)
        else:
            df = pd.read_excel(f)
            
        if df.empty:
            return jsonify({'success': False, 'msg': 'El archivo está vacío.'})
            
        # Buscar columnas flexibles
        def find_col(*hints):
            for col in df.columns:
                c_low = str(col).strip().lower()
                for h in hints:
                    if h in c_low: return col
            return None
            
        sku_col = find_col('sku', 'np', 'clave', 'codigo', 'parte', 'referencia')
        qty_col = find_col('cantidad', 'qty', 'fisico')
        ubi_col = find_col('ubicacion', 'ubicación', 'location', 'almacen')
        
        if bloque == 'Otra Ubicación':
            if not sku_col or not qty_col or not ubi_col:
                return jsonify({'success': False, 'msg': 'Estructura inválida. Se esperaban las columnas: SKU, Cantidad, Ubicación.'})
        else:
            if not sku_col or not qty_col:
                return jsonify({'success': False, 'msg': 'Estructura inválida. Se esperaban las columnas: SKU, Cantidad.'})
                
        records = []
        errores = []
        for i, row in df.iterrows():
            try:
                sku_val = str(row[sku_col]).strip() if pd.notna(row[sku_col]) else ''
                qty_val = str(row[qty_col]).strip() if pd.notna(row[qty_col]) else '0'
                ubi_val = str(row[ubi_col]).strip() if (bloque == 'Otra Ubicación' and ubi_col and pd.notna(row[ubi_col])) else ''
            except Exception:
                continue

            if sku_val and sku_val.lower() not in ('nan', 'none', 'null', '', 'n/a'):
                qty = _parse_qty(qty_val)
                if qty is None:
                    errores.append(f"fila {i + 2}: SKU '{sku_val}' cantidad '{qty_val}'")
                    continue
                records.append({
                    'sku': sku_val.upper(),
                    'cantidad': str(qty),
                    'ubicacion': ubi_val
                })

        if errores:
            limite = '\n'.join(errores[:10])
            extra = f"\n... y {len(errores) - 10} más" if len(errores) > 10 else ''
            return jsonify({'success': False,
                            'msg': f"CANTIDADES NO VÁLIDAS ({len(errores)}): revisa y corrige.\n{limite}{extra}"})

        if not records:
            return jsonify({'success': False, 'msg': 'No se encontraron filas válidas con SKU.'})
            
        from core.local_db import set_pt_metadata
        import datetime
        success, msg = load_pt_wms1_archivo(bloque, records)
        if not success:
            return jsonify({'success': False, 'msg': msg})

        # ——— BLINDAJES ———
        backup_db()
        set_pt_metadata(f'upload_wms1_{bloque}', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        ok_ref, msg_ref = _refresh_consolidado_after_archivo()
        legajo = f" | {msg_ref}" if msg_ref else ""
        return jsonify({'success': success,
                        'msg': msg + legajo,
                        'obsoleto': _consolidado_obsoleto()})
        
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error procesando el archivo: {str(e)}'})

@app.route('/api/analisis_final/data')
def api_analisis_final_data():
    from core.local_db import get_analisis_final
    return jsonify({'data': get_analisis_final()})

@app.route('/api/analisis_final/upload', methods=['POST'])
def api_analisis_final_upload():
    if request.form.get('module') != 'analisis_final':
        return _module_denied('analisis_final')
    from core.local_db import load_analisis_final
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'success': False, 'msg': 'No se recibió ningún archivo.'})
    try:
        records, stats = _parse_analisis_final_xlsx(f)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error leyendo el archivo: {str(e)}'})
    if not records:
        return jsonify({'success': False, 'msg': 'No se encontraron filas válidas en el archivo.'})
    success, msg = load_analisis_final(records)
    if not success:
        return jsonify({'success': False, 'msg': msg})
    log_module_action('analisis_final', request.path,
                      f"upload -> {msg} | MP total={stats['mp_total']} loaded={stats['mp_loaded']} | EPT={stats['ept_total']} | bloques={stats['bloques']}")
    return jsonify({'success': True, 'msg': msg, 'stats': stats})

@app.route('/api/analisis_final/fill_uom', methods=['POST'])
def api_analisis_final_fill_uom():
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    from core.local_db import get_analisis_final_nps, update_analisis_final_uom
    nps = get_analisis_final_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en Análisis Final para procesar.'})
    config = load_config()
    db = DBManager(config)
    query = config.get('query', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query 1 (query) está vacío en la configuración.'})
    try:
        db_results = db.execute_query(query, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 1: {str(e)}'})
    if not db_results:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió resultados.'})
    np_map = _extract_uom_empaque_map(db_results)
    if not np_map:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió unidad/empaque para ningún NP.'})
    updated = update_analisis_final_uom(np_map)
    with_uom = len([i for i in np_map.values() if i.get('unidad')])
    with_emp = len([i for i in np_map.values() if i.get('empaque')])
    log_module_action('analisis_final', request.path, f"fill_uom -> {updated} actualizaciones ({len(nps)} NPs)")
    return jsonify({'success': True, 'updated': updated, 'processed': len(nps),
                    'matched_q1': len(np_map), 'with_uom': with_uom, 'with_empaque': with_emp})

@app.route('/api/analisis_final/fill_descriptions', methods=['POST'])
def api_analisis_final_fill_descriptions():
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    from core.local_db import get_analisis_final_nps, update_analisis_final_descriptions
    nps = get_analisis_final_nps()
    if not nps:
        return jsonify({'success': False, 'msg': 'No hay NPs en Análisis Final para procesar.'})
    config = load_config()
    db = DBManager(config)
    query = config.get('query', '')
    if not query or not query.strip():
        return jsonify({'success': False, 'msg': 'El Query 1 (query) está vacío en la configuración.'})
    try:
        db_results = db.execute_query(query, nps)
    except Exception as e:
        return jsonify({'success': False, 'msg': f'Error ejecutando Query 1: {str(e)}'})
    if not db_results:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió resultados.'})
    np_map = _extract_description_map(db_results)
    if not np_map:
        return jsonify({'success': False, 'msg': 'El Query 1 no devolvió descripciones para ningún NP.'})
    updated = update_analisis_final_descriptions(np_map)
    with_desc = len([d for d in np_map.values() if d])
    log_module_action('analisis_final', request.path, f"fill_descriptions -> {updated} actualizaciones ({len(nps)} NPs)")
    return jsonify({'success': True, 'updated': updated, 'processed': len(nps),
                    'matched_q1': len(np_map), 'with_desc': with_desc})

@app.route('/api/analisis_final/delete', methods=['POST'])
def api_analisis_final_delete():
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    from core.local_db import delete_analisis_final_records
    ids = request.get_json().get('ids', [])
    success, msg = delete_analisis_final_records(ids)
    log_module_action('analisis_final', request.path, f"delete -> {msg}")
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/analisis_final/empty', methods=['POST'])
def api_analisis_final_empty():
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    from core.local_db import clear_analisis_final
    success, msg = clear_analisis_final()
    log_module_action('analisis_final', request.path, f"empty -> {msg}")
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/analisis_final/export')
def api_analisis_final_export():
    """Exporta un bloque del Análisis Final a Excel."""
    import io
    from flask import send_file
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    from core.local_db import get_analisis_final

    bloque = request.args.get('bloque', '')
    rows = get_analisis_final()
    if bloque:
        rows = [r for r in rows if r.get('bloque') == bloque]
    if not rows:
        return jsonify({'success': False, 'msg': 'No hay datos para exportar.'}), 400

    headers = ['NP', 'Descripción', 'Ubicación', 'Unidad', 'Lote', 'QTY Odoo', 'QTY Conteo']
    keys = ['np', 'descripcion', 'almacen', 'unidad', 'lote', 'qty_odoo', 'qty_conteo']

    wb = Workbook()
    ws = wb.active
    ws.title = bloque if bloque else 'Análisis Final'

    header_fill = PatternFill('solid', start_color='454D55')
    header_font = Font(bold=True, color='FFFFFF')
    for ci, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=ci, value=h)
        c.fill = header_fill
        c.font = header_font
        c.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)

    num_fmt = '#,##0.####'
    for ri, r in enumerate(rows, start=2):
        for ci, k in enumerate(keys, start=1):
            cell = ws.cell(row=ri, column=ci)
            val = r.get(k)
            if k in ('qty_odoo', 'qty_conteo'):
                try:
                    cell.value = float(val or 0)
                except (TypeError, ValueError):
                    cell.value = 0.0
                cell.number_format = num_fmt
                cell.alignment = Alignment(horizontal='right')
            else:
                cell.value = '' if val is None else val

    thin = Side(style='thin', color='DEE2E6')
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    for row_cells in ws.iter_rows(min_row=1, max_row=ws.max_row, max_col=len(headers)):
        for cell in row_cells:
            cell.border = border

    widths = [10, 50, 40, 10, 12, 12, 12]
    for ci, w in enumerate(widths, start=1):
        ws.column_dimensions[ws.cell(row=1, column=ci).column_letter].width = w

    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = f"A1:{ws.cell(row=1, column=len(headers)).column_letter}{max(ws.max_row, 1)}"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    fname = f"Analisis_Final_{bloque.replace(' ', '_')}.xlsx" if bloque else "Analisis_Final.xlsx"
    log_module_action('analisis_final', request.path, f"export {bloque} -> {len(rows)} fila(s)")
    return send_file(output, download_name=fname, as_attachment=True)

def _af_audit():
    """Calcula los hallazgos de control de calidad (QC) sobre el modelo Análisis Final."""
    from core.local_db import get_analisis_final
    rows = get_analisis_final()
    findings = []
    bloques = {}

    def invalid_np(s):
        return not str(s or '').strip() or str(s).strip().lower() in ('nan', 'none', 'n/a', 'nulo', 'null')

    # Indices
    np_blocks = {}
    for r in rows:
        np_blocks.setdefault(str(r.get('np') or ''), set()).add(r.get('bloque'))
        bloques[r.get('bloque')] = bloques.get(r.get('bloque'), 0) + 1

    for r in rows:
        np_val = str(r.get('np') or '')
        bloque = r.get('bloque')
        qty_odoo = float(r.get('qty_odoo') or 0)
        qty_conteo = float(r.get('qty_conteo') or 0)
        dif = round(qty_odoo - qty_conteo, 10)

        # Hallazgo CRITICAL: NP inválido sin código real
        if invalid_np(np_val):
            findings.append({
                'sev': 'critical', 'tipo': 'NP sin código',
                'fkey': f"NP_SIN_CODIGO::{bloque}::{np_val}",
                'bloque': bloque, 'np': np_val or '(vacío)',
                'qty_odoo': qty_odoo, 'qty_conteo': qty_conteo,
                'mensaje': 'Fila sin código de producto (NP). Requiere asignar SKU real.',
            })
            continue

        # NP en más de un bloque
        bl = sorted(np_blocks.get(np_val, set()))
        if len(bl) > 1:
            findings.append({
                'sev': 'warning', 'tipo': 'NP en múltiples bloques',
                'fkey': f"NP_MULTI::{np_val}",
                'bloque': '+'.join(bl) if bloque in bl else bloque, 'np': np_val,
                'qty_odoo': qty_odoo, 'qty_conteo': qty_conteo,
                'mensaje': f'El NP {np_val} aparece en bloques: {", ".join(bl)}.',
            })

        # Ambos QTY en 0
        if qty_odoo == 0 and qty_conteo == 0:
            findings.append({
                'sev': 'warning', 'tipo': 'Ambos QTY en 0',
                'fkey': f"QTY_CERO::{bloque}::{np_val}",
                'bloque': bloque, 'np': np_val,
                'qty_odoo': qty_odoo, 'qty_conteo': qty_conteo,
                'mensaje': 'QTY Odoo y QTY Conteo ambos en cero (sin movimiento registrado).',
            })

        # Sin Unidad
        if not str(r.get('unidad') or '').strip():
            findings.append({
                'sev': 'warning', 'tipo': 'Sin Unidad',
                'fkey': f"SIM_UNIDAD::{bloque}::{np_val}",
                'bloque': bloque, 'np': np_val,
                'qty_odoo': qty_odoo, 'qty_conteo': qty_conteo,
                'mensaje': 'No tiene unidad de medida asignada (UDM pendiente).',
            })

        # Sin Descripción
        if not str(r.get('descripcion') or '').strip():
            findings.append({
                'sev': 'warning', 'tipo': 'Sin Descripción',
                'fkey': f"SIM_DESCRIPCION::{bloque}::{np_val}",
                'bloque': bloque, 'np': np_val,
                'qty_odoo': qty_odoo, 'qty_conteo': qty_conteo,
                'mensaje': 'No tiene descripción del producto.',
            })

        # Diferencia QTY odoo vs conteo (info, contado aparte)
        if abs(dif) > 1e-9:
            findings.append({
                'sev': 'info', 'tipo': 'Diferencia QTY Odoo vs Conteo',
                'fkey': f"DIF_QTY::{bloque}::{np_val}",
                'bloque': bloque, 'np': np_val,
                'qty_odoo': qty_odoo, 'qty_conteo': qty_conteo,
                'mensaje': f'Dif: {dif:g} (Odoo {qty_odoo:g} vs Conteo {qty_conteo:g}).',
            })

    # Marías EPT: filas con lote 'nan' (dato basura, ej. MESC). Se corrigen directo
    # dejando el lote en blanco en el modelo (BD), ver api_analisis_final_audit.
    from collections import defaultdict as _dd
    nan_ept_np = _dd(list)
    for r in rows:
        if r.get('bloque') == 'EPT' and str(r.get('lote') or '').strip().lower() == 'nan':
            nan_ept_np[str(r.get('np') or '')].append(r)
    for np_val, rs in nan_ept_np.items():
        findings.append({
            'sev': 'warning', 'tipo': "Lote 'nan' (maría)",
            'fkey': f"LOTE_NAN::EPT::{np_val}",
            'bloque': 'EPT', 'np': np_val,
            'qty_odoo': sum(float(x.get('qty_odoo') or 0) for x in rs),
            'qty_conteo': sum(float(x.get('qty_conteo') or 0) for x in rs),
            'mensaje': f"{len(rs)} fila(s) EPT con lote 'nan' (dato basura, ej. MESC). "
                        'Se corrige directo dejando el lote en blanco en el modelo.',
        })

    summary = {
        'critical': sum(1 for f in findings if f['sev'] == 'critical'),
        'warning': sum(1 for f in findings if f['sev'] == 'warning'),
        'info': sum(1 for f in findings if f['sev'] == 'info'),
        'total': len(rows),
        'super_critical': 0,
    }

    # Tarea: total de SKU del archivo vs filas del modelo
    sku = _af_sku_check(len(rows))
    summary['sku_check'] = sku
    if sku.get('error'):
        findings.append({
            'sev': 'warning', 'tipo': 'Total SKU Archivo vs Modelo',
            'fkey': 'SKU_TOTAL_CHECK', 'bloque': 'Todos', 'np': '',
            'qty_odoo': 0, 'qty_conteo': sku.get('modelo_skus') or 0,
            'mensaje': f"No se pudo verificar el total de SKU: {sku['error']}",
        })
        summary['warning'] += 1
    elif not sku.get('coincide'):
        findings.append({
            'sev': 'super_critical', 'tipo': 'Total SKU Archivo vs Modelo',
            'fkey': 'SKU_TOTAL_CHECK', 'bloque': 'Todos', 'np': '',
            'qty_odoo': sku.get('archivo_skus') or 0, 'qty_conteo': sku.get('modelo_skus') or 0,
            'mensaje': (f"El total de SKU del archivo ({sku.get('archivo_skus')}) NO coincide "
                        f"con las filas del modelo ({sku.get('modelo_skus')}). Acción requerida."),
        })
        summary['super_critical'] = 1

    # Nuevo bloque: Auditoría Query Auditoría 1 vs Análisis Final (comparativo de lotes)
    qa = _af_query_audit(rows)
    summary['query_auditoria'] = qa
    for g in qa.get('grupos', []):
        if g.get('es_hallazgo'):
            findings.append(g)

    # Recalcular contadores para incluir los hallazgos del bloque Query Auditoría 1
    summary['critical'] = sum(1 for f in findings if f['sev'] == 'critical')
    summary['warning'] = sum(1 for f in findings if f['sev'] == 'warning')
    summary['info'] = sum(1 for f in findings if f['sev'] == 'info')

    return {'summary': summary, 'findings': findings, 'bloques': bloques}

def _af_sku_check(modelo_skus):
    """Relee el archivo INVENTARIO MP 2026.xlsx y compara el total de SKU cargables
    (MP cargadas + EPT cargadas, contemplando la fila corregida NPMANDEL1) contra las
    filas actuales del modelo. Devuelve dict con conteos y si coinciden."""
    result = {
        'archivo_skus': None, 'modelo_skus': modelo_skus,
        'mp_loaded': 0, 'ept_loaded': 0, 'coincide': None, 'error': '',
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'analisisfinal', 'INVENTARIO MP 2026.xlsx')
    if not os.path.exists(path):
        result['error'] = f"No se encontró el archivo de inventario en {path}"
        return result
    try:
        with open(path, 'rb') as f:
            records, stats = _parse_analisis_final_xlsx(f)
        mp_loaded = int(stats.get('mp_loaded', 0))
        ept_loaded = int(stats.get('ept_loaded', 0))
        archivo = mp_loaded + ept_loaded
        result['archivo_skus'] = archivo
        result['mp_loaded'] = mp_loaded
        result['ept_loaded'] = ept_loaded
        result['coincide'] = (archivo == modelo_skus)
    except Exception as e:
        result['error'] = f'Error leyendo el archivo: {str(e)}'
    return result

def _af_norm(np_val, lote_val):
    """Normaliza NP y LOTE para comparativas Query vs Modelo."""
    np_norm = str(np_val or '').strip().upper()
    lote = str(lote_val or '').strip().upper()
    if not lote or lote.lower() in ('nan', 'none', 'null', '-', 'n/a'):
        lote = ''
    if lote:
        lote = lote.lstrip('0') or '0'
    return np_norm, lote

def _af_query_audit(rows):
    """Ejecuta el Query Auditoría 1 (config query_auditoria_1) contra Odoo, que devuelve
    triplas (NP, UBICACION, LOTE), y lo compara contra las filas del modelo Análisis Final
    por NP + ubicación, listando qué lotes faltan en cada dirección.
    Devuelve dict con 'resumen', 'grupos' (hallazgos) y 'error'."""
    import time
    result = {
        'resumen': {'query_rows': 0, 'modelo_rows': len(rows), 'coinciden': False,
                    'grupos': 0, 'con_faltantes': 0, 'tiempo_ms': 0, 'error': '',
                    'info_sin_lotes': 0, 'info_coinciden': 0},
        'grupos': [],
    }
    config = load_config()
    query = config.get('query_auditoria_1', '')
    if not query or not query.strip():
        result['resumen']['error'] = 'Query Auditoría 1 vacío. Guárdalo en Configuraciones.'
        return result

    init_db()
    db = DBManager(config)
    t0 = time.time()
    try:
        if '{NPs}' in query:
            from core.local_db import get_analisis_final_nps
            nps = get_analisis_final_nps()
            qrows = db.execute_query(query, nps) if nps else []
        else:
            qrows = db.execute_raw(query)
    except Exception as e:
        result['resumen']['error'] = f'Error ejecutando Query Auditoría 1: {str(e)}'
        return result
    elapsed_ms = int((time.time() - t0) * 1000)
    result['resumen']['tiempo_ms'] = elapsed_ms

    # Índice del Query por (NP, UBICACION) -> {lote: cantidad}
    query_np_ubi = defaultdict(dict)
    query_valid = 0
    for r in qrows:
        np_norm, lote = _af_norm(r.get('NP'), r.get('LOTE'))
        ubicacion = str(r.get('UBICACION') or '').strip()
        if not np_norm or not lote or not ubicacion:
            continue
        try:
            cantidad = float(r.get('CANTIDAD') or r.get('QTY') or 0)
        except (TypeError, ValueError):
            cantidad = 0.0
        query_np_ubi[(np_norm, ubicacion)][lote] = cantidad
        query_valid += 1
    result['resumen']['query_rows'] = query_valid

    # Índice del Modelo por (NP, ubicacion) -> set de lotes
    model_np_ubi = defaultdict(set)
    model_valid = 0
    for r in rows:
        np_norm, lote = _af_norm(r.get('np'), r.get('lote'))
        ubicacion = str(r.get('almacen') or '').strip()
        if not np_norm or not ubicacion:
            continue
        if lote:
            model_np_ubi[(np_norm, ubicacion)].add(lote)
            model_valid += 1
    # También indexar NPs por ubicación aunque no tengan lote (para saber si el NP+ubicación existe)
    np_ubi_existe = set()
    for r in rows:
        np_norm, _ = _af_norm(r.get('np'), r.get('lote'))
        ubicacion = str(r.get('almacen') or '').strip()
        if np_norm and ubicacion:
            np_ubi_existe.add((np_norm, ubicacion))
    result['resumen']['modelo_con_lote'] = model_valid

    _BLOQUE_POR_ALMACEN = {
        'Physical Locations/AMP/Stock/B&A': 'B&A',
        'Physical Locations/AMP/Stock/EPTs': 'EPT',
        'Physical Locations/AMP/Stock/Insumos': 'Insumos',
        'Physical Locations/AMP/Stock/Prop. Cte.': 'Prop. Cliente',
    }

    def bloque_of(ubi):
        return _BLOQUE_POR_ALMACEN.get(ubi, ubi or '(sin ubicación)')

    # Unir todas las claves (NP, ubicación) presentes en Query o Modelo
    all_keys = set(query_np_ubi.keys()) | set(model_np_ubi.keys()) | set(np_ubi_existe)
    grupos = []
    for (np_norm, ubicacion) in sorted(all_keys):
        q_lotes = set(query_np_ubi.get((np_norm, ubicacion), {}).keys())
        m_lotes = model_np_ubi.get((np_norm, ubicacion), set())
        faltan_en_modelo = sorted(q_lotes - m_lotes)
        faltan_en_query = sorted(m_lotes - q_lotes)
        bloque = bloque_of(ubicacion)
        coincide = (set(q_lotes) == set(m_lotes))
        # Totales del modelo para el NP+ubicación
        model_rows_npu = [r for r in rows
                          if _af_norm(r.get('np'), r.get('lote'))[0] == np_norm
                          and str(r.get('almacen') or '').strip() == ubicacion]
        qty_odoo = sum(float(r.get('qty_odoo') or 0) for r in model_rows_npu)
        qty_conteo = sum(float(r.get('qty_conteo') or 0) for r in model_rows_npu)
        fkey = f"Q1::{bloque}::{np_norm}::{ubicacion}"

        # Info para la acción "Agregar al modelo" (FASE 1)
        # Regla por LOTE: un lote del Query que no tiene línea en el modelo (o esa
        # línea no tiene conteo) se agrega copiando info del modelo. Aplica SOLO a
        # B&A, Insumos y Prop. Cliente; EPTs es únicamente auditoría (warning) y
        # nunca se agrega nada al modelo en esa ubicación.
        faltan_en_modelo_qty = [{'lote': l, 'qty': query_np_ubi[(np_norm, ubicacion)].get(l),
                                 'linea_modelo': None, 'conteo_lote': 0.0}
                                for l in faltan_en_modelo]
        modelo_qty_conteo = qty_conteo
        puede_agregar = bool(faltan_en_modelo) and bloque in ('B&A', 'Insumos', 'Prop. Cliente')

        # EPTs: los hallazgos de lotes en ubicación EPT se marcan como WARNING (auditoría
        # informativa), no como crítico: al cargar las existencias bajan a 0 y se sube
        # todo nuevo, por lo que el modelo puede traer lotes que el Query aún no reporta
        # (y viceversa). Aplica SOLO a la auditoría; EPTs nunca se agregan al modelo.
        es_ept = (bloque == 'EPT')
        if q_lotes and not m_lotes:
            if es_ept:
                sev = 'warning'
                tipo = 'NP en Query sin cargar (EPTs)'
                mensaje = (f'El Query reporta {len(q_lotes)} lote(s) para {np_norm} en {ubicacion} '
                           f'que no están en Análisis Final: {", ".join(faltan_en_modelo)}. '
                           'EPTs: al cargar existencias bajan a 0 y se sube todo nuevo, por lo que '
                           'queda como pendiente de agregar al modelo (WARNING).')
            else:
                sev = 'critical'
                tipo = 'Lotes en Query faltan en Modelo'
                mensaje = (f'El Query reporta {len(q_lotes)} lote(s) para {np_norm} en {ubicacion} '
                           f'que NO están en Análisis Final: {", ".join(faltan_en_modelo)}.')
        elif faltan_en_modelo:
            if es_ept:
                sev = 'warning'
                tipo = 'NP en Query sin cargar (EPTs)'
                mensaje = (f'Faltan {len(faltan_en_modelo)} lote(s) del Query en Análisis Final para '
                           f'{np_norm} ({ubicacion}): {", ".join(faltan_en_modelo)}. '
                           'EPTs: al cargar existencias bajan a 0 y se sube todo nuevo, por lo que '
                           'queda como pendiente de agregar al modelo (WARNING).')
            else:
                sev = 'critical'
                tipo = 'Lotes en Query faltan en Modelo'
                mensaje = (f'Faltan {len(faltan_en_modelo)} lote(s) del Query en Análisis Final para '
                           f'{np_norm} ({ubicacion}): {", ".join(faltan_en_modelo)}.')
        elif faltan_en_query:
            if es_ept:
                sev = 'warning'
                tipo = 'Modelo tiene más lotes que el Query (EPTs)'
                mensaje = (f'{len(faltan_en_query)} lote(s) de Análisis Final no aparecen en el Query '
                           f'para {np_norm} ({ubicacion}): {", ".join(faltan_en_query)}. '
                           'EPTs: al cargar existencias bajan a 0 y se sube todo nuevo, por lo que '
                           'el modelo puede traer lotes que el Query aún no reporta (WARNING).')
            else:
                sev = 'critical'
                tipo = 'Lotes del Modelo no están en Query'
                mensaje = (f'{len(faltan_en_query)} lote(s) de Análisis Final no aparecen en el Query '
                           f'para {np_norm} ({ubicacion}): {", ".join(faltan_en_query)}.')
        elif coincide and m_lotes:
            sev = 'info'
            tipo = 'Lotes coinciden 1:1'
            mensaje = f'Los {len(m_lotes)} lote(s) coinciden entre Query y Análisis Final para {np_norm} ({ubicacion}).'
        else:
            # NP+ubicación sin lotes en ninguna parte: info de presencia
            if (np_norm, ubicacion) in query_np_ubi or (np_norm, ubicacion) in model_np_ubi or (np_norm, ubicacion) in np_ubi_existe:
                sev = 'info'
                tipo = 'Sin lotes en ambas fuentes'
                mensaje = f'{np_norm} existe en {ubicacion} pero sin lotes registrados (Query ni Modelo).'
            else:
                continue

        grupos.append({
            'sev': sev, 'tipo': tipo, 'fkey': fkey,
            'bloque': bloque, 'np': np_norm,
            'ubicacion': ubicacion,
            'qty_odoo': qty_odoo, 'qty_conteo': qty_conteo,
            'lotes_query': sorted(q_lotes), 'lotes_modelo': sorted(m_lotes),
            'faltan_en_modelo': faltan_en_modelo, 'faltan_en_query': faltan_en_query,
            'faltan_en_modelo_qty': faltan_en_modelo_qty,
            'modelo_qty_conteo': modelo_qty_conteo,
            'puede_agregar': bool(puede_agregar),
            'coincide': coincide,
            'es_hallazgo': sev in ('critical', 'warning'),
            'mensaje': mensaje,
        })

    result['grupos'] = grupos
    result['resumen']['grupos'] = len(grupos)
    result['resumen']['con_faltantes'] = sum(1 for g in grupos if g['sev'] in ('critical', 'warning'))
    result['resumen']['faltan_en_modelo'] = sum(len(g.get('faltan_en_modelo', [])) for g in grupos)
    result['resumen']['faltan_en_query'] = sum(len(g.get('faltan_en_query', [])) for g in grupos)
    result['resumen']['info_sin_lotes'] = sum(1 for g in grupos if g['tipo'] == 'Sin lotes en ambas fuentes')
    result['resumen']['info_coinciden'] = sum(1 for g in grupos if g['tipo'] == 'Lotes coinciden 1:1')
    result['resumen']['hallazgos'] = sum(1 for g in grupos if g['es_hallazgo'])
    result['resumen']['coinciden'] = result['resumen']['con_faltantes'] == 0
    return result
    """Relee el archivo INVENTARIO MP 2026.xlsx y compara el total de SKU cargables
    (MP cargadas + EPT cargadas, contemplando la fila corregida NPMANDEL1) contra las
    filas actuales del modelo. Devuelve dict con conteos y si coinciden."""
    result = {
        'archivo_skus': None, 'modelo_skus': modelo_skus,
        'mp_loaded': 0, 'ept_loaded': 0, 'coincide': None, 'error': '',
    }
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        'analisisfinal', 'INVENTARIO MP 2026.xlsx')
    if not os.path.exists(path):
        result['error'] = f"No se encontró el archivo de inventario en {path}"
        return result
    try:
        with open(path, 'rb') as f:
            records, stats = _parse_analisis_final_xlsx(f)
        mp_loaded = int(stats.get('mp_loaded', 0))
        ept_loaded = int(stats.get('ept_loaded', 0))
        archivo = mp_loaded + ept_loaded
        result['archivo_skus'] = archivo
        result['mp_loaded'] = mp_loaded
        result['ept_loaded'] = ept_loaded
        result['coincide'] = (archivo == modelo_skus)
    except Exception as e:
        result['error'] = f'Error leyendo el archivo: {str(e)}'
    return result

@app.route('/api/analisis_final/audit')
def api_analisis_final_audit():
    from core.local_db import init_db, get_analisis_final_audit_states, save_analisis_final_audit_state
    init_db()
    audit = _af_audit()
    # Corrección directa de marías EPT: filas con lote 'nan' (ej. MESC) → se dejan
    # en blanco en BD y el hallazgo LOTE_NAN::EPT queda auto-registrado corregido.
    nan_nps = [f.get('np') for f in audit.get('findings', []) if f.get('tipo') == "Lote 'nan' (maría)"]
    if nan_nps:
        from core.local_db import clear_analisis_final_nan_lotes
        res = clear_analisis_final_nan_lotes('EPT')
        if res.get('updated'):
            log_module_action('analisis_final', request.path,
                              f"nan_lote(EpT) -> se vaciaron {res['updated']} lote(s): {', '.join(res['nps'])}")
        for np_val in nan_nps:
            save_analisis_final_audit_state(
                f"LOTE_NAN::EPT::{np_val}", 'corregido',
                "Lote 'nan' corregido directo (maría tipo MESC): se dejó en blanco en el modelo (BD).")
    states = get_analisis_final_audit_states()
    for f in audit.get('findings', []):
        st = states.get(f.get('fkey'))
        f['estado'] = (st or {}).get('estado', '')
        f['nota'] = (st or {}).get('nota', '')
    # Enriquecer también los grupos del bloque Query Auditoría 1
    # Regla EPTs: "Modelo tiene más lotes que el Query" es solo auditoría informativa
    # (no crítico) y se da por corregido con nota; se persiste en el estado.
    # Optimización PG: solo se abre conexión y escribe si el estado guardado difiere,
    # evita ~1 conexión+commit por grupo (~600 ms c/u en PG remoto).
    for g in audit.get('summary', {}).get('query_auditoria', {}).get('grupos', []):
        st = states.get(g.get('fkey'))
        g['estado'] = (st or {}).get('estado', '')
        g['nota'] = (st or {}).get('nota', '')
        if g.get('tipo') == 'Modelo tiene más lotes que el Query (EPTs)':
            if (st or {}).get('estado') != 'corregido' or (st or {}).get('nota') != 'Se va a agregar al modelo no hay tema':
                g['estado'] = 'corregido'
                g['nota'] = 'Se va a agregar al modelo no hay tema'
                save_analisis_final_audit_state(g.get('fkey'), 'corregido',
                                                'Se va a agregar al modelo no hay tema')
    return jsonify(audit)

@app.route('/api/analisis_final/audit/detail')
def api_analisis_final_audit_detail():
    """Devuelve las filas del modelo del Análisis Final agrupadas por bloque para un hallazgo.
    Requiere 'np' (y opcionalmente 'fkey'/'bloque'). Se usa para el popup de revisión."""
    from core.local_db import get_analisis_final
    init_db()
    np_val = request.args.get('np', '')
    rows = get_analisis_final()

    def norm(s):
        return str(s or '').strip()

    if np_val:
        target = norm(np_val)
        # NP_MULTI y el resto usan el NP; si es la fila CRITICAL con np='nan', usamos bloque
        if target.lower() in ('nan', 'none', ''):
            bloque = request.args.get('bloque', '')
            matched = [r for r in rows if str(r.get('bloque') or '').strip() == bloque and
                       norm(r.get('np')).lower() in ('nan', 'none', '')]
        else:
            matched = [r for r in rows if norm(r.get('np')) == target]
    else:
        matched = rows

    by_block = {}
    for r in matched:
        b = r.get('bloque') or '(sin bloque)'
        by_block.setdefault(b, []).append(r)
    blocks = []
    for b, items in by_block.items():
        blocks.append({
            'bloque': b,
            'count': len(items),
            'total_odoo': sum(float(x.get('qty_odoo') or 0) for x in items),
            'total_conteo': sum(float(x.get('qty_conteo') or 0) for x in items),
            'filas': [{
                'id': x.get('id'), 'np': x.get('np'), 'descripcion': x.get('descripcion'),
                'unidad': x.get('unidad'), 'lote': x.get('lote'),
                'qty_odoo': x.get('qty_odoo'), 'qty_conteo': x.get('qty_conteo'),
            } for x in items],
        })
    return jsonify({'np': np_val, 'blocks': blocks})

@app.route('/api/analisis_final/audit/state', methods=['POST'])
def api_analisis_final_audit_state():
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    from core.local_db import save_analisis_final_audit_state
    payload = request.get_json(silent=True) or {}
    fkey = str(payload.get('fkey', '')).strip()
    estado = str(payload.get('estado', '')).strip()
    nota = str(payload.get('nota', '')).strip()
    if not fkey:
        return jsonify({'success': False, 'msg': 'Falta la clave del hallazgo.'})
    if estado not in ('corregido', 'anotado'):
        return jsonify({'success': False, 'msg': 'Estado inválido (debe ser corregido o anotado).'})
    ok = save_analisis_final_audit_state(fkey, estado, nota)
    log_module_action('analisis_final', request.path, f"audit_state -> {fkey} | {estado}" + (f" | nota: {nota}" if nota else ""))
    return jsonify({'success': ok, 'msg': 'Estado guardado correctamente.' if ok else 'No se pudo guardar el estado.'})

@app.route('/api/analisis_final/audit/add_lotes', methods=['POST'])
def api_analisis_final_audit_add_lotes():
    """Agrega al modelo Análisis Final los lotes del Query Auditoría 1 que faltan,
    según la regla FASE 1: lote presente en el Query y ausente en el modelo, en
    bloques B&A/Insumos/Prop. Cliente (no EPTs), y con qty_conteo total = 0 en el
    modelo (si hay conteo se interpreta como baja confirmada y no se agrega).
    Copia toda la info de una fila del NP y solo lote + cantidad del Query."""
    if _module_payload('analisis_final') is None:
        return _module_denied('analisis_final')
    from core.local_db import (init_db, get_analisis_final,
                               add_analisis_final_lotes,
                               save_analisis_final_audit_state,
                               get_analisis_final_audit_states)
    init_db()
    payload = request.get_json(silent=True) or {}
    fkeys = [str(x).strip() for x in (payload.get('fkeys') or [])]
    if not fkeys:
        return jsonify({'success': False, 'msg': 'No se recibieron claves de hallazgo (fkeys).'})

    # Correr la auditoría completa para resolver los grupos con datos frescos del Query
    audit = _af_audit()
    groups = audit.get('summary', {}).get('query_auditoria', {}).get('grupos', [])
    by_fkey = {}
    for g in groups:
        by_fkey[g.get('fkey')] = g

    results = {}
    total_added = 0
    for fkey in fkeys:
        g = by_fkey.get(fkey)
        if not g:
            results[fkey] = {'ok': False, 'msg': 'Hallazgo no encontrado en la auditoría.'}
            continue
        faltantes = g.get('faltan_en_modelo') or []
        if not faltantes:
            results[fkey] = {'ok': False, 'msg': 'Ya no faltan lotes en el modelo para este hallazgo.'}
            continue
        if g.get('bloque') not in ('B&A', 'Insumos', 'Prop. Cliente'):
            results[fkey] = {'ok': False, 'msg': 'EPTs no aplica para agregar: solo auditoría informativa, no se agrega nada al modelo en esa ubicación.'}
            continue
        # Regla por LOTE: si ese lote no tiene línea en el modelo (o no tiene conteo)
        # se agrega. Datos de una fila existente del NP si hay (mismo NP + ubicación).
        base_rows = [r for r in get_analisis_final()
                     if _af_norm(r.get('np'), r.get('lote'))[0] == g.get('np')
                     and str(r.get('almacen') or '').strip() == g.get('ubicacion')]
        base = base_rows[0] if base_rows else {}

        qty_map = {item['lote']: item.get('qty') for item in (g.get('faltan_en_modelo_qty') or [])}
        records = []
        for lote in faltantes:
            records.append({
                'np': g.get('np'),
                'descripcion': base.get('descripcion', ''),
                'bloque': g.get('bloque'),
                'unidad': base.get('unidad', ''),
                'lote': lote,
                'qty_odoo': qty_map.get(lote) or 0,
                'empaque': base.get('empaque', ''),
                'almacen': g.get('ubicacion'),
                'procedencia': base.get('procedencia', ''),
                'sheet': base.get('sheet', ''),
            })
        ok, msg, added, detalle = add_analisis_final_lotes(records)
        if ok and added > 0:
            total_added += added
            nota = f"{added} lote(s) agregados al modelo desde Query Auditoría 1: {', '.join(d['lote'] for d in detalle)}"
            save_analisis_final_audit_state(fkey, 'corregido', nota)
            log_module_action('analisis_final', request.path, f"add_lotes -> {fkey} | {nota}")
        results[fkey] = {'ok': ok, 'added': added, 'msg': msg, 'detalle': detalle}

    # Recalcular la auditoría completa y devolverla para re-render en un solo round-trip
    audit = _af_audit()
    states = get_analisis_final_audit_states()
    for f in audit.get('findings', []):
        st = states.get(f.get('fkey'))
        f['estado'] = (st or {}).get('estado', '')
        f['nota'] = (st or {}).get('nota', '')
    for g in audit.get('summary', {}).get('query_auditoria', {}).get('grupos', []):
        st = states.get(g.get('fkey'))
        g['estado'] = (st or {}).get('estado', '')
        g['nota'] = (st or {}).get('nota', '')
    return jsonify({'success': True, 'total_added': total_added, 'results': results, 'audit': audit})

@app.route('/auditoria_folios')
def auditoria_folios_view():
    from core.local_db import init_db
    init_db()
    return render_template('auditoria_folios.html')

@app.route('/api/auditoria/data')
def api_auditoria_data():
    from core.local_db import get_pool_deleted, get_lost_folios
    return jsonify({'deleted': get_pool_deleted(), 'lost': get_lost_folios()})

@app.route('/api/auditoria/reconstruct', methods=['POST'])
def api_auditoria_reconstruct():
    """Escanea los PDFs físicos y reconstruye en la Papelera los folios faltantes.
    SOLO LECTURA sobre pool_final: nunca lo modifica (salvo restauración explícita)."""
    if _module_payload('auditoria') is None:
        return _module_denied('auditoria')
    from core.local_db import reconstruct_deleted_from_pdfs
    success, msg = reconstruct_deleted_from_pdfs()
    if success:
        log_module_action('auditoria', request.path, f"reconstruct -> {msg}")
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/auditoria/update', methods=['POST'])
def api_auditoria_update():
    if _module_payload('auditoria') is None:
        return _module_denied('auditoria')
    from core.local_db import update_pool_deleted_records
    records = request.get_json(silent=True).get('records', [])
    if not records:
        return jsonify({'success': False, 'msg': 'No se recibieron registros.'})
    success, msg = update_pool_deleted_records(records)
    log_module_action('auditoria', request.path, f"update -> {msg}")
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/auditoria/restore', methods=['POST'])
def api_auditoria_restore():
    """Restaura registros de la Papelera de vuelta al Pool Final (conserva su folio)."""
    if _module_payload('auditoria') is None:
        return _module_denied('auditoria')
    from core.local_db import restore_from_deleted
    folios = request.get_json(silent=True).get('folios', [])
    if not folios:
        return jsonify({'success': False, 'msg': 'No se enviaron folios para restaurar.'})
    success, msg = restore_from_deleted(folios)
    if success:
        log_module_action('auditoria', request.path, f"restore -> {msg}")
    return jsonify({'success': success, 'msg': msg})

def _do_transfer_to_pool(module):
    """Lógica compartida de traspaso de un módulo hacia Pool Final.
    Genera marbetes NUEVOS con folios consecutivos (conservación del último folio)
    y cierra los marbetes en pool_final. Cada registro origen se marca con su folio."""
    if _module_payload(module) is None:
        return _module_denied(module)
    table = MODULE_TRANSFER_TABLE.get(module)
    if not table:
        return _module_denied(module)
    success, msg = transfer_module_to_pool(table)
    if success:
        log_module_action(module, request.path, f"transfer_to_pool -> {msg}")
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/wms/transfer', methods=['POST'])
def api_wms_transfer():
    return _do_transfer_to_pool('wms')

@app.route('/api/saldos/transfer', methods=['POST'])
def api_saldos_transfer():
    return _do_transfer_to_pool('saldos')

@app.route('/api/etqmang/transfer', methods=['POST'])
def api_etqmang_transfer():
    return _do_transfer_to_pool('etqmang')

@app.route('/api/pool/mark_audit', methods=['POST'])
def api_pool_mark_audit():
    from core.local_db import mark_audit_all
    updated = mark_audit_all()
    return jsonify({'success': True, 'updated': updated})

@app.route('/api/pool/create_backup', methods=['POST'])
def api_pool_create_backup():
    from core.local_db import create_pool_backup
    success, msg = create_pool_backup()
    return jsonify({'success': success, 'msg': msg})

@app.route('/api/config/db', methods=['POST'])
def save_db_config():
    data = request.json
    config = load_config()
    config['db'] = data
    db = DBManager(config)
    success, error = db.test_connection()
    if success:
        save_config(config)
        return jsonify({'success': True})
    return jsonify({'success': False, 'error': error})

@app.route('/api/config/query', methods=['POST'])
def save_query():
    config = load_config()
    config['query'] = request.json.get('query', '')
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/config/existencias', methods=['POST'])
def save_existencias_query():
    config = load_config()
    config['query_existencias'] = request.json.get('query', '')
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/config/query_pool', methods=['POST'])
def save_pool_query():
    config = load_config()
    config['query_pool'] = request.json.get('query', '')
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/config/query_epts', methods=['POST'])
def save_epts_query():
    config = load_config()
    config['query_epts'] = request.json.get('query', '')
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/config/query_auditoria', methods=['POST'])
def save_auditoria_query():
    config = load_config()
    config['query_auditoria_1'] = request.json.get('query', '')
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/config/mapping', methods=['POST'])
def save_mapping():
    config = load_config()
    config['data_mapping'] = request.json
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/config/coords', methods=['POST'])
def save_coords():
    config = load_config()
    config['pdf_coords'] = request.json
    save_config(config)
    return jsonify({'success': True})

# ============ CONFIGURACIÓN PT (Producto Terminado) ============

_PT_QUERY_KEYS = {
    'cedis1_odoo', 'cedis2_odoo', 'cedis3_odoo', 'cedis4_odoo',
    'nave6_odoo', 'wms1', 'wms2', 'wms3', 'wms4', 'actualizacion_datos',
    'actualizacion_directa_wms1', 'wms1_info_ubicacion_rack', 'vaciar_ubicacion_wms1'
}

@app.route('/api/config/pt_query', methods=['POST'])
def save_pt_query():
    """Guarda un query de PT bajo config.pt_queries.<key> y lo prueba contra
    su base de datos (PostgreSQL para Odoo, MySQL para WMS)."""
    data = request.get_json(silent=True) or {}
    key = str(data.get('key', '')).strip()
    query = str(data.get('query', '')).strip()
    if key not in _PT_QUERY_KEYS:
        return jsonify({'success': False, 'error': 'Origen de query PT inválido.'})

    config = load_config()
    pt_queries = config.setdefault('pt_queries', {})

    # Los queries de validación de estructura/escritura solo se guardan si pasan
    # la validación (no se permite persistir un query que no cumple).
    if pt_queries.get(key, {}).get('validacion') in ('estructura', 'escritura'):
        result = _test_pt_query(config, key, query)
        if not result.get('success'):
            return jsonify({'success': True, 'saved': False, 'test': result, 'key': key})
        if key not in pt_queries:
            pt_queries[key] = {'tipo': 'wms', 'etiqueta': key, 'query': ''}
        pt_queries[key]['query'] = query
        save_config(config)
        return jsonify({'success': True, 'saved': True, 'test': result, 'key': key})

    if key not in pt_queries:
        tipo = 'wms' if key.startswith('wms') else 'odoo'
        pt_queries[key] = {'tipo': tipo, 'etiqueta': key, 'query': ''}
    pt_queries[key]['query'] = query
    save_config(config)

    result = _test_pt_query(config, key, query)
    return jsonify({
        'success': True,
        'saved': True,
        'test': result,
        'key': key,
    })

@app.route('/api/config/pt_test', methods=['POST'])
def test_pt_query():
    """Prueba un query de PT sin guardarlo (usa el texto enviado)."""
    data = request.get_json(silent=True) or {}
    key = str(data.get('key', '')).strip()
    query = str(data.get('query', '')).strip()
    if key not in _PT_QUERY_KEYS:
        return jsonify({'success': False, 'error': 'Origen de query PT inválido.'})

    config = load_config()
    result = _test_pt_query(config, key, query)
    result['saved'] = False
    return jsonify(result)

def _test_pt_query(config, key, query):
    """Ejecuta un query PT contra su origen y devuelve el detalle del resultado.
    Si el query está marcado como 'es_update', solo realiza validación de estructura."""
    import time
    if not query or not query.strip():
        return {'success': False, 'error': 'El query está vacío.'}

    pt_queries = config.get('pt_queries', {})
    is_update = pt_queries.get(key, {}).get('es_update', False)

    if is_update:
        # Validación básica de estructura para UPDATE
        import re
        q_upper = query.upper()
        if not q_upper.strip().startswith('UPDATE'):
            return {'success': False, 'error': "El query debe iniciar con la palabra UPDATE."}
        if not re.search(r'\bSET\b', q_upper):
            return {'success': False, 'error': "El query debe contener la palabra SET."}
        if not re.search(r'\bWHERE\b', q_upper):
            return {'success': False, 'error': "El query debe contener la palabra WHERE."}
        if '{NUEVA_CANTIDAD}' not in query:
            return {'success': False, 'error': "El query debe contener el placeholder {NUEVA_CANTIDAD}."}
        if '{ID_LOTE}' not in query:
            return {'success': False, 'error': "El query debe contener el placeholder {ID_LOTE}."}
            
        return {
            'success': True,
            'is_update': True,
            'filas': 0,
            'tiempo_ms': 0,
            'columnas': [],
            'preview': []
        }

    # Validación de estructura sin ejecutar contra la BD (queries marcados
    # con 'validacion': 'estructura' en la configuración).
    config_q = pt_queries.get(key, {})
    if config_q.get('validacion') == 'estructura':
        q_upper = query.upper()
        if not q_upper.strip().startswith('SELECT'):
            return {'success': False, 'error': "El query debe iniciar con la palabra SELECT."}
        if 'FROM' not in q_upper:
            return {'success': False, 'error': "El query debe contener la palabra FROM."}
        if 'WHERE' not in q_upper:
            return {'success': False, 'error': "El query debe contener la palabra WHERE."}
        for ph in config_q.get('placeholders', []):
            if ph not in query:
                return {'success': False, 'error': f"El query debe contener el placeholder {ph}."}
        return {
            'success': True,
            'is_update': False,
            'solo_validacion': True,
            'filas': 0,
            'tiempo_ms': 0,
            'columnas': [],
            'preview': []
        }

    # Validación de escritura (DELETE) sin ejecutar contra la BD (queries
    # marcados con 'validacion': 'escritura').
    if config_q.get('validacion') == 'escritura':
        q_upper = query.upper()
        if not q_upper.strip().startswith('DELETE'):
            return {'success': False, 'error': "El query debe iniciar con la palabra DELETE."}
        if 'FROM' not in q_upper:
            return {'success': False, 'error': "El query debe contener la palabra FROM."}
        if 'WHERE' not in q_upper:
            return {'success': False, 'error': "El query debe contener la palabra WHERE."}
        for ph in config_q.get('placeholders', []):
            if ph not in query:
                return {'success': False, 'error': f"El query debe contener el placeholder {ph}."}
        return {
            'success': True,
            'is_update': False,
            'solo_validacion': True,
            'filas': 0,
            'tiempo_ms': 0,
            'columnas': [],
            'preview': []
        }

    # Inyectar un valor de prueba (P12278) si el query contiene los placeholders {NP} o {NPs}
    test_query = query.replace("{NPs}", "'P12278'").replace("{NP}", "'P12278'")

    tipo = 'wms' if key.startswith('wms') else 'odoo'
    t0 = time.time()
    try:
        if tipo == 'wms':
            from core.db_manager import DBManagerMySQL
            conexion_key = pt_queries.get(key, {}).get('conexion', key)
            pt_wms = config.get('pt_wms', {}).get(conexion_key)
            if not pt_wms:
                return {'success': False, 'error': f'No hay credenciales WMS configuradas para este origen ({conexion_key}).'}
            db = DBManagerMySQL(pt_wms)
            rows = db.execute_raw(test_query)
        else:
            from core.db_manager import DBManager
            db = DBManager(config)
            rows = db.execute_raw(test_query)
    except Exception as e:
        elapsed_ms = int((time.time() - t0) * 1000)
        return {'success': False, 'error': str(e), 'tiempo_ms': elapsed_ms}

    elapsed_ms = int((time.time() - t0) * 1000)
    preview = []
    for r in (rows or [])[:3]:
        row_view = {}
        for kk, vv in (r or {}).items():
            row_view[str(kk)] = '' if vv is None else str(vv)
        preview.append(row_view)
    return {
        'success': True,
        'filas': len(rows or []),
        'tiempo_ms': elapsed_ms,
        'columnas': list((rows[0].keys() if rows else [])),
        'preview': preview,
    }

@app.route('/api/config/pt_wms', methods=['POST'])
def save_pt_wms():
    """Guarda las credenciales de conexiones WMS (MySQL) de PT."""
    data = request.get_json(silent=True) or {}
    wms_data = data.get('wms', {})
    if not isinstance(wms_data, dict) or not wms_data:
        return jsonify({'success': False, 'error': 'Datos WMS inválidos.'})

    config = load_config()
    pt_wms = config.setdefault('pt_wms', {})
    for key, vals in wms_data.items():
        if key not in _PT_QUERY_KEYS or not key.startswith('wms'):
            continue
        if not isinstance(vals, dict):
            continue
        base = pt_wms.get(key, {})
        etiqueta = base.get('etiqueta', key)
        pt_wms[key] = {
            'etiqueta': etiqueta,
            'host': str(vals.get('host', base.get('host', ''))),
            'port': vals.get('port', base.get('port', '3306')),
            'database': str(vals.get('database', base.get('database', ''))),
            'user': str(vals.get('user', base.get('user', ''))),
            'password': str(vals.get('password', base.get('password', ''))),
        }
    save_config(config)
    return jsonify({'success': True, 'msg': 'Conexiones WMS guardadas.'})

@app.route('/api/config/pt_wms_test', methods=['POST'])
def test_pt_wms():
    """Prueba las conexiones WMS guardadas (sin guardar cambios del form)."""
    data = request.get_json(silent=True) or {}
    wms_data = data.get('wms', {})
    config = load_config()
    pt_wms = config.setdefault('pt_wms', {})
    from core.db_manager import DBManagerMySQL

    results = {}
    for key, base in pt_wms.items():
        if not key.startswith('wms'):
            continue
        vals = wms_data.get(key, {})
        creds = {
            'host': str(vals.get('host', base.get('host', ''))),
            'port': vals.get('port', base.get('port', '3306')),
            'database': str(vals.get('database', base.get('database', ''))),
            'user': str(vals.get('user', base.get('user', ''))),
            'password': str(vals.get('password', base.get('password', ''))),
        }
        ok, err = DBManagerMySQL(creds).test_connection()
        results[key] = {'success': ok, 'error': err}
    return jsonify({'success': True, 'results': results})

@app.route('/api/printers')
def list_printers():
    return jsonify({'printers': get_printers()})

@app.route('/api/config/printer', methods=['POST'])
def save_printer():
    config = load_config()
    config['printer'] = request.json
    save_config(config)
    return jsonify({'success': True})

@app.route('/api/print/dummy', methods=['POST'])
def print_dummy():
    config = load_config()
    printer_name = config['printer']['name']
    
    if not printer_name:
        return jsonify({'success': False, 'error': 'No printer configured'})
        
    sample_file = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_data.json')
    if not os.path.exists(sample_file):
        return jsonify({'success': False, 'error': 'Primero debes cargar un archivo y validar el query en el Módulo 2.'})
        
    import json
    with open(sample_file, 'r') as sf:
        dummy_marbetes = json.load(sf)
        
    if not dummy_marbetes:
        return jsonify({'success': False, 'error': 'No hay datos cruzados disponibles para imprimir.'})
        
    while len(dummy_marbetes) < 3:
        dummy_marbetes.append(dummy_marbetes[0])
    
    try:
        generate_pdf_batch(dummy_marbetes, 99999, config['pdf_coords'], app.config['PDF_FOLDER'], debug_mode=False)
        dummy_file = os.path.join(app.config['PDF_FOLDER'], '99999-100000-100001.pdf')
        print_pdf(printer_name, dummy_file)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/diff', methods=['POST'])
def run_diff():
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': 'No file uploaded'})
        
    file = request.files['file']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(file.filename))
    file.save(filepath)
    
    try:
        config = load_config()
        excel_nps = extract_unique_nps(filepath)
        db = DBManager(config)
        db_results = db.execute_query(config['query'], excel_nps)
        
        db_nps = []
        if db_results:
            key_to_use = None
            if 'default_code' in db_results[0]: key_to_use = 'default_code'
            elif 'clave' in db_results[0]: key_to_use = 'clave'
            elif 'clave_solicitada' in db_results[0]: key_to_use = 'clave_solicitada'
            else: key_to_use = list(db_results[0].keys())[0]
            db_nps = [str(r[key_to_use]).strip() for r in db_results]
        
        diff_data = []
        summary_by_sheet = {}
        raw_excel_marbetes = parse_excel_for_marbetes(filepath)
        for m in raw_excel_marbetes:
            np = m['np']
            sheet = m.get('sheet', 'unknown')
            in_db = np in db_nps
            diff_data.append({'np': np, 'sheet': sheet, 'in_db': in_db})
            if sheet not in summary_by_sheet:
                summary_by_sheet[sheet] = {'total': 0, 'ok': 0, 'fail': 0}
            summary_by_sheet[sheet]['total'] += 1
            if in_db: summary_by_sheet[sheet]['ok'] += 1
            else: summary_by_sheet[sheet]['fail'] += 1
            
        joined_marbetes = get_joined_marbetes(filepath, config)
        sample_file = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_data.json')
        import json
        with open(sample_file, 'w') as sf:
            json.dump(joined_marbetes[:3], sf)
            
        return jsonify({'success': True, 'diff': diff_data, 'summary': summary_by_sheet})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/preview/pdf', methods=['POST'])
def preview_pdf():
    config_coords = request.json
    sample_file = os.path.join(app.config['UPLOAD_FOLDER'], 'sample_data.json')
    if not os.path.exists(sample_file):
        return "Please upload Excel and validate Query first to enable preview.", 400
    import json
    with open(sample_file, 'r') as sf:
        dummy_marbetes = json.load(sf)
    if not dummy_marbetes:
        return "No matching data found between Excel and Database.", 400
    while len(dummy_marbetes) < 3:
        dummy_marbetes.append(dummy_marbetes[0])
        
    import io
    from flask import send_file
    buffer = io.BytesIO()
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.colors import black
    import datetime
    
    c = canvas.Canvas(buffer, pagesize=letter)
    global_row_offset_y = config_coords.get('global_row_offset_y', 272)
    base_y = config_coords.get('base_y', 98)
    adj_m1 = config_coords.get('ajuste_m1_y', 0)
    adj_m2 = config_coords.get('ajuste_m2_y', 0)
    adj_m3 = config_coords.get('ajuste_m3_y', 0)
    font_size = config_coords.get('font_size', 10)
    exact_y_positions = [base_y + adj_m1, base_y + global_row_offset_y + adj_m2, base_y + (global_row_offset_y * 2) + adj_m3]
    c1_x = config_coords.get('col1', {}).get('x', 30)
    c2_x = config_coords.get('col2', {}).get('x', 230)
    c3_x = c2_x + config_coords.get('col3', {}).get('x_offset_from_col2', 200)
    elements = config_coords.get('elements', {})
    current_date = datetime.datetime.now().strftime("%B %Y").upper()

    for i, marbete in enumerate(dummy_marbetes):
        current_y = exact_y_positions[i] if i < len(exact_y_positions) else exact_y_positions[-1]
        folio_str = str(i+1).zfill(5)
        np_str = marbete['np']
        almacen = marbete['almacen']
        
        c.saveState()
        c.translate(c1_x, current_y)
        c.rotate(90)
        c1_np_el = elements.get('col1_np', {})
        if c1_np_el.get('enabled', True):
            c.setFont("Helvetica-Bold", font_size + c1_np_el.get('font_size_add', 4))
            c.drawCentredString(c1_np_el.get('x_add', 100), c1_np_el.get('y_offset', 0), np_str)
        c1_fol_el = elements.get('col1_folio', {})
        if c1_fol_el.get('enabled', True):
            c.setFont("Helvetica-Bold", font_size + c1_fol_el.get('font_size_add', 4))
            c.drawCentredString(c1_fol_el.get('x_add', 100), c1_fol_el.get('y_offset', -20), folio_str)
        c.restoreState()

        def draw_conteo_block(x_offset, title, is_col3=False):
            def get_el(name): return elements.get(name, {})
            def set_font(is_bold=False, add_size=0):
                c.setFont("Helvetica-Bold" if is_bold else "Helvetica", font_size + add_size)
            c.setFillColor(black)
            def draw_el_text(key, text_val, is_bold=False, default_x=0, default_y=0, align='left'):
                el = get_el(key)
                if not el.get('enabled', True): return
                set_font(is_bold, el.get('font_size_add', 0))
                draw_x = x_offset + el.get('x_add', default_x)
                draw_y = current_y + el.get('y_offset', default_y)
                text_val_str = str(text_val) if text_val is not None else ""
                if align == 'center': c.drawCentredString(draw_x, draw_y, text_val_str)
                else: c.drawString(draw_x, draw_y, text_val_str)

            def draw_el_rect(key, default_x, default_y, default_w, default_h):
                el = get_el(key)
                if not el.get('enabled', True): return
                draw_x = x_offset + el.get('x_add', default_x)
                draw_y = current_y + el.get('y_offset', default_y)
                c.rect(draw_x, draw_y, el.get('w', default_w), el.get('h', default_h))

            draw_el_text('titulo', title, True, 0, 120)
            draw_el_text('fecha', f"{current_date}", False, 0, 105)
            draw_el_text('folio_horizontal', folio_str, True, 0, 95)
            draw_el_text('lbl_clave', "Clave:", False, 0, 85)
            draw_el_rect('rect_clave', 0, 65, 150, 18)
            draw_el_text('val_clave', np_str, False, 5, 70)
            draw_el_text('lbl_unidad', "Unidad:", False, 0, 45)
            draw_el_rect('rect_unidad', 40, 40, 40, 15)
            draw_el_text('val_unidad', marbete.get('unidad', ''), False, 60, 42, 'center')
            draw_el_text('lbl_empaque', "Empaque:", False, 90, 45)
            draw_el_rect('rect_empaque', 140, 40, 40, 15)
            draw_el_text('val_empaque', marbete.get('empaque', ''), False, 160, 42, 'center')
            draw_el_text('lbl_almacen', "Almacén:", False, 0, 20)
            draw_el_rect('rect_almacen', 0, 0, 150, 18)
            draw_el_text('val_almacen', almacen, False, 5, 5)
            draw_el_text('lbl_cantidad', "Cantidad:", False, 0, -15)
            draw_el_rect('rect_cantidad', 50, -20, 100, 15)
            draw_el_text('val_cantidad', marbete.get('cantidad', ''), False, 100, -18, 'center')
            draw_el_text('lbl_contado', "Contado por:", False, 0, -40)
            draw_el_rect('rect_contado', 65, -45, 85, 15)
            draw_el_text('val_contado', marbete.get('contado_por', ''), False, 107, -43, 'center')

        draw_conteo_block(c2_x, "SEGUNDO CONTEO")
        draw_conteo_block(c3_x, "PRIMER CONTEO", is_col3=True)
    c.save()
    buffer.seek(0)
    return send_file(buffer, mimetype='application/pdf', as_attachment=False, download_name='preview.pdf')

@app.route('/api/pdfs/status')
def pdfs_status():
    flujo = request.args.get('flujo', 'flujo1_excel')
    flujo_dir = os.path.join(app.config['PDF_FOLDER'], flujo)
    real_files = []
    transaction = ''
    if os.path.exists(flujo_dir):
        for name in os.listdir(flujo_dir):
            full = os.path.join(flujo_dir, name)
            if name.startswith('TX_') and os.path.isdir(full):
                transaction = name
                break
        for root, dirs, files in os.walk(flujo_dir):
            for f in files:
                if f.endswith('.pdf') and not f.startswith('99999'):
                    real_files.append(f)
    count = len(real_files)
    folios = sum([len(f.replace('.pdf', '').split('-')) for f in real_files])
    return jsonify({'count': count, 'folios_aprox': folios, 'transaction': transaction})

@app.route('/api/pdfs/purge', methods=['POST'])
def purge_pdfs():
    import shutil
    try:
        data = request.json or {}
        flujo = data.get('flujo', 'flujo1_excel')
        flujo_dir = os.path.join(app.config['PDF_FOLDER'], flujo)
        if os.path.exists(flujo_dir): shutil.rmtree(flujo_dir)
        os.makedirs(flujo_dir, exist_ok=True)
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/api/print/start', methods=['GET', 'POST'])
def print_start():
    config = load_config()
    printer_name = config['printer']['name']
    batch_size = config['printer']['batch_size']
    sleep_time = config['printer']['sleep_time']
    flujo = request.args.get('flujo', 'flujo1_excel')
    pdf_path = os.path.join(app.config['PDF_FOLDER'], flujo)
    return Response(print_batch_job(printer_name, pdf_path, batch_size, sleep_time), mimetype='text/event-stream')

@app.route('/api/execute/upload', methods=['POST'])
def execute_upload():
    if 'file' not in request.files: return jsonify({'success': False, 'error': 'No file uploaded'})
    file = request.files['file']
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'current_run.xlsx')
    file.save(filepath)
    return jsonify({'success': True})
    
@app.route('/api/execute/stream_ubicaciones')
def execute_stream_ubicaciones():
    def generate():
        import shutil
        from collections import Counter
        yield 'data: {"status": "info", "msg": "[INFO] Iniciando proceso (Query Existencias)..."}\n\n'
        try:
            config = load_config()
            query = config.get('query_existencias', '')
            if not query:
                yield 'data: {"status": "error", "msg": "[ERROR] El Query de Existencias está vacío en Configuraciones."}\n\n'
                return
                
            yield 'data: {"status": "info", "msg": "[INFO] Paso 1: Ejecutando Query a BD Odoo..."}\n\n'
            db = DBManager(config)
            conn = db.get_connection()
            from psycopg2.extras import DictCursor
            cur = conn.cursor(cursor_factory=DictCursor)
            cur.execute(query)
            db_results = [dict(r) for r in cur.fetchall()]
            cur.close()
            conn.close()
            
            if not db_results:
                yield 'data: {"status": "error", "msg": "[ERROR] El query no devolvió resultados."}\n\n'
                return
            
            yield 'data: {"status": "info", "msg": "[INFO] Paso 2: Analizando Ubicaciones e infiriendo datos..."}\n\n'
            joined = []
            
            def get_coincidencia(fila_db, posibles_nombres):
                import unicodedata
                def normalize(txt):
                    t = unicodedata.normalize('NFKD', str(txt)).encode('ASCII', 'ignore').decode('utf-8')
                    return t.lower().replace(' ', '').replace('_', '')
                lower_keys = {normalize(k): k for k in fila_db.keys()}
                for nombre in posibles_nombres:
                    norm_nombre = normalize(nombre)
                    if norm_nombre in lower_keys and fila_db[lower_keys[norm_nombre]]:
                        return str(fila_db[lower_keys[norm_nombre]]).strip()
                return ''
                
            def format_ubicacion(ubi_str):
                # Filtra la ubicacion para dejar solo la palabra clave solicitada
                keywords = ["Prop. Cte.", "Insumos", "EPTs", "B&A"]
                for kw in keywords:
                    if kw.lower() in ubi_str.lower():
                        return kw
                return ubi_str # Si no encuentra ninguna, deja la original

            for r in db_results:
                np_val = get_coincidencia(r, ['materiaprima', 'np', 'clave', 'defaultcode', 'productid', 'codigo'])
                ubi_val_crudo = get_coincidencia(r, ['ubicacioncompleta', 'ubicacion', 'almacen', 'locationid', 'locationdestid', 'name'])
                if not ubi_val_crudo:
                    ubi_val_crudo = 'SIN_UBICACION'
                
                # Sheet path and visual grouping can use original or formatted, but the user wants to reduce space in PDF
                # I will use the short name for BOTH the PDF printed text and the folder name for consistency.
                ubi_val = format_ubicacion(ubi_val_crudo)
                
                joined.append({

                    'np': np_val.upper(),
                    'clave': np_val.upper(),
                    'sheet': ubi_val, 
                    'ubicacion': ubi_val,
                    'descripcion': get_coincidencia(r, ['descripcion', 'name', 'productname', 'producttmplid']),
                    'unidad': get_coincidencia(r, ['unidad', 'uomid', 'productuom', 'uomname']),
                    'empaque': get_coincidencia(r, ['empaque', 'packagingid', 'packageid', 'tipo', 'type']),
                    'cantidad': '', 
                    'contado_por': '', 
                    'almacen': ubi_val,
                    'folio': ''
                })
                
            ubi_counts = Counter([m['ubicacion'] for m in joined])
            total = sum(ubi_counts.values())
            counts_str = ", ".join([f"{k}: {v}" for k, v in ubi_counts.items()])
            yield f'data: {{"status": "info", "msg": "[INFO] Total detectado: {total} existencias. | Por Ubicación: {counts_str}"}}\n\n'
            
            yield 'data: {"status": "info", "msg": "[INFO] Paso 3: Purgando PDFs anteriores (Flujo 2)..."}\n\n'
            flujo_dir = os.path.join(app.config['PDF_FOLDER'], 'flujo2_query')
            if os.path.exists(flujo_dir): shutil.rmtree(flujo_dir)
            os.makedirs(flujo_dir, exist_ok=True)
            
            yield 'data: {"status": "info", "msg": "[INFO] Generando PDFs por subcarpetas de Ubicación..."}\n\n'
            start_f = get_next_folio()
            pdfs_created = create_all_pdfs(joined, config['pdf_coords'], flujo_dir, start_folio=start_f, group_by_field='ubicacion')
            
            yield 'data: {"status": "info", "msg": "[INFO] Paso 4: Guardando Resultado en la Tabla Temporal..."}\n\n'
            init_db()
            insert_existencias(db_results)
            insert_cruce(joined)
            yield f'data: {{"status": "done", "msg": "[EXITO] Generación finalizada. {pdfs_created} PDFs listos en Flujo Ubicaciones."}}\n\n'
            
        except Exception as e:
            flujo_dir = os.path.join(app.config['PDF_FOLDER'], 'flujo2_query')
            if os.path.exists(flujo_dir):
                import shutil
                shutil.rmtree(flujo_dir)
                os.makedirs(flujo_dir, exist_ok=True)
            yield f'data: {{"status": "error", "msg": "[ERROR] Fallo crítico: {str(e)}."}}\n\n'
            
    return Response(generate(), mimetype='text/event-stream')


def load_config():
    import json
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)

def save_config(config_data):
    import json
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f, indent=2)


def get_joined_marbetes(filepath, config):
    excel_marbetes = parse_excel_for_marbetes(filepath)
    unique_nps = list(set([m['np'] for m in excel_marbetes]))
    
    db = DBManager(config)
    db_results = db.execute_query(config['query'], unique_nps)
    
    db_map = {}
    if db_results:
        key_to_use = None
        if 'default_code' in db_results[0]: key_to_use = 'default_code'
        elif 'clave' in db_results[0]: key_to_use = 'clave'
        elif 'clave_solicitada' in db_results[0]: key_to_use = 'clave_solicitada'
        else: key_to_use = list(db_results[0].keys())[0]
            
        for r in db_results:
            clave = str(r[key_to_use]).strip()
            db_map[clave] = r
            
    mapping = config.get('data_mapping', {})
    
    joined = []
    for em in excel_marbetes:
        np = em['np']
        if np in db_map:
            db_row = db_map[np]
            
            def get_val(field_name):
                source = mapping.get(field_name, 'db')
                if source == 'excel':
                    if field_name == 'clave': return em.get('np', '')
                    return em.get(field_name, '')
                elif source == 'db':
                    if field_name == 'clave': return str(db_row.get(key_to_use, np)).strip()
                    return db_row.get(field_name, '')
                return '' # sistema
                
            joined.append({
                'np': get_val('clave'),
                'clave': get_val('clave'),
                'sheet': em.get('sheet', ''),
                'descripcion': get_val('descripcion'),
                'unidad': get_val('unidad'),
                'empaque': get_val('empaque'),
                'cantidad': get_val('cantidad'),
                'contado_por': get_val('contado_por'),
                'almacen': get_val('almacen')
            })
    return joined



@app.route('/api/execute/stream')
def execute_stream():
    def generate():
        import shutil
        yield 'data: {"status": "info", "msg": "[INFO] Iniciando proceso de ejecución..."}\n\n'
        try:
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'current_run.xlsx')
            if not os.path.exists(filepath):
                yield 'data: {"status": "error", "msg": "[ERROR] No se encontró el archivo de Excel cargado."}\n\n'
                return
                
            config = load_config()
            
            # 1. Analyze
            yield 'data: {"status": "info", "msg": "[INFO] Paso 1: Analizando pestañas del Excel..."}\n\n'
            excel_marbetes = parse_excel_for_marbetes(filepath)
            if not excel_marbetes:
                yield 'data: {"status": "error", "msg": "[ERROR] No se detectaron materias primas marcadas en el Excel."}\n\n'
                return
                
            from collections import Counter
            sheet_counts = Counter([m['sheet'] for m in excel_marbetes])
            total = sum(sheet_counts.values())
            counts_str = ", ".join([f"{k}: {v}" for k, v in sheet_counts.items()])
            yield f'data: {{"status": "info", "msg": "[INFO] Total detectado: {total} marbetes. ({counts_str})"}}\n\n'
            
            # 2. Query
            yield 'data: {"status": "info", "msg": "[INFO] Paso 2: Ejecutando Query en Base de Datos..."}\n\n'
            unique_nps = list(set([m['np'] for m in excel_marbetes]))
            db = DBManager(config)
            db_results = db.execute_query(config['query'], unique_nps)
            
            db_map = {}
            if db_results:
                key_to_use = 'default_code' if 'default_code' in db_results[0] else ('clave' if 'clave' in db_results[0] else list(db_results[0].keys())[0])
                for r in db_results:
                    db_map[str(r[key_to_use]).strip()] = r
                    
            # 3. Compare Strict
            yield 'data: {"status": "info", "msg": "[INFO] Paso 3: Comparación estricta Excel vs DB..."}\n\n'
            missing = [np for np in unique_nps if np not in db_map]
            if missing:
                yield f'data: {{"status": "error", "msg": "[ERROR] PROCESO ABORTADO. Faltan {len(missing)} SKUs en la Base de Datos (ej. {missing[:3]}). Corrige y vuelve a intentar."}}\n\n'
                return
                
            yield 'data: {"status": "info", "msg": "[INFO] Comparación 100% exitosa."}\n\n'
            
            # 4. Create Joined Array First
            mapping = config.get('data_mapping', {})
            joined = []
            for em in excel_marbetes:
                np = em['np']
                db_row = db_map[np]
                def get_val(fn):
                    src = mapping.get(fn, 'db')
                    if src == 'excel': return em.get(fn, '') if fn != 'clave' else em.get('np', '')
                    elif src == 'db': return db_row.get(fn, '') if fn != 'clave' else db_row.get(key_to_use, np)
                    return ''
                    
                joined.append({
                    'np': get_val('clave'), 'clave': get_val('clave'), 'sheet': em.get('sheet', ''),
                    'descripcion': get_val('descripcion'), 'unidad': get_val('unidad'),
                    'empaque': get_val('empaque'), 'cantidad': get_val('cantidad'),
                    'contado_por': get_val('contado_por'), 'almacen': get_val('almacen'),
                    'folio': '' # default empty
                })

            # 5. Create PDFs (This will inject folios into 'joined')
            yield 'data: {"status": "info", "msg": "[INFO] Paso 4: Purgando PDFs anteriores..."}\n\n'
            flujo_dir = os.path.join(app.config['PDF_FOLDER'], 'flujo1_excel')
            if os.path.exists(flujo_dir):
                import shutil
                shutil.rmtree(flujo_dir)
            os.makedirs(flujo_dir, exist_ok=True)
            
            yield 'data: {"status": "info", "msg": "[INFO] Generando nuevos PDFs y Folios..."}\n\n'
            start_f = get_next_folio()
            pdfs_created = create_all_pdfs(joined, config['pdf_coords'], flujo_dir, start_folio=start_f, group_by_field='sheet')

            # 6. Save to DB AFTER PDFs have assigned folios
            yield 'data: {"status": "info", "msg": "[INFO] Paso 5: Guardando Resultado de Pool en BD..."}\n\n'
            init_db()
            insert_query(db_results)
            insert_cruce(joined)
            
            yield f'data: {{"status": "done", "msg": "[EXITO] Generación finalizada. {pdfs_created} archivos PDF listos para imprimir."}}\n\n'
        except Exception as e:
            if os.path.exists(app.config['PDF_FOLDER']):
                import shutil
                shutil.rmtree(app.config['PDF_FOLDER'])
                os.makedirs(app.config['PDF_FOLDER'], exist_ok=True)
            yield f'data: {{"status": "error", "msg": "[ERROR] Fallo crítico: {str(e)}. Rollback ejecutado (PDFs purgados)."}}\n\n'


    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/execute/stream_vacios')
def execute_stream_vacios():
    qty_param = request.args.get('qty', 0)
    def generate():
        import shutil
        import random
        qty = qty_param
        try:
            qty = int(qty)
            if qty <= 0: raise ValueError("Cantidad debe ser mayor a 0")
        except:
            yield 'data: {"status": "error", "msg": "[ERROR] Cantidad inválida."}\n\n'
            return

        txn_code = 'TX_' + ''.join(random.choice('ABCDEFGHJKMNPQRSTUVWXYZ23456789') for _ in range(4))

        yield f'data: {{"status": "info", "msg": "[INFO] Iniciando creación de {qty} marbetes EN BLANCO (Transacción {txn_code})..."}}\n\n'
        
        try:
            config = load_config()
            
            yield 'data: {"status": "info", "msg": "[INFO] Generando fantasmas en memoria..."}\n\n'
            joined = []
            for _ in range(qty):
                joined.append({
                    'np': '', 'clave': '', 'sheet': 'VACIOS', 'ubicacion': '',
                    'descripcion': '', 'unidad': '', 'empaque': '', 'cantidad': '',
                    'contado_por': '', 'almacen': '', 'folio': ''
                })
                
            yield 'data: {"status": "info", "msg": "[INFO] Purgando directorio anterior de vacíos..."}\n\n'
            vacios_root = os.path.join(app.config['PDF_FOLDER'], 'flujo3_vacios')
            if os.path.exists(vacios_root):
                shutil.rmtree(vacios_root)
            flujo_dir = os.path.join(vacios_root, txn_code)
            os.makedirs(flujo_dir, exist_ok=True)
            
            yield 'data: {"status": "info", "msg": "[INFO] Dibujando PDFs..."}\n\n'
            start_f = get_next_folio()
            pdfs_created = create_all_pdfs(joined, config['pdf_coords'], flujo_dir, start_folio=start_f, group_by_field='sheet', is_blank=True)
            
            yield 'data: {"status": "info", "msg": "[INFO] Guardando registro temporal en BD..."}\n\n'
            init_db()
            # No guardamos nada en crudo de query porque no hay query
            insert_cruce(joined)
            
            yield f'data: {{"status": "done", "msg": "[EXITO] Generación finalizada. {pdfs_created} PDFs listos en Flujo Vacíos.", "txn": "{txn_code}"}}\n\n'
            
        except Exception as e:
            vacios_root = os.path.join(app.config['PDF_FOLDER'], 'flujo3_vacios')
            if os.path.exists(vacios_root):
                import shutil
                shutil.rmtree(vacios_root)
                os.makedirs(vacios_root, exist_ok=True)
            yield f'data: {{"status": "error", "msg": "[ERROR] Fallo crítico: {str(e)}."}}\n\n'
            
    return Response(generate(), mimetype='text/event-stream')


@app.route('/api/pool/next_folio')
def get_next_f_api():
    return jsonify({'next_folio': str(get_next_folio()).zfill(5)})

@app.route('/api/data/logs')
def get_logs_data():
    return jsonify({
        'query': get_all_query(),
        'cruce': get_all_cruce(),
        'existencias': get_all_existencias()
    })

@app.route('/api/print/action', methods=['POST'])
def print_action():
    action = request.json.get('action')
    if action == 'pause':
        state.paused = True
    elif action == 'resume':
        state.paused = False
    elif action == 'stop':
        state.stopped = True
    elif action == 'add_paper':
        qty = request.json.get('count', 0)
        state.paper_count += int(qty)
        if state.paper_count > 0:
            state.paused = False
    return jsonify({'success': True, 'state': {'paused': state.paused, 'paper_count': state.paper_count}})

@app.route('/api/print/state')
def print_state():
    return jsonify({'paused': state.paused, 'paper_count': state.paper_count, 'current_file': state.current_file})

if __name__ == '__main__':
    app.run(debug=True, port=8001)
