import os
import json
import decimal
import datetime
import psycopg2
from psycopg2 import errors as pg_errors
from psycopg2.extras import DictCursor

_LOCAL_DB_CFG = None


def _load_local_db_config():
    global _LOCAL_DB_CFG
    if _LOCAL_DB_CFG is None:
        cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
        with open(cfg_path, 'r') as f:
            cfg = json.load(f)
        _LOCAL_DB_CFG = cfg.get('local_db', {})
    return _LOCAL_DB_CFG


def connect():
    """Abre una conexión a la base de datos interna (PostgreSQL)."""
    cfg = _load_local_db_config()
    return psycopg2.connect(
        host=cfg['host'],
        port=int(cfg.get('port', 5432)),
        user=cfg['user'],
        password=cfg['password'],
        database=cfg['database'],
        connect_timeout=10,
    )


def _cursor(conn):
    return conn.cursor(cursor_factory=DictCursor)


def init_db():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
    with open(cfg_path, 'r') as f:
        json.load(f)
    conn = connect()
    c = _cursor(conn)
    c.execute('DROP TABLE IF EXISTS log_existencias')
    c.execute('''CREATE TABLE log_existencias (
        id BIGSERIAL PRIMARY KEY,
        data_json TEXT
    )''')
    c.execute('DROP TABLE IF EXISTS log_query')
    c.execute('DROP TABLE IF EXISTS log_cruce')
    c.execute('''CREATE TABLE log_query (
        np TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT
    )''')
    c.execute('''CREATE TABLE log_cruce (
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT
    )''')

    # NUEVA TABLA (no se dropea para que sea permanente)
    c.execute('''CREATE TABLE IF NOT EXISTS pool_final (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT UNIQUE,
        almacen_pool TEXT, auditoria TEXT, varias_ubicaciones INTEGER DEFAULT 0, layout INTEGER DEFAULT 0
    )''')
    _ensure_column(conn, 'pool_final', 'almacen_pool', 'TEXT')
    _ensure_column(conn, 'pool_final', 'auditoria', 'TEXT')
    _ensure_column(conn, 'pool_final', 'varias_ubicaciones', 'INTEGER DEFAULT 0')
    _ensure_column(conn, 'pool_final', 'layout', 'INTEGER DEFAULT 0')
    c.execute('''CREATE TABLE IF NOT EXISTS pool_final_backup (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT,
        almacen_pool TEXT, auditoria TEXT, varias_ubicaciones INTEGER DEFAULT 0, layout INTEGER DEFAULT 0
    )''')
    _ensure_column(conn, 'pool_final_backup', 'almacen_pool', 'TEXT')
    _ensure_column(conn, 'pool_final_backup', 'auditoria', 'TEXT')
    _ensure_column(conn, 'pool_final_backup', 'varias_ubicaciones', 'INTEGER DEFAULT 0')
    _ensure_column(conn, 'pool_final_backup', 'layout', 'INTEGER DEFAULT 0')

    # Tabla WMS (Cargas WMS)
    c.execute('''CREATE TABLE IF NOT EXISTS wms_data (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT,
        almacen_pool TEXT, auditoria TEXT, varias_ubicaciones INTEGER DEFAULT 0, layout INTEGER DEFAULT 0
    )''')

    # Tabla Saldos
    c.execute('''CREATE TABLE IF NOT EXISTS saldos_data (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT,
        almacen_pool TEXT, auditoria TEXT, varias_ubicaciones INTEGER DEFAULT 0, layout INTEGER DEFAULT 0
    )''')

    # Tabla Etiquetas y Mangas
    c.execute('''CREATE TABLE IF NOT EXISTS etqmang_data (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT,
        almacen_pool TEXT, auditoria TEXT, varias_ubicaciones INTEGER DEFAULT 0, layout INTEGER DEFAULT 0
    )''')

    # Tabla EPTS
    c.execute('''CREATE TABLE IF NOT EXISTS epts_data (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT,
        almacen_pool TEXT, auditoria TEXT, varias_ubicaciones INTEGER DEFAULT 0, layout INTEGER DEFAULT 0, lote TEXT, unidad_file TEXT
    )''')

    # Tabla Comparativo de EPTS
    c.execute('''CREATE TABLE IF NOT EXISTS epts_comparativo (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT,
        almacen_pool TEXT, auditoria TEXT, varias_ubicaciones INTEGER DEFAULT 0, layout INTEGER DEFAULT 0, lote TEXT, unidad_file TEXT,
        procedencia TEXT, qty_odoo DOUBLE PRECISION DEFAULT 0, qty_conteo DOUBLE PRECISION DEFAULT 0, diff DOUBLE PRECISION DEFAULT 0, accion TEXT DEFAULT '', ajuste DOUBLE PRECISION DEFAULT 0
    )''')
    _ensure_column(conn, 'epts_comparativo', 'accion', "TEXT DEFAULT ''")
    _ensure_column(conn, 'epts_comparativo', 'ajuste', 'DOUBLE PRECISION DEFAULT 0')

    # Tabla Papelera de Auditoría
    c.execute('''CREATE TABLE IF NOT EXISTS pool_deleted (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, sheet TEXT, descripcion TEXT, unidad TEXT, empaque TEXT, almacen TEXT, cantidad TEXT, contado_por TEXT, estado TEXT, folio TEXT UNIQUE,
        almacen_pool TEXT, auditoria TEXT, varias_ubicaciones INTEGER DEFAULT 0, layout INTEGER DEFAULT 0
    )''')

    # Bitácora de acciones por módulo
    c.execute('''CREATE TABLE IF NOT EXISTS module_actions (
        id BIGSERIAL PRIMARY KEY,
        ts TEXT, module TEXT, endpoint TEXT, detail TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS analisis_final_data (
        id BIGSERIAL PRIMARY KEY,
        np TEXT, descripcion TEXT, bloque TEXT,
        unidad TEXT, lote TEXT,
        qty_odoo DOUBLE PRECISION DEFAULT 0, qty_conteo DOUBLE PRECISION DEFAULT 0,
        empaque TEXT, almacen TEXT,
        procedencia TEXT, sheet TEXT, auditoria TEXT
    )''')

    # Estado de revisión de cada hallazgo del Log de Auditoría
    c.execute('''CREATE TABLE IF NOT EXISTS analisis_final_audit_state (
        fkey TEXT PRIMARY KEY,
        estado TEXT DEFAULT '',
        nota TEXT DEFAULT '',
        ts TEXT
    )''')

    # Módulo PT (Carga de Catálogos CEDIS 1)
    c.execute('''CREATE TABLE IF NOT EXISTS pt_cedis1_odoo_data (
        id BIGSERIAL PRIMARY KEY,
        data_json TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS pt_wms1_data (
        id BIGSERIAL PRIMARY KEY,
        data_json TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS pt_consolidado_cedis1 (
        id BIGSERIAL PRIMARY KEY,
        data_json TEXT
    )''')

    # Submódulo "Carga archivos WMS 1" (6 bloques de CSVs)
    c.execute('''CREATE TABLE IF NOT EXISTS pt_wms1_archivos_data (
        id BIGSERIAL PRIMARY KEY,
        bloque TEXT,
        sku TEXT,
        cantidad TEXT,
        ubicacion TEXT
    )''')
    _ensure_column(conn, 'pt_wms1_archivos_data', 'ubicacion', 'TEXT')

    # Metadatos de PT
    c.execute('''CREATE TABLE IF NOT EXISTS pt_metadata (
        clave TEXT PRIMARY KEY,
        valor TEXT
    )''')

    conn.commit()
    conn.close()


def _ensure_column(conn, table, column, coltype):
    c = _cursor(conn)
    c.execute(
        'SELECT 1 FROM information_schema.columns WHERE table_name=%s AND column_name=%s',
        (table, column))
    if c.fetchone() is None:
        c.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {coltype}')


def _now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def backup_db(max_keep=10):
    """En modo PostgreSQL el respaldo se administra a nivel de servidor;
    esta función es un no-op informativo que preserva el contrato de la API."""
    return None


def clear_pt_wms1_archivo(bloque):
    """Elimina todos los registros de un bloque de archivos WMS 1."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('DELETE FROM pt_wms1_archivos_data WHERE bloque=%s', (bloque,))
        conn.commit()
        return True, f"Bloque '{bloque}' vaciado."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def log_module_action(module, endpoint, detail=''):
    """Registra en module_actions qué módulo ejecutó una acción y contra qué endpoint.
    Es la bitácora que permite rastrear el ORIGEN de cualquier modificación entre módulos."""
    try:
        conn = connect()
        c = _cursor(conn)
        c.execute("INSERT INTO module_actions (ts, module, endpoint, detail) VALUES (%s,%s,%s,%s)",
                  (_now(), str(module)[:40], str(endpoint)[:120], str(detail)[:400]))
        conn.commit()
        conn.close()
    except Exception:
        pass


def insert_query(data):
    conn = connect()
    c = _cursor(conn)
    for r in data:
        key_to_use = 'default_code' if 'default_code' in r else ('clave' if 'clave' in r else list(r.keys())[0])
        c.execute('INSERT INTO log_query VALUES (%s,%s,%s,%s,%s,%s,%s)',
                  (str(r.get(key_to_use, '')), str(r.get('descripcion', '')), str(r.get('unidad', '')),
                   str(r.get('empaque', '')), str(r.get('almacen', '')), str(r.get('cantidad', '')), str(r.get('contado_por', ''))))
    conn.commit()
    conn.close()


def insert_cruce(data):
    conn = connect()
    c = _cursor(conn)
    for r in data:
        c.execute('INSERT INTO log_cruce VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
                  (str(r.get('np', '')), str(r.get('sheet', '')), str(r.get('descripcion', '')),
                   str(r.get('unidad', '')), str(r.get('empaque', '')), str(r.get('almacen', '')),
                   str(r.get('cantidad', '')), str(r.get('contado_por', '')), 'OK', str(r.get('folio', ''))))
    conn.commit()
    conn.close()


def get_all_query():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT * FROM log_query')
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def get_all_cruce():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT * FROM log_cruce')
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


# NUEVAS FUNCIONES PARA POOL FINAL
def copy_to_pool_final():
    conn = connect()
    c = _cursor(conn)
    try:
        # Extraemos los temporales que tengan folio
        c.execute("SELECT * FROM log_cruce WHERE folio != '' AND folio IS NOT NULL")
        records = c.fetchall()

        if not records:
            conn.close()
            return False, "No hay marbetes generados (con folio) en el cruce temporal para copiar."

        # Insertamos 1 por 1 con ON CONFLICT DO NOTHING: si el folio ya existe en
        # Pool Final se omite (respetando no duplicar) y se sigue con el resto.
        inserted = 0
        skipped = 0
        for r in records:
            c.execute('''INSERT INTO pool_final
                (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0)
                ON CONFLICT DO NOTHING''',
                (r[0], r[1], r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], '', _now()))
            if c.rowcount:
                inserted += 1
            else:
                skipped += 1

        conn.commit()
        conn.close()
        if inserted == 0 and skipped > 0:
            return True, f"No se insertaron folios: todos ({skipped}) ya están en Pool Final."
        msg = f"Traspaso exitoso a Pool Final: {inserted} marbete(s) insertado(s)."
        if skipped:
            msg += f" {skipped} duplicado(s) omitido(s)."
        return True, msg
    except Exception as e:
        conn.close()
        return False, str(e)


def get_pool_final():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT * FROM pool_final ORDER BY folio DESC')
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def get_pool_matrix():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT DISTINCT almacen_pool FROM pool_final WHERE almacen_pool IS NOT NULL AND almacen_pool != '' ORDER BY almacen_pool ASC")
        columns = [row[0] for row in c.fetchall()]
        row_data = {}
        c.execute("SELECT np, almacen_pool FROM pool_final WHERE np IS NOT NULL AND np != '' AND almacen_pool IS NOT NULL AND almacen_pool != ''")
        for np, loc in c.fetchall():
            if np not in row_data:
                row_data[np] = set()
            row_data[np].add(loc)
        rows = [{'np': np, 'locations': sorted(locs)} for np, locs in row_data.items()]
        rows = [r for r in rows if len(r['locations']) > 1]
        rows.sort(key=lambda r: r['np'])
    except Exception:
        conn.close()
        return {'columns': [], 'rows': []}
    conn.close()
    return {'columns': columns, 'rows': rows}


def empty_pool_final():
    """Vacía TODA la tabla pool_final.
    ANTES toma un snapshot de respaldo en pool_final_backup (seguridad/rollback).
    Devuelve el número de registros eliminados."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM pool_final_backup")
        c.execute("""INSERT INTO pool_final_backup
            (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
            SELECT np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout
            FROM pool_final""")
        c.execute('DELETE FROM pool_final')
        total = c.rowcount
        # Al vaciar por completo, siguiente folio regresa a 1 si se desea regenerar
        conn.commit()
        return total
    except Exception:
        conn.rollback()
        return 0
    finally:
        conn.close()


def transfer_module_to_pool(table_name):
    """Crea marbetes NUEVOS (folios consecutivos) a partir de los registros SIN folio
    de un módulo (wms_data | saldos_data | etqmang_data) y los cierra en pool_final.
    - Conservación de folio: arranca en MAX(folio) de pool_final + 1.
    - Cada registro origen queda marcado con su folio; así un 2do clic no duplica.
    - Se toma snapshot de respaldo de pool_final antes de insertar (seguridad).
    Devuelve (success, msg)"""
    allowed = {'wms_data', 'saldos_data', 'etqmang_data', 'epts_data'}
    if table_name not in allowed:
        return False, "Tabla de módulo no permitida."
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute(f"SELECT id, np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, almacen_pool, varias_ubicaciones, layout "
                  f"FROM {table_name} WHERE folio IS NULL OR folio = ''")
        records = c.fetchall()
        if not records:
            conn.close()
            return False, "No hay registros sin folio en el módulo para traspasar."

        # Folio conservativo: continuar desde el último creado en Pool Final
        c.execute("SELECT MAX(CAST(folio AS INTEGER)) FROM pool_final WHERE folio IS NOT NULL AND folio != ''")
        last = c.fetchone()[0]
        next_folio = (int(last) + 1) if last is not None else 1

        # Snapshot de seguridad de pool_final antes de insertar
        c.execute("DELETE FROM pool_final_backup")
        c.execute("""INSERT INTO pool_final_backup
            (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
            SELECT np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout
            FROM pool_final""")

        visitoria = _now()
        total = 0
        first_folio = next_folio
        for rid, np_v, sheet, desc, unidad, empaque, almacen, cantidad, contado, estado, almacen_pool, varias, layout in records:
            folio_new = str(next_folio).zfill(5)
            next_folio += 1
            c.execute('''INSERT INTO pool_final
                (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING''',
                (np_v, sheet, desc, unidad or '', empaque or '', almacen,
                 cantidad or '', contado or '', estado or 'OK', folio_new,
                 almacen_pool or '', visitoria,
                 1 if varias else 0, 1 if layout else 0))
            c.execute(f"UPDATE {table_name} SET folio=%s, auditoria=%s WHERE id=%s", (folio_new, visitoria, rid))
            total += 1

        conn.commit()
        conn.close()
        if total == 0:
            return False, "No se insertó ningún marbete (folio duplicado detectado)."
        return True, f"Traspaso exitoso: {total} marbete(s) cerrado(s) en Pool Final (folios {str(first_folio).zfill(5)} a {str(next_folio - 1).zfill(5)})."
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, decimal.Decimal):
            return float(obj)
        if isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        return super().default(obj)


def insert_existencias(data_list):
    conn = connect()
    c = _cursor(conn)
    c.execute('DELETE FROM log_existencias')  # Purge old run
    for r in data_list:
        c.execute('INSERT INTO log_existencias (data_json) VALUES (%s)', (json.dumps(r, cls=CustomJSONEncoder),))
    conn.commit()
    conn.close()


def get_all_existencias():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT data_json FROM log_existencias ORDER BY id ASC')
        res = [json.loads(row['data_json']) for row in c.fetchall()]
    except Exception as e:
        print(f"Error reading existencias: {e}")
        res = []
    conn.close()
    return res


def get_next_folio():
    conn = connect()
    c = _cursor(conn)
    try:
        # Assuming folio is a string like '00001', cast to integer to find max
        c.execute("SELECT MAX(CAST(folio AS INTEGER)) FROM pool_final WHERE folio IS NOT NULL AND folio != ''")
        result = c.fetchone()[0]
        next_folio = (int(result) + 1) if result is not None else 1
    except Exception:
        next_folio = 1
    conn.close()
    return next_folio


def delete_selected_pool(folios):
    conn = connect()
    c = _cursor(conn)
    try:
        # 1. Mover seleccionados a la Papelera de Auditoría (retienen todos sus datos)
        placeholders = ','.join('%s' for _ in folios)
        c.execute(f"""INSERT INTO pool_deleted
            (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
            SELECT np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout
            FROM pool_final WHERE folio IN ({placeholders})
            ON CONFLICT DO NOTHING""", tuple(folios))
        moved = c.rowcount

        # 2. Borrar del Pool Final
        c.execute(f"DELETE FROM pool_final WHERE folio IN ({placeholders})", tuple(folios))
        conn.commit()
        return True, f"{moved} registro(s) movido(s) a la Papelera de Auditoría (sin sobrescribir el respaldo)."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def restore_pool_from_backup():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM pool_final")
        c.execute("""INSERT INTO pool_final
            (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
            SELECT np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout
            FROM pool_final_backup""")
        conn.commit()
        return True, "Pool Final restaurado desde el backup."
    except Exception as e:
        return False, str(e)
    finally:
        conn.close()


def get_pool_nps():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT DISTINCT np FROM pool_final WHERE np IS NOT NULL AND np != ''")
        res = [row[0] for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def get_pool_nps_varias():
    """Devuelve los NPs de pool_final con varias_ubicaciones = 1 (incluye los que tienen almacen_pool)."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT DISTINCT np FROM pool_final WHERE np IS NOT NULL AND np != '' AND varias_ubicaciones = 1")
        res = [row[0] for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


PDF_FOLIO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'pdfs')


def _folio_set(table):
    """Devuelve el set de folios (zfill 5) de una tabla."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute(f"SELECT folio FROM {table} WHERE folio IS NOT NULL AND folio != ''")
        res = {str(r[0]).strip().zfill(5) for r in c.fetchall()}
    except Exception:
        res = set()
    conn.close()
    return res


def scan_pdf_folios():
    """Escanea la carpeta pdfs/ y devuelve {folio(zfill5): almacen(nombre de carpeta)}.
    Extrae los folios desde el nombre de archivo (ej. 01842-01843-01844.pdf)."""
    result = {}
    if not os.path.exists(PDF_FOLIO_DIR):
        return result
    for root, dirs, files in os.walk(PDF_FOLIO_DIR):
        for f in files:
            if not f.lower().endswith('.pdf'):
                continue
            basename = f[:-4]
            parts = basename.split('-')
            almacen = os.path.basename(root) or ''
            for p in parts:
                p = p.strip()
                if p.isdigit() and int(p) >= 0:
                    result[str(int(p)).zfill(5)] = almacen
    return result


def get_pool_deleted():
    """Registros de la Papelera de Auditoría (marbetes eliminados seleccionados del Pool Final)."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT * FROM pool_deleted ORDER BY CAST(folio AS INTEGER) ASC')
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def update_pool_deleted_records(records):
    """Edita registros de la Papelera de Auditoría (misma lógica que pool_final, sin snapshot)."""
    if not records:
        return False, "No se recibieron registros para actualizar."
    conn = connect()
    c = _cursor(conn)
    try:
        visitoria = _now()
        for rec in records:
            folio = str(rec.get('folio', '')).strip()
            if not folio:
                continue
            set_clause = ", ".join([f"{f}=%s" for f in EDITABLE_FIELDS])
            params = [rec.get(f, '') if rec.get(f) is not None else '' for f in EDITABLE_FIELDS]
            params.append(visitoria)
            params.append(folio)
            c.execute(f"UPDATE pool_deleted SET {set_clause}, auditoria=%s WHERE folio=%s", params)
        conn.commit()
        return True, f"{len(records)} registro(s) de la Papelera actualizado(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def restore_from_deleted(folios):
    """Restaura registros seleccionados desde la Papelera (pool_deleted) hacia pool_final.
    Conserva su folio original. Solo sale de la papelera si se insertó con éxito."""
    conn = connect()
    c = _cursor(conn)
    try:
        placeholders = ','.join('%s' for _ in folios)
        c.execute(f"""INSERT INTO pool_final
            (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
            SELECT np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout
            FROM pool_deleted WHERE folio IN ({placeholders})
            ON CONFLICT DO NOTHING""", tuple(folios))
        restored = c.rowcount
        if restored:
            c.execute(f"DELETE FROM pool_deleted WHERE folio IN ({placeholders})", tuple(folios))
        conn.commit()
        if restored == 0:
            return False, "No se restauró ningún registro (folio ya existente en Pool Final)."
        return True, f"{restored} marbete(s) restaurado(s) a Pool Final."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def reconstruct_deleted_from_pdfs():
    """Escanea los PDFs físicos y agrega a la Papelera los folios que existen en archivos
    pero NO están en pool_final ni en pool_deleted, con estado 'Reconstruido desde PDF'.
    Solo reconstruye folios dentro del rango esperado (<= máximo folio de pool_final) para
    ignorar archivos anómalos de prueba como '99999-100000-100001.pdf'."""
    pdf_folios = scan_pdf_folios()
    if not pdf_folios:
        return False, "No se encontraron archivos PDF para reconstruir."
    conn = connect()
    c = _cursor(conn)
    try:
        pool_set = _folio_set('pool_final')
        del_set = _folio_set('pool_deleted')
        pool_max = max((int(x) for x in pool_set), default=0)
        visitoria = _now()
        inserted = 0
        skipped_outliers = 0
        for folio, almacen in sorted(pdf_folios.items()):
            if folio in pool_set or folio in del_set:
                continue
            if pool_max and int(folio) > pool_max:
                skipped_outliers += 1
                continue
            c.execute('''INSERT INTO pool_deleted
                (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0,0)
                ON CONFLICT DO NOTHING''',
                ('', '', '', '', '', almacen, '', '', 'Reconstruido desde PDF', folio, '', visitoria))
            if c.rowcount:
                inserted += 1
                del_set.add(folio)
        conn.commit()
        conn.close()
        if inserted == 0:
            if skipped_outliers:
                return True, f"Sin folios nuevos por reconstruir dentro del rango ({skipped_outliers} folio(s) anómalo(s) ignorado(s))."
            return True, "Sin folios nuevos por reconstruir (todos ya están en Pool Final o en la Papelera)."
        msg = f"{inserted} folio(s) reconstruido(s) desde PDF y agregado(s) a la Papelera de Auditoría."
        if skipped_outliers:
            msg += f" ({skipped_outliers} folio(s) anómalo(s) fuera del rango ignorado(s))."
        return True, msg
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, str(e)


def get_lost_folios():
    """Folios IRRECUPERABLES: números sin rastro (no están en pool_final, ni en la
    papelera ni existen como archivo PDF). Evalúa secuencia desde 00001 hasta el máximo
    folio CONFIABLE. Se ignora el outlier '99999-100000-100001.pdf' (folios anómalos que
    inflan el rango), por lo que la cota se toma de pool_final y pool_deleted."""
    known = _folio_set('pool_final') | _folio_set('pool_deleted')
    pdf_folios = set(scan_pdf_folios().keys())
    max_f = max((int(x) for x in known), default=0)
    bound = max_f if max_f else 0
    if bound <= 0:
        return []
    lost = []
    for i in range(1, bound + 1):
        f_str = str(i).zfill(5)
        if f_str not in known and f_str not in pdf_folios:
            lost.append({'folio': f_str, 'estado': 'Irrecuperable / Sin rastro'})
    return lost


def update_pool_location(np_map):
    """Actualiza la columna almacen_pool de pool_final.
    np_map: dict {np: ubicacion} -> None/'' deja la celda en blanco.
    También soporta {np: {'ubicacion': loc, 'varias': bool}} para actualizar varias_ubicaciones."""
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        visitoria = _now()
        for np_val, value in np_map.items():
            if isinstance(value, dict):
                ubicacion = value.get('ubicacion') or ''
                varias = 1 if value.get('varias') else 0
            else:
                ubicacion = value if value else ''
                varias = 0
            c.execute("UPDATE pool_final SET almacen_pool=%s, auditoria=%s, varias_ubicaciones=%s WHERE np=%s",
                      (ubicacion, visitoria, varias, np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


EDITABLE_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'cantidad', 'contado_por', 'almacen_pool']


def update_pool_records(records):
    """Actualiza registros en pool_final haciendo snapshot previo en pool_final_backup.
    records: lista de dicts {folio: str, np: .., sheet: .., ...} usando EDITABLE_FIELDS."""
    if not records:
        return False, "No se recibieron registros para actualizar."
    conn = connect()
    c = _cursor(conn)
    try:
        # Snapshot de seguridad antes de actualizar
        c.execute("DELETE FROM pool_final_backup")
        c.execute("""INSERT INTO pool_final_backup
            (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
            SELECT np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout
            FROM pool_final""")

        visitoria = _now()
        for rec in records:
            folio = str(rec.get('folio', '')).strip()
            if not folio:
                continue
            set_clause = ", ".join([f"{f}=%s" for f in EDITABLE_FIELDS])
            params = [rec.get(f, '') if rec.get(f) is not None else '' for f in EDITABLE_FIELDS]
            params.append(visitoria)
            params.append(folio)
            c.execute(f"UPDATE pool_final SET {set_clause}, auditoria=%s WHERE folio=%s", params)

        conn.commit()
        return True, f"{len(records)} registro(s) actualizado(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def update_pool_descriptions(np_map):
    """Actualiza la columna descripcion de pool_final de forma masiva.
    np_map: dict {np: descripcion}. Estampa la auditoría en cada fila cambiada.
    Solo actualiza si la descripción del query difiere de la actual."""
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        visitoria = _now()
        for np_val, desc in np_map.items():
            desc = str(desc).strip() if desc else ''
            if not desc:
                continue
            c.execute("UPDATE pool_final SET descripcion=%s, auditoria=%s WHERE np=%s AND descripcion<>%s",
                      (desc, visitoria, np_val, desc))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def mark_audit_all():
    """Estampa la fecha/hora actual en TODOS los registros de pool_final."""
    conn = connect()
    c = _cursor(conn)
    try:
        visitoria = _now()
        c.execute("UPDATE pool_final SET auditoria=%s", (visitoria,))
        updated = c.rowcount
        conn.commit()
        return updated
    except Exception:
        conn.rollback()
        return 0
    finally:
        conn.close()


def create_pool_backup():
    """Copia la tabla pool_final a su espejo pool_final_backup (snapshot manual)."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM pool_final_backup")
        c.execute("""INSERT INTO pool_final_backup
            (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
            SELECT np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout
            FROM pool_final""")
        total = c.rowcount
        conn.commit()
        return True, f"Respaldo de seguridad creado con {total} registro(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def load_wms_data(records):
    """Vacía la tabla wms_data y la llena con los nuevos registros.
    records: lista de dicts {np, sheet, descripcion, unidad, empaque, almacen, cantidad,
    contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout}.
    El folio se guarda SIEMPRE vacío en la sección WMS."""
    if not records:
        return False, "No se recibieron registros WMS para cargar."
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM wms_data")
        for r in records:
            c.execute('''INSERT INTO wms_data
                (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (r.get('np', ''), r.get('sheet', ''), r.get('descripcion', ''),
                 r.get('unidad', ''), r.get('empaque', ''), r.get('almacen', ''),
                 r.get('cantidad', ''), r.get('contado_por', ''), r.get('estado', 'OK'),
                 '', '', _now(),
                 1 if r.get('varias_ubicaciones') else 0,
                 1 if r.get('layout') else 0))
        conn.commit()
        return True, f"WMS cargado correctamente: {len(records)} registro(s) en wms_data."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_wms_data():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT * FROM wms_data ORDER BY CASE sheet WHEN 'WMS-B1' THEN 1 WHEN 'WMS-CEDIS 4' THEN 2 ELSE 3 END, CAST(folio AS TEXT) ASC")
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def get_wms_nps():
    """Devuelve los NPs distintos de la tabla wms_data."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT DISTINCT np FROM wms_data WHERE np IS NOT NULL AND np != ''")
        res = [row[0] for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def update_wms_uom_empaque(np_map):
    """Actualiza las columnas unidad y empaque de wms_data.
    np_map: dict {np: {'unidad': u, 'empaque': e}}."""
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        for np_val, info in np_map.items():
            unidad = info.get('unidad', '') or ''
            empaque = info.get('empaque', '') or ''
            c.execute("UPDATE wms_data SET unidad=%s, empaque=%s, auditoria=%s WHERE np=%s",
                      (unidad, empaque, _now(), np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def update_wms_location(np_map):
    """Actualiza las columnas almacen_pool y varias_ubicaciones de wms_data.
    np_map: dict {np: {'ubicacion': loc, 'varias': bool}}."""
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        for np_val, value in np_map.items():
            if isinstance(value, dict):
                ubicacion = value.get('ubicacion') or ''
                varias = 1 if value.get('varias') else 0
            else:
                ubicacion = value if value else ''
                varias = 0
            c.execute("UPDATE wms_data SET almacen_pool=%s, varias_ubicaciones=%s, auditoria=%s WHERE np=%s",
                      (ubicacion, varias, _now(), np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


WMS_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por']


def update_wms_records(records):
    """Actualiza registros en wms_data usando su id.
    records: lista de dicts {id: int, np: .., sheet: .., ...} usando WMS_EDIT_FIELDS."""
    if not records:
        return False, "No se recibieron registros para actualizar."
    conn = connect()
    c = _cursor(conn)
    try:
        visitoria = _now()
        updated = 0
        for rec in records:
            rid = str(rec.get('id', '')).strip()
            if not rid:
                continue
            set_clause = ", ".join([f"{f}=%s" for f in WMS_EDIT_FIELDS])
            params = [rec.get(f, '') if rec.get(f) is not None else '' for f in WMS_EDIT_FIELDS]
            params.append(visitoria)
            params.append(rid)
            c.execute(f"UPDATE wms_data SET {set_clause}, auditoria=%s WHERE id=%s", params)
            updated += c.rowcount
        conn.commit()
        return True, f"{updated} registro(s) actualizado(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


SALDOS_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por']


def load_saldos_data(records):
    """Vacía la tabla saldos_data y la llena con los nuevos registros.
    El folio se guarda SIEMPRE vacío en la sección Saldos."""
    if not records:
        return False, "No se recibieron registros Saldos para cargar."
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM saldos_data")
        for r in records:
            c.execute('''INSERT INTO saldos_data
                (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (r.get('np', ''), r.get('sheet', ''), r.get('descripcion', ''),
                 r.get('unidad', ''), r.get('empaque', ''), r.get('almacen', ''),
                 r.get('cantidad', ''), r.get('contado_por', ''), r.get('estado', 'OK'),
                 '', '', _now(),
                 1 if r.get('varias_ubicaciones') else 0,
                 1 if r.get('layout') else 0))
        conn.commit()
        return True, f"Saldos cargado correctamente: {len(records)} registro(s) en saldos_data."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_saldos_data():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT * FROM saldos_data ORDER BY CAST(np AS TEXT) ASC')
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def get_saldos_nps():
    """Devuelve los NPs distintos de la tabla saldos_data."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT DISTINCT np FROM saldos_data WHERE np IS NOT NULL AND np != ''")
        res = [row[0] for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def update_saldos_uom_empaque(np_map):
    """Actualiza las columnas unidad y empaque de saldos_data.
    np_map: dict {np: {'unidad': u, 'empaque': e}}."""
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        for np_val, info in np_map.items():
            unidad = info.get('unidad', '') or ''
            empaque = info.get('empaque', '') or ''
            c.execute("UPDATE saldos_data SET unidad=%s, empaque=%s, auditoria=%s WHERE np=%s",
                      (unidad, empaque, _now(), np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def update_saldos_location(np_map):
    """Actualiza las columnas almacen_pool y varias_ubicaciones de saldos_data.
    np_map: dict {np: {'ubicacion': loc, 'varias': bool}}."""
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        for np_val, value in np_map.items():
            if isinstance(value, dict):
                ubicacion = value.get('ubicacion') or ''
                varias = 1 if value.get('varias') else 0
            else:
                ubicacion = value if value else ''
                varias = 0
            c.execute("UPDATE saldos_data SET almacen_pool=%s, varias_ubicaciones=%s, auditoria=%s WHERE np=%s",
                      (ubicacion, varias, _now(), np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def update_saldos_records(records):
    """Actualiza registros en saldos_data usando su id.
    records: lista de dicts {id: int, np: .., sheet: .., ...} usando SALDOS_EDIT_FIELDS."""
    if not records:
        return False, "No se recibieron registros para actualizar."
    conn = connect()
    c = _cursor(conn)
    try:
        visitoria = _now()
        updated = 0
        for rec in records:
            rid = str(rec.get('id', '')).strip()
            if not rid:
                continue
            set_clause = ", ".join([f"{f}=%s" for f in SALDOS_EDIT_FIELDS])
            params = [rec.get(f, '') if rec.get(f) is not None else '' for f in SALDOS_EDIT_FIELDS]
            params.append(visitoria)
            params.append(rid)
            c.execute(f"UPDATE saldos_data SET {set_clause}, auditoria=%s WHERE id=%s", params)
            updated += c.rowcount
        conn.commit()
        return True, f"{updated} registro(s) actualizado(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


ETQMANG_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por']


def load_etqmang_data(records, replace_sheet=None):
    """Vacía la tabla etqmang_data y la llena con los nuevos registros.
    Si replace_sheet se indica, SOLO se reemplazan los registros de esa pestaña
    ('LayEtqMag-<replace_sheet>') y se conservan las demás.
    El folio se guarda SIEMPRE vacío en la sección Etiquetas y Mangas."""
    if not records:
        return False, "No se recibieron registros Etiquetas y Mangas para cargar."
    conn = connect()
    c = _cursor(conn)
    try:
        if replace_sheet:
            c.execute("DELETE FROM etqmang_data WHERE sheet=%s", (f'LayEtqMag-{replace_sheet}',))
        else:
            c.execute("DELETE FROM etqmang_data")
        for r in records:
            c.execute('''INSERT INTO etqmang_data
                (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (r.get('np', ''), r.get('sheet', ''), r.get('descripcion', ''),
                 r.get('unidad', ''), r.get('empaque', ''), r.get('almacen', ''),
                 r.get('cantidad', ''), r.get('contado_por', ''), r.get('estado', 'OK'),
                 '', '', _now(),
                 1 if r.get('varias_ubicaciones') else 0,
                 1 if r.get('layout') else 0))
        conn.commit()
        return True, f"Etiquetas y Mangas cargado correctamente: {len(records)} registro(s) en etqmang_data."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_etqmang_data():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT * FROM etqmang_data ORDER BY sheet ASC, CAST(np AS TEXT) ASC')
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def get_etqmang_nps():
    """Devuelve los NPs distintos de la tabla etqmang_data."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT DISTINCT np FROM etqmang_data WHERE np IS NOT NULL AND np != ''")
        res = [row[0] for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def update_etqmang_uom_empaque(np_map):
    """Actualiza las columnas unidad y empaque de etqmang_data.
    np_map: dict {np: {'unidad': u, 'empaque': e}}."""
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        for np_val, info in np_map.items():
            unidad = info.get('unidad', '') or ''
            empaque = info.get('empaque', '') or ''
            c.execute("UPDATE etqmang_data SET unidad=%s, empaque=%s, auditoria=%s WHERE np=%s",
                      (unidad, empaque, _now(), np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def update_etqmang_location(np_map):
    """Actualiza las columnas almacen_pool y varias_ubicaciones de etqmang_data.
    np_map: dict {np: {'ubicacion': loc, 'varias': bool}}."""
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        for np_val, value in np_map.items():
            if isinstance(value, dict):
                ubicacion = value.get('ubicacion') or ''
                varias = 1 if value.get('varias') else 0
            else:
                ubicacion = value if value else ''
                varias = 0
            c.execute("UPDATE etqmang_data SET almacen_pool=%s, varias_ubicaciones=%s, auditoria=%s WHERE np=%s",
                      (ubicacion, varias, _now(), np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def update_etqmang_records(records):
    """Actualiza registros en etqmang_data usando su id.
    records: lista de dicts {id: int, np: .., sheet: .., ...} usando ETQMANG_EDIT_FIELDS."""
    if not records:
        return False, "No se recibieron registros para actualizar."
    conn = connect()
    c = _cursor(conn)
    try:
        visitoria = _now()
        updated = 0
        for rec in records:
            rid = str(rec.get('id', '')).strip()
            if not rid:
                continue
            set_clause = ", ".join([f"{f}=%s" for f in ETQMANG_EDIT_FIELDS])
            params = [rec.get(f, '') if rec.get(f) is not None else '' for f in ETQMANG_EDIT_FIELDS]
            params.append(visitoria)
            params.append(rid)
            c.execute(f"UPDATE etqmang_data SET {set_clause}, auditoria=%s WHERE id=%s", params)
            updated += c.rowcount
        conn.commit()
        return True, f"{updated} registro(s) actualizado(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ============ MÓDULO PT ============

def set_pt_metadata(clave, valor):
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('INSERT INTO pt_metadata (clave, valor) VALUES (%s, %s) '
                  'ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor', (clave, valor))
        conn.commit()
    except Exception:
        pass
    finally:
        conn.close()


def get_pt_metadata(clave):
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT valor FROM pt_metadata WHERE clave = %s', (clave,))
        res = c.fetchone()
        return res[0] if res else ''
    except Exception:
        return ''
    finally:
        conn.close()


def load_pt_cedis1_odoo_data(records):
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('DELETE FROM pt_cedis1_odoo_data')
        for r in records:
            c.execute('INSERT INTO pt_cedis1_odoo_data (data_json) VALUES (%s)', (json.dumps(r, cls=CustomJSONEncoder),))
        conn.commit()
        set_pt_metadata('cedis1_odoo_last_update', _now())
        return True, f"Carga Odoo CEDIS 1 exitosa: {len(records)} registros."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_pt_cedis1_odoo_data():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT data_json FROM pt_cedis1_odoo_data ORDER BY id ASC')
        res = [json.loads(row['data_json']) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def load_pt_wms1_data(records):
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('DELETE FROM pt_wms1_data')
        for r in records:
            c.execute('INSERT INTO pt_wms1_data (data_json) VALUES (%s)', (json.dumps(r, cls=CustomJSONEncoder),))
        conn.commit()
        set_pt_metadata('wms1_last_update', _now())
        return True, f"Carga WMS 1 exitosa: {len(records)} registros."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_pt_wms1_data():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT data_json FROM pt_wms1_data ORDER BY id ASC')
        res = [json.loads(row['data_json']) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def load_pt_consolidado_cedis1(records):
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('DELETE FROM pt_consolidado_cedis1')
        for r in records:
            c.execute('INSERT INTO pt_consolidado_cedis1 (data_json) VALUES (%s)', (json.dumps(r, cls=CustomJSONEncoder),))
        conn.commit()
        set_pt_metadata('consolidado_cedis1_last_update', _now())
        return True, f"Consolidado CEDIS 1 exitoso: {len(records)} registros."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_pt_consolidado_cedis1():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT data_json FROM pt_consolidado_cedis1 ORDER BY id ASC')
        res = [json.loads(row['data_json']) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def load_pt_wms1_archivo(bloque, records):
    """Vacía los registros solo de un bloque específico y carga los nuevos del CSV"""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('DELETE FROM pt_wms1_archivos_data WHERE bloque=%s', (bloque,))
        for r in records:
            c.execute('INSERT INTO pt_wms1_archivos_data (bloque, sku, cantidad, ubicacion) VALUES (%s, %s, %s, %s)',
                      (bloque, str(r.get('sku', '')), str(r.get('cantidad', '')), str(r.get('ubicacion', ''))))
        conn.commit()
        return True, f"Carga exitosa: {len(records)} registros en el bloque '{bloque}'."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_pt_wms1_archivos(bloque):
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT sku, cantidad, ubicacion FROM pt_wms1_archivos_data WHERE bloque=%s ORDER BY id ASC', (bloque,))
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def group_sum_pt_wms1_archivos(bloque):
    """Agrupa por SKU (normalizado a mayúsculas) y suma las cantidades de un bloque.
    Devuelve {SKU: total}; dict vacío si el bloque no tiene datos."""
    res = {}
    for r in get_pt_wms1_archivos(bloque):
        sku = str(r.get('sku', '')).strip().upper()
        if not sku or sku in ('NONE', 'NAN', 'NULL', 'N/A'):
            continue
        try:
            cant = float(r.get('cantidad', 0) or 0)
        except Exception:
            cant = 0.0
        res[sku] = res.get(sku, 0.0) + cant
    return res


def merge_pt_data(existing_records, update_records, key_col='np'):
    """Fusión (merge) de registros. update_records enriquece existing_records."""
    # Convert update_records to a dict by key_col
    update_map = {}

    # Intenta detectar la columna del NP si no se llama exactamente 'np'
    # Buscar una columna que parezca ser NP en update_records
    update_key_col = key_col
    if update_records:
        first_rec = update_records[0]
        candidates = ['np', 'sku', 'clave', 'codigo', 'default_code', 'referencia']

        # Búsqueda case-insensitive flexible
        for cand in candidates:
            for k in first_rec.keys():
                if cand == k.lower():
                    update_key_col = k
                    break
            else:
                continue
            break
        else:
            if key_col not in first_rec:
                # Fallback a la primera columna si no hay ninguna conocida
                update_key_col = list(first_rec.keys())[0]

    for r in update_records:
        kval = str(r.get(update_key_col, '')).strip().upper()
        if kval:
            update_map[kval] = r

    # Determinar la columna NP en existing_records
    exist_key_col = key_col
    if existing_records:
        first_rec = existing_records[0]
        candidates = ['np', 'sku', 'clave', 'codigo', 'default_code', 'referencia', 'producto']
        for cand in candidates:
            # Búsqueda case-insensitive flexible
            for k in first_rec.keys():
                if cand == k.lower():
                    exist_key_col = k
                    break
        else:
            if exist_key_col not in first_rec:
                exist_key_col = list(first_rec.keys())[0]

    updated_count = 0
    # Opcional: obtener un listado normalizado de las columnas que existen en el modelo original
    original_keys = {k.lower(): k for k in existing_records[0].keys()} if existing_records else {}

    for r in existing_records:
        kval = str(r.get(exist_key_col, '')).strip().upper()
        if kval and kval in update_map:
            upd_data = update_map[kval]
            # Mezclar solo si la columna devuelta por el query ya existía en el modelo (ignorar extras)
            for k, v in upd_data.items():
                if k != update_key_col:  # No sobrescribir la llave
                    # Comparación case-insensitive para la llave de destino
                    k_low = k.lower()
                    if k_low in original_keys:
                        r[original_keys[k_low]] = v
            updated_count += 1

    return existing_records, updated_count


EPTS_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por', 'lote', 'unidad_file']


def load_epts_data(records):
    """Vacía la tabla epts_data y la llena con los nuevos registros.
    El folio se guarda SIEMPRE vacío en la sección EPTS."""
    if not records:
        return False, "No se recibieron registros EPTS para cargar."
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM epts_data")
        for r in records:
            c.execute('''INSERT INTO epts_data
                (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout, lote, unidad_file)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (r.get('np', ''), r.get('sheet', ''), r.get('descripcion', ''),
                 r.get('unidad', ''), r.get('empaque', ''), r.get('almacen', ''),
                 r.get('cantidad', ''), r.get('contado_por', ''), r.get('estado', 'OK'),
                 '', '', _now(),
                 1 if r.get('varias_ubicaciones') else 0,
                 1 if r.get('layout') else 0,
                 r.get('lote', ''), r.get('unidad_file', '')))
        conn.commit()
        return True, f"EPTS cargado correctamente: {len(records)} registro(s) en epts_data."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_epts_data():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('SELECT * FROM epts_data ORDER BY CAST(np AS TEXT) ASC')
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def clear_epts_data():
    """VACÍA SOLO la tabla epts_data (sin afectar el resto del sistema).
    Pensado para sustituir el archivo de inventario EPTS por uno definitivo."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM epts_data")
        conn.commit()
        return True, "Tabla EPTS vaciada correctamente (solo epts_data)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_epts_nps():
    """Devuelve los NPs distintos de la tabla epts_data."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT DISTINCT np FROM epts_data WHERE np IS NOT NULL AND np != ''")
        res = [row[0] for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def update_epts_uom_empaque(np_map):
    """Actualiza las columnas unidad y empaque de epts_data.
    np_map: dict {np: {'unidad': u, 'empaque': e}}."""
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        for np_val, info in np_map.items():
            unidad = info.get('unidad', '') or ''
            empaque = info.get('empaque', '') or ''
            c.execute("UPDATE epts_data SET unidad=%s, empaque=%s, auditoria=%s WHERE np=%s",
                      (unidad, empaque, _now(), np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def update_epts_location(np_map):
    """Actualiza las columnas almacen_pool y varias_ubicaciones de epts_data.
    np_map: dict {np: {'ubicacion': loc, 'varias': bool}}."""
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        for np_val, value in np_map.items():
            if isinstance(value, dict):
                ubicacion = value.get('ubicacion') or ''
                varias = 1 if value.get('varias') else 0
            else:
                ubicacion = value if value else ''
                varias = 0
            c.execute("UPDATE epts_data SET almacen_pool=%s, varias_ubicaciones=%s, auditoria=%s WHERE np=%s",
                      (ubicacion, varias, _now(), np_val))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def update_epts_records(records):
    """Actualiza registros en epts_data usando su id.
    records: lista de dicts {id: int, np: .., sheet: .., ...} usando EPTS_EDIT_FIELDS."""
    if not records:
        return False, "No se recibieron registros para actualizar."
    conn = connect()
    c = _cursor(conn)
    try:
        visitoria = _now()
        updated = 0
        for rec in records:
            rid = str(rec.get('id', '')).strip()
            if not rid:
                continue
            set_clause = ", ".join([f"{f}=%s" for f in EPTS_EDIT_FIELDS])
            params = [rec.get(f, '') if rec.get(f) is not None else '' for f in EPTS_EDIT_FIELDS]
            params.append(visitoria)
            params.append(rid)
            c.execute(f"UPDATE epts_data SET {set_clause}, auditoria=%s WHERE id=%s", params)
            updated += c.rowcount
        conn.commit()
        return True, f"{updated} registro(s) actualizado(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# ============ ELIMINACIÓN POR SELECCIÓN EN MÓDULOS (borrado definitivo) ============

def _delete_module_rows(table, ids, label):
    """Borra de forma PERMANENTE los registros con id en `ids` de la tabla del módulo."""
    if not ids:
        return False, "No se recibieron registros para eliminar."
    conn = connect()
    c = _cursor(conn)
    try:
        placeholders = ','.join('%s' for _ in ids)
        c.execute(f"DELETE FROM {table} WHERE id IN ({placeholders})", tuple(ids))
        deleted = c.rowcount
        conn.commit()
        return True, f"{deleted} registro(s) eliminado(s) definitivamente del modelo {label}."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def delete_wms_records(ids):
    return _delete_module_rows('wms_data', ids, 'WMS')


def delete_saldos_records(ids):
    return _delete_module_rows('saldos_data', ids, 'Saldos')


def delete_etqmang_records(ids):
    return _delete_module_rows('etqmang_data', ids, 'Etiquetas y Mangas')


def delete_epts_records(ids):
    return _delete_module_rows('epts_data', ids, 'EPTS')

# ============ COMPARATIVO EPTS (Query EPTS vs Datos EPTS) ============

def clear_epts_comparativo():
    """VACÍA SOLO la tabla epts_comparativo (sin afectar epts_data ni el resto del sistema)."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM epts_comparativo")
        deleted = c.rowcount
        conn.commit()
        return True, f"Comparativo EPTS vaciado correctamente ({deleted} registro(s) previos)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def load_epts_comparativo(records):
    """Vacía epts_comparativo y la llena con los nuevos registros del comparativo."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("DELETE FROM epts_comparativo")
        for r in records:
            c.execute('''INSERT INTO epts_comparativo
                (np, sheet, descripcion, unidad, empaque, almacen, cantidad, contado_por, estado, folio, almacen_pool, auditoria, varias_ubicaciones, layout, lote, unidad_file,
                 procedencia, qty_odoo, qty_conteo, diff, accion, ajuste)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (r.get('np', ''), r.get('sheet', ''), r.get('descripcion', ''),
                 r.get('unidad', ''), r.get('empaque', ''), r.get('almacen', ''),
                 r.get('cantidad', ''), r.get('contado_por', ''), r.get('estado', 'OK'),
                 '', '', _now(),
                 1 if r.get('varias_ubicaciones') else 0,
                 1 if r.get('layout') else 0,
                 r.get('lote', ''), r.get('unidad_file', ''),
                 r.get('procedencia', ''), r.get('qty_odoo', 0), r.get('qty_conteo', 0), r.get('diff', 0),
                 r.get('accion', ''), r.get('ajuste', 0)))
        conn.commit()
        return True, f"Comparativo EPTS cargado correctamente: {len(records)} registro(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_epts_comparativo():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('''SELECT * FROM epts_comparativo
                     ORDER BY CASE procedencia WHEN 'SOLO CONTEO' THEN 0 WHEN 'AMBOS' THEN 1 ELSE 2 END,
                              CAST(np AS TEXT) ASC, lote ASC''')
        res = [dict(row) for row in c.fetchall()]
    except Exception:
        res = []
    conn.close()
    return res


def sync_epts_comparativo_from_datos():
    """Propaga los campos de Datos EPTS (epts_data) hacia las filas existentes del Comparativo
    EPTS por llave (np, lote). Se usa tras llenar UoM & Empaque o Ubicaciones Query 2, SIN
    re-ejecutar el query. Solo se actualizan filas cuyo (np, lote) existe en Datos EPTS."""
    conn = connect()
    c = _cursor(conn)
    try:
        try:
            c.execute("SELECT COUNT(*) FROM epts_comparativo")
        except pg_errors.UndefinedTable:
            return True, "No hay comparativo EPTS que sincronizar."
        c.execute("SELECT id, np, lote FROM epts_comparativo")
        comp_rows = c.fetchall()
        c.execute("""SELECT np, lote, sheet, descripcion, unidad, empaque, almacen,
                            contado_por, almacen_pool, auditoria, varias_ubicaciones, layout, unidad_file
                     FROM epts_data""")
        dmap = {}
        for r in c.fetchall():
            k = (str(r[0] or '').strip().upper(), str(r[1] or '').strip())
            dmap[k] = r
        updated = 0
        for rowid, npv, lotev in comp_rows:
            k = (str(npv or '').strip().upper(), str(lotev or '').strip())
            d = dmap.get(k)
            if not d:
                continue
            c.execute('''UPDATE epts_comparativo SET
                    sheet=%s, descripcion=%s, unidad=%s, empaque=%s, almacen=%s, contado_por=%s,
                    almacen_pool=%s, auditoria=%s, varias_ubicaciones=%s, layout=%s, unidad_file=%s
                    WHERE id=%s''',
                    (d[2], d[3], d[4], d[5], d[6], d[7],
                     d[8], d[9], 1 if d[10] else 0, 1 if d[11] else 0, d[12], rowid))
            updated += 1
        conn.commit()
        return True, f"Comparativo EPTS sincronizado: {updated} fila(s) actualizada(s) desde Datos EPTS."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


# =================== ANÁLISIS FINAL ===================

AF_EDIT_FIELDS = ['np', 'descripcion', 'unidad', 'lote', 'qty_odoo', 'qty_conteo',
                  'empaque', 'almacen', 'procedencia', 'sheet']


def load_analisis_final(records):
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('DELETE FROM analisis_final_data')
        for r in records:
            c.execute('''INSERT INTO analisis_final_data
                (np, descripcion, bloque, unidad, lote, qty_odoo, qty_conteo,
                 empaque, almacen, procedencia, sheet, auditoria)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (r.get('np', ''), r.get('descripcion', ''), r.get('bloque', ''),
                 r.get('unidad', ''), r.get('lote', ''),
                 float(r.get('qty_odoo', 0) or 0), float(r.get('qty_conteo', 0) or 0),
                 r.get('empaque', ''), r.get('almacen', ''),
                 r.get('procedencia', ''), r.get('sheet', ''), _now()))
        conn.commit()
        return True, f"Análisis Final cargado correctamente: {len(records)} registro(s)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def get_analisis_final():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('''SELECT * FROM analisis_final_data
                     ORDER BY bloque, CAST(np AS TEXT) ASC''')
        return [dict(row) for row in c.fetchall()]
    finally:
        conn.close()


def get_analisis_final_nps():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT DISTINCT np FROM analisis_final_data WHERE np IS NOT NULL AND TRIM(np) != ''")
        return [r[0] for r in c.fetchall()]
    except Exception:
        return []
    finally:
        conn.close()


def update_analisis_final_uom(np_map):
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        visitoria = _now()
        for np_val, info in np_map.items():
            unidad = str(info.get('unidad', '') or '').strip()
            empaque = str(info.get('empaque', '') or '').strip()
            if not unidad and not empaque:
                continue
            if unidad:
                c.execute("UPDATE analisis_final_data SET unidad=%s, auditoria=%s WHERE np=%s AND unidad<>%s",
                          (unidad, visitoria, np_val, unidad))
                updated += c.rowcount
            if empaque:
                c.execute("UPDATE analisis_final_data SET empaque=%s, auditoria=%s WHERE np=%s AND empaque<>%s",
                          (empaque, visitoria, np_val, empaque))
                updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def update_analisis_final_descriptions(np_map):
    if not np_map:
        return 0
    conn = connect()
    c = _cursor(conn)
    updated = 0
    try:
        visitoria = _now()
        for np_val, desc in np_map.items():
            desc = str(desc).strip() if desc else ''
            if not desc:
                continue
            c.execute("UPDATE analisis_final_data SET descripcion=%s, auditoria=%s WHERE np=%s AND descripcion<>%s",
                      (desc, visitoria, np_val, desc))
            updated += c.rowcount
        conn.commit()
    except Exception:
        conn.rollback()
        updated = 0
    finally:
        conn.close()
    return updated


def clear_analisis_final():
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT COUNT(*) FROM analisis_final_data")
        deleted = c.fetchone()[0]
        c.execute("DELETE FROM analisis_final_data")
        conn.commit()
        return True, f"Análisis Final vaciado correctamente ({deleted} registro(s) previos)."
    except Exception as e:
        conn.rollback()
        return False, str(e)
    finally:
        conn.close()


def delete_analisis_final_records(ids):
    return _delete_module_rows('analisis_final_data', ids, 'Análisis Final')


def save_analisis_final_audit_state(fkey, estado, nota=''):
    """Guarda (upsert) el estado de revisión de un hallazgo del Log de Auditoría."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('''INSERT INTO analisis_final_audit_state (fkey, estado, nota, ts)
                     VALUES (%s,%s,%s,%s)
                     ON CONFLICT (fkey) DO UPDATE SET estado=EXCLUDED.estado, nota=EXCLUDED.nota, ts=EXCLUDED.ts''',
                  (str(fkey), str(estado or ''), str(nota or ''), _now()))
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        return False
    finally:
        conn.close()


def get_analisis_final_audit_states():
    """Devuelve dict {fkey: {estado, nota, ts}} con los estados guardados."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute("SELECT fkey, estado, nota, ts FROM analisis_final_audit_state")
        return {r['fkey']: {'estado': r['estado'] or '', 'nota': r['nota'] or '', 'ts': r['ts'] or ''} for r in c.fetchall()}
    except Exception:
        return {}
    finally:
        conn.close()


def add_analisis_final_lotes(records):
    """Agrega lotes faltantes del Query Auditoría 1 al modelo Análisis Final.
    Los registros llevan toda la info de una fila existente del NP (descripcion, unidad,
    empaque, almacen, etc.) y solo el lote + qty_odoo del Query; qty_conteo queda en 0.
    Deduplica por (np, bloque, almacen, lote). Devuelve (success, msg, added, detalle)."""
    if not records:
        return False, "No se recibieron registros para agregar.", 0, []
    conn = connect()
    c = _cursor(conn)
    added = 0
    detalle = []
    try:
        for r in records:
            np_v = str(r.get('np', '') or '').strip()
            lote = str(r.get('lote', '') or '').strip()
            bloque = str(r.get('bloque', '') or '').strip()
            almacen = str(r.get('almacen', '') or '').strip()
            if not np_v or not lote:
                continue
            c.execute('''SELECT COUNT(*) FROM analisis_final_data
                         WHERE np=%s AND bloque=%s AND almacen=%s AND lote=%s''',
                      (np_v, bloque, almacen, lote))
            if c.fetchone()[0] > 0:
                continue
            c.execute('''INSERT INTO analisis_final_data
                (np, descripcion, bloque, unidad, lote, qty_odoo, qty_conteo,
                 empaque, almacen, procedencia, sheet, auditoria)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''',
                (np_v, r.get('descripcion', '') or '', bloque,
                 r.get('unidad', '') or '', lote,
                 float(r.get('qty_odoo', 0) or 0), 0.0,
                 r.get('empaque', '') or '', almacen,
                 'QC Query Auditoría 1', r.get('sheet', '') or '', _now()))
            added += 1
            detalle.append({'np': np_v, 'lote': lote, 'qty': float(r.get('qty_odoo', 0) or 0), 'bloque': bloque})
        conn.commit()
        if added == 0:
            return False, "No se agregó ningún lote (ya existían en el modelo o datos inválidos).", 0, detalle
        return True, f"{added} lote(s) agregado(s) al modelo Análisis Final.", added, detalle
    except Exception as e:
        conn.rollback()
        return False, f'Error agregando lotes: {str(e)}', 0, detalle
    finally:
        conn.close()


def clear_analisis_final_nan_lotes(bloque='EPT'):
    """Corrige directo las filas del modelo cuyo lote es 'nan' (dato basura, ej. marías
    tipo MESC): deja el lote en blanco (''). Idempotente: tras corregir no queda ningún
    lote 'nan' en ese bloque. Devuelve {'updated': n, 'nps': [...]}."""
    conn = connect()
    c = _cursor(conn)
    try:
        c.execute('''SELECT id, np FROM analisis_final_data
                     WHERE bloque=%s AND lote IS NOT NULL AND lote<>'' AND lower(lote)=%s''',
                  (str(bloque or ''), 'nan'))
        filas = c.fetchall()
        ids = [r[0] for r in filas]
        nps = []
        for _id, np_v in filas:
            if str(np_v or '').strip() and str(np_v or '').strip() not in nps:
                nps.append(str(np_v or '').strip())
        if not ids:
            return {'updated': 0, 'nps': []}
        placeholders = ','.join('%s' for _ in ids)
        c.execute(f"UPDATE analisis_final_data SET lote='' WHERE id IN ({placeholders})", ids)
        conn.commit()
        return {'updated': len(ids), 'nps': nps}
    except Exception:
        conn.rollback()
        return {'updated': 0, 'nps': []}
    finally:
        conn.close()