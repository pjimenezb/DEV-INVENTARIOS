# DEV-INVENTARIOS (MARBETES)

Sistema interno de inventarios (Materia Prima y Producto Terminado) para Raloy.
Aplicación web Flask para el conteo cíclico, generación de marbetes, auditoría de
folios y consolidados de existencias contra Odoo y WMS.

## Descripción

- **Módulo MP (Materia Prima):** carga de inventarios (WMS, Saldos, Etiquetas y
  Mangas, EPTS), cruces, generación de marbetes (PDF), pool final, análisis final
  y auditoría de folios (papelera, recuperación desde PDFs).
- **Módulo PT (Producto Terminado):** catálogos CEDIS 1 desde Odoo, archivos WMS,
  consolidado de existencias con cálculo de acción (ALTA / AUMENTO / DECREMENTO /
  BAJA / NO HAGO NADA / ERROR) y exportación.

## Requisitos

- Python 3.14+
- Credenciales locales: se requieren un `config.json` con las conexiones a
  PostgreSQL (base interna), Odoo y MySQL/WMS. Ver `config.example.json` como
  plantilla de estructura (credenciales en blanco).

## Instalación

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp config.example.json config.json   # completar credenciales reales
```

## Ejecución

```bash
python app.py
```

La app arranca en `http://127.0.0.1:8001` (modo debug).

## Base de datos

- Interna (históricos, pool, análisis, PT): PostgreSQL — configurables en
  `config.json` → `local_db`.
- Orígenes externos (solo lectura): Odoo `db` y WMS `pt_wms` (MySQL).

## Notas

- Los archivos de datos operativos (`marbetes_log.db`, `backups/`, `pdfs/`,
  `uploads/`, `analisisfinal/`, CSVs de carga) no se versionan.
- La migración histórica SQLite → PostgreSQL puede reproducirse con
  `python -m core.migrate_local_db`.