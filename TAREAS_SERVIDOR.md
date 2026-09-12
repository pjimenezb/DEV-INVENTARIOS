# TAREAS — opencode del servidor

Handoff para el agente que trabajará este repo (DEV-INVENTARIOS / MARBETES).

## CONTEXTO PREVIO (obligatorio leer antes de tocar código)

1. App Flask (Python 3.14, `venv`, deps en `requirements.txt`), corre con `python app.py` → `127.0.0.1:8001` (modo debug).
2. La base interna ya es **PostgreSQL** (`config.json` → `local_db`, puede ser remoto 10.150.4.220:5434). **Ya NO hay SQLite ni fallback.** `core/local_db.py` es psycopg2 (DictCursor).
3. `backup_db()` es **no-op** en PG (decisión de negocio). Los respaldos reales que sí funcionan: tabla `pool_final_backup`, `create_pool_backup()`, `restore_pool_from_backup()`.
4. `config.json` **NO está en git** (tiene contraseñas Odoo/WMS/PG). En el servidor debe crearse desde `config.example.json` y verificarse conectividad a los 3 orígenes (PG interna, Odoo, WMS).
5. `marbetes_log.db` (legacy SQLite) tampoco está en git; solo útil para `core/migrate_local_db.py` (migración one-time).
6. En PG remoto, abrir conexión + commit **por registro cuesta ~600 ms**. Los patrones N+1 de la era SQLite ahora son cuellos de botella (ver T5).
7. Endpoints conocidos lentos: `/api/pt/consolidado_cedis1/reload` ~6–7 min (query WMS externo); `/api/analisis_final/audit` ~16 s (ya optimizado; antes 226 s).
8. **NO EJECUTAR `update_app.py`**: es un script inyector que REESCRIBE `app.py` con una versión vieja del consolidado (pierde recálculo DIFF/Acción y la regla ERROR). Considerar eliminarlo del repo.

## TAREAS

**T1. Setup del servidor**
Clonar repo → `python -m venv venv` → `pip install -r requirements.txt` → crear `config.json` real → `python app.py` → smoke test `/`, `/inventario_mp`, `/pt/consolidado_cedis1`.

**T2. Smoke test de datos reales**
Verificar endpoints MP y PT con datos reales: pool (≈7,503), análisis final (≈5,016), consolidado PT (≈1,412 + Acción), `/api/auditoria/data`, exports Excel/CSV.

**T3. Regresión módulo MP (flujo completo con archivos reales)**
Carga WMS / Saldos / Etiquetas y Mangas / EPTS (upload xlsx) → UoM & Empaque → Ubicaciones → Query/Cruce → transferir a Pool → generación de marbetes (folios consecutivos) → PDF → ediciones de pool → papelera (borrar/editar/restaurar) → auditoría de folios (lost/reconstruct desde PDFs) → exports.

**T4. Regresión módulo PT (flujo completo)**
Carga catálogos CEDIS 1 (Odoo) → Carga archivos WMS 1 (6 bloques + responsables + config destino suma/resta) → Consolidado (reload, update, recálculo DIFF/Acción, celdas finales negativas rojas + Acción ERROR) → exports.

**T5. Optimización N+1 en PG remoto**
Auditar `core/local_db.py` por loops que abren conexión por registro (patrón de `save_analisis_final_audit_state` en el endpoint audit, ya resuelto). Donde sea patológico, batch con una sola conexión/commit.

**T6. Funciones de local_db poco ejercitadas en PG**
Probar y corregir si algo falla: `reconstruct_deleted_from_pdfs`, `scan_pdf_folios`, `get_lost_folios`, `update_pool_deleted_records`, `mark_audit_all`, `create_pool_backup`, `restore_pool_from_backup`, `delete_*_records` (wms/saldos/etqmang/epts), `add_analisis_final_lotes`, `clear_analisis_final_nan_lotes`.

**T7. Deuda técnica / limpieza**
- Eliminar o marcar `update_app.py` como obsoleto (riesgo de reescribir `app.py`).
- Documentar `core/migrate_local_db.py` como one-time (necesita `marbetes_log.db`).
- `config.example.json` ya está saneado: mantener sustituyendo credenciales en blanco.
- Revisar botones de UI que invoquen `backup_db()` (no-op en PG): ajustar copy o comportamiento para no confundir.
- Silenciar (o migrar a SQLAlchemy) los `UserWarning` de `pandas.read_sql_query(conn)` de psycopg2 en los exports.

**T8. Disciplina de repo**
No commitear secretos ni datos; trabajar en rama y mantener `.gitignore` (ya excluye `config.json`, `marbetes_log.db`, `backups/`, `pdfs/`, `uploads/`, `analisisfinal/`, `artefactos/`).

## Decisión pendiente (usuario)
- ¿Eliminar `update_app.py` del repo?