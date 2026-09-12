"""Migración de marbetes_log.db (SQLite) -> PostgreSQL (config.json -> local_db).

Uso:
    ./venv/bin/python -m core.migrate_local_db            # migrar todo
    ./venv/bin/python -m core.migrate_local_db --check     # sólo validar

Requisito: el servidor ya debe haber creado las tablas PG (init_db) o este
script las crea automáticamente al inicio (idempotente).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sqlite3
import psycopg2
from psycopg2.extras import execute_values

from core.local_db import connect, init_db

SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'marbetes_log.db')

# Tablas del SQLite que se copian tal cual (columnas idénticas a PG).
_TABLES = [
    'log_existencias',
    'log_query',
    'log_cruce',
    'pool_final',
    'pool_final_backup',
    'wms_data',
    'saldos_data',
    'etqmang_data',
    'epts_data',
    'epts_comparativo',
    'pool_deleted',
    'module_actions',
    'analisis_final_data',
    'analisis_final_audit_state',
    'pt_cedis1_odoo_data',
    'pt_wms1_data',
    'pt_consolidado_cedis1',
    'pt_wms1_archivos_data',
    'pt_metadata',
]

# Tablas donde SQLite NO tiene la columna id (PG la genera con BIGSERIAL).
_NO_ID = {
    'log_query', 'log_cruce', 'pool_final', 'pool_final_backup', 'wms_data',
    'saldos_data', 'etqmang_data', 'epts_data', 'epts_comparativo',
    'pool_deleted', 'analisis_final_data', 'analisis_final_audit_state',
    'pt_metadata',
}

# Tablas donde el id NÚMERICO de SQLite SÍ debe preservarse.
_PRESERVE_ID = {
    'log_existencias', 'module_actions', 'pt_cedis1_odoo_data',
    'pt_wms1_data', 'pt_consolidado_cedis1', 'pt_wms1_archivos_data',
}


def sqlite_rows(table):
    sconn = sqlite3.connect(SQLITE_PATH)
    sconn.row_factory = sqlite3.Row
    try:
        cur = sconn.execute(f'SELECT * FROM "{table}"')
        return [dict(r) for r in cur.fetchall()], [d[0] for d in cur.description]
    finally:
        sconn.close()


def pg_columns(pconn, table):
    cur = pconn.cursor()
    cur.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name=%s ORDER BY ordinal_position", (table,))
    return [r[0] for r in cur.fetchall()]


def copy_table(cur, table, rows, cols_sql, preserve_id):
    if not rows:
        return 0
    if preserve_id and 'id' in cols_sql:
        cols = cols_sql
    else:
        cols = [c for c in cols_sql if c != 'id']
    placeholders = ','.join(['%s'] * len(cols))
    col_names = ','.join(cols)
    values = [tuple(r.get(c) for c in cols) for r in rows]
    execute_values(
        cur,
        f'INSERT INTO {table} ({col_names}) VALUES %s',
        values,
        template=f'({placeholders})',
    )
    if preserve_id and 'id' in cols:
        cur.execute(
            f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), "
            f"COALESCE((SELECT MAX(id) FROM {table}), 1))")
    return len(values)


def migrate():
    init_db()
    sconn = sqlite3.connect(SQLITE_PATH)
    sconn.row_factory = sqlite3.Row
    pconn = connect()
    try:
        all_tables = [r[0] for r in sconn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for table in _TABLES:
            if table not in all_tables:
                print(f'- {table}: (no existe en SQLite, ok)')
                continue
            rows, cols = sqlite_rows(table)
            pg_cols = pg_columns(pconn, table)
            missing = [c for c in cols if c not in pg_cols]
            if missing:
                raise RuntimeError(f'{table}: columnas sqlite no existen en PG: {missing}')
            cur = pconn.cursor()
            cur.execute(f'TRUNCATE TABLE {table}')
            preserve = table in _PRESERVE_ID
            n = copy_table(cur, table, rows, cols, preserve)
            cur.close()
            print(f'- {table}: {n} fila(s)')
        pconn.commit()
    except Exception:
        pconn.rollback()
        raise
    finally:
        sconn.close()
        pconn.close()


def check():
    sconn = sqlite3.connect(SQLITE_PATH)
    pconn = connect()
    try:
        for table in _TABLES:
            s_count = sconn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            cur = pconn.cursor()
            cur.execute(f'SELECT COUNT(*) FROM {table}')
            p_count = cur.fetchone()[0]
            cur.close()
            status = 'OK' if s_count == p_count else 'DIFERENTE!'
            print(f'- {table}: sqlite={s_count} pg={p_count} [{status}]')
    finally:
        sconn.close()
        pconn.close()


if __name__ == '__main__':
    if '--check' in sys.argv:
        check()
    else:
        migrate()
        print('Validando...')
        check()