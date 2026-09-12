// Helper to append logs
function addLog(message, isError=false) {
    const consoleOut = document.getElementById('console-output');
    if(!consoleOut) return;
    const div = document.createElement('div');
    div.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
    if (isError) div.style.color = 'red';
    consoleOut.appendChild(div);
    consoleOut.scrollTop = consoleOut.scrollHeight;
}

// 1. Database Config
async function testDB() {
    const data = {
        host: document.getElementById('db-host').value,
        port: document.getElementById('db-port').value,
        user: document.getElementById('db-user').value,
        password: document.getElementById('db-password').value,
        database: document.getElementById('db-database').value,
    };
    const res = await fetch('/api/config/db', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    const json = await res.json();
    const alertDiv = document.getElementById('db-alert');
    if (json.success) {
        alertDiv.innerHTML = `<span class="text-success">Conexión exitosa y guardada.</span>`;
    } else {
        alertDiv.innerHTML = `<span class="text-danger">Error: ${json.error}</span>`;
    }
}

// 2. Query and Diff
async function saveQuery() {
    const query = document.getElementById('db-query').value;
    await fetch('/api/config/query', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query})
    });
    alert('Query guardado');
}


async function saveExistenciasQuery() {
    const query = document.getElementById('db-query-existencias').value;
    await fetch('/api/config/existencias', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query})
    });
    alert('Query de Existencias guardado');
}

async function savePoolQuery() {
    const query = document.getElementById('db-query-pool').value;
    await fetch('/api/config/query_pool', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query})
    });
    alert('Query Pool Data guardado');
}

async function saveEptsQuery() {
    const query = document.getElementById('db-query-epts').value;
    await fetch('/api/config/query_epts', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query})
    });
    alert('Query EPTS guardado');
}

async function saveAuditoriaQuery() {
    const query = document.getElementById('db-query-auditoria').value;
    await fetch('/api/config/query_auditoria', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({query})
    });
    alert('Query Auditoría 1 guardado');
}

async function runEptsQuery() {
    const btn = document.getElementById('btn-epts-query');
    if(btn) { btn.disabled = true; btn.textContent = '⌛ Ejecutando...'; }
    try {
        const res = await fetch('/api/epts/compare', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'epts'})
        });
        const json = await res.json();
        if(json.success) {
            eptsCompData = json.data || [];
            renderEptsComparativo();
            const t = json.totals || {};
            const warning = json.warning ? '\n⚠️ ' + json.warning : '';
            alert(`✅ ${json.msg}\nTotal: ${t.total} | AMBOS: ${t.ambos} | SOLO ODOO: ${t.solo_odoo} | SOLO CONTEO: ${t.solo_conteo}${warning}`);
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        if(btn) { btn.disabled = false; btn.textContent = '🔍 Ejecutar Query EPTS'; }
    }
}

async function saveMapping() {
    const data = {
        clave: document.getElementById('map-clave').value,
        unidad: document.getElementById('map-unidad').value,
        empaque: document.getElementById('map-empaque').value,
        almacen: document.getElementById('map-almacen').value,
        cantidad: document.getElementById('map-cantidad').value,
        contado_por: document.getElementById('map-contado').value,
        descripcion: 'db' // Fijo por ahora
    };
    await fetch('/api/config/mapping', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    alert('Mapeo de Origen de Datos guardado');
    // Refresh preview if available
    updatePreview();
}

async function testQueryDiff() {
    const fileInput = document.getElementById('excel-test-file');
    if (!fileInput.files[0]) return alert("Selecciona un archivo Excel");

    const formData = new FormData();
    formData.append('file', fileInput.files[0]);

    document.getElementById('diff-results').style.display = 'block';
    document.getElementById('summary-container').style.display = 'block';
    document.getElementById('diff-tbody').innerHTML = '<tr><td colspan="3">Procesando...</td></tr>';
    document.getElementById('summary-badges').innerHTML = 'Cargando resumen...';

    try {
        const res = await fetch('/api/diff', {
            method: 'POST',
            body: formData
        });
        const json = await res.json();
        
        if (!json.success) throw new Error(json.error);

        // Render Summary
        let summaryHtml = '';
        for (const [sheet, stats] of Object.entries(json.summary)) {
            const isPerfect = stats.fail === 0;
            const badgeClass = isPerfect ? 'bg-success' : 'bg-danger';
            summaryHtml += `
                <span class="badge ${badgeClass} p-2 fs-6">
                    ${sheet}: ${stats.total} total | ${stats.ok} OK
                    ${!isPerfect ? ` | ${stats.fail} Fallos` : ''}
                </span>`;
        }
        document.getElementById('summary-badges').innerHTML = summaryHtml;

        // Render Table
        let html = '';
        // Ordenar para mostrar primero los errores (Falta en DB)
        json.diff.sort((a, b) => (a.in_db === b.in_db ? 0 : a.in_db ? 1 : -1));
        
        json.diff.forEach(item => {
            const rowClass = item.in_db ? 'diff-match' : 'diff-missing-db';
            const status = item.in_db ? '✅ Encontrado en DB' : '❌ Falta en DB';
            html += `<tr class="${rowClass}"><td>${item.np}</td><td><span class="badge bg-secondary">${item.sheet}</span></td><td>${status}</td></tr>`;
        });
        document.getElementById('diff-tbody').innerHTML = html;
        
        // Habilitar preview y test dummy
        document.getElementById('btn-dummy-print').disabled = false;
        const overlay = document.getElementById('preview-overlay');
        if(overlay) overlay.style.display = 'none';
        
        // Cargar preview inicial con datos reales
        updatePreview();

    } catch (e) {
        document.getElementById('diff-tbody').innerHTML = `<tr><td colspan="3" class="text-danger">Error: ${e.message}</td></tr>`;
        document.getElementById('summary-badges').innerHTML = '';
    }
}

// 3. Coords & Live Preview
function renderElementsTable() {
    const dataScript = document.getElementById('elements-data');
    if(!dataScript) return;
    const elements = JSON.parse(dataScript.textContent);
    const tbody = document.getElementById('elements-tbody');
    tbody.innerHTML = '';
    
    // Función auxiliar para crear inputs que actualicen el preview al cambiar
    // Ya no bloqueamos ningún input. Si no existía, arranca en 0 o vacío, pero es editable.
    const createInput = (val, key, className, placeholder = '') => {
        const inp = document.createElement('input');
        inp.type = 'number';
        inp.className = `form-control form-control-sm bg-dark text-white border-secondary ${className}`;
        inp.dataset.key = key;
        if(placeholder) {
            inp.placeholder = placeholder;
            inp.style.width = '55px';
        }
        inp.value = val !== undefined ? val : (placeholder ? '' : '0');
        
        // Deshabilitar solo si no es de un tipo lógico (ej. no pedir Height a un Label de texto)
        // Pero X, Y y Font quedan abiertos para todos.
        const isRect = key.startsWith('rect_');
        if (!isRect && (className === 'el-w' || className === 'el-h')) {
            inp.disabled = true;
            inp.value = '';
            inp.style.display = 'none';
        } else {
            inp.addEventListener('input', updatePreview);
        }
        return inp;
    };

    // Asegurarnos de que el orden de pintado sea lógico en la tabla
    const orderedKeys = [
        'col1_np', 'col1_folio',
        'titulo', 'fecha', 'folio_horizontal', 'lbl_clave', 'rect_clave', 'val_clave',
        'lbl_unidad', 'rect_unidad', 'val_unidad', 'lbl_empaque', 'rect_empaque', 'val_empaque',
        'lbl_almacen', 'rect_almacen', 'val_almacen',
        'lbl_cantidad', 'rect_cantidad', 'val_cantidad', 'lbl_contado', 'rect_contado', 'val_contado'
    ];

    // Iterar sobre llaves ordenadas, o todas si hay nuevas
    const keysToRender = new Set([...orderedKeys, ...Object.keys(elements)]);

    for (const key of keysToRender) {
        const val = elements[key] || {};
        const tr = document.createElement('tr');
        
        // Checkbox de Visibilidad (enabled)
        const tdVis = document.createElement('td');
        const chk = document.createElement('input');
        chk.type = 'checkbox';
        chk.className = 'form-check-input el-chk';
        chk.dataset.key = key;
        chk.checked = val.enabled !== false; // true por defecto
        chk.addEventListener('change', updatePreview);
        tdVis.appendChild(chk);

        // Element Name
        const tdName = document.createElement('td');
        tdName.textContent = key;
        tdName.className = 'text-start fw-bold text-info';
        
        // X Add
        const tdX = document.createElement('td');
        tdX.appendChild(createInput(val.x_add, key, 'el-x'));
        
        // Y Offset
        const tdY = document.createElement('td');
        tdY.appendChild(createInput(val.y_offset, key, 'el-y'));
        
        // Width / Height
        const tdWH = document.createElement('td');
        tdWH.className = 'd-flex gap-1 justify-content-center';
        tdWH.appendChild(createInput(val.w, key, 'el-w', 'W'));
        tdWH.appendChild(createInput(val.h, key, 'el-h', 'H'));
        
        // Font Add
        const tdF = document.createElement('td');
        tdF.appendChild(createInput(val.font_size_add, key, 'el-f'));
        
        tr.appendChild(tdVis);
        tr.appendChild(tdName);
        tr.appendChild(tdX);
        tr.appendChild(tdY);
        tr.appendChild(tdWH);
        tr.appendChild(tdF);
        
        tbody.appendChild(tr);
    }
    
    // Configurar listener para variables maestras
    document.getElementById('coord-base-y').addEventListener('input', updatePreview);
    document.getElementById('coord-global-y').addEventListener('input', updatePreview);
    document.getElementById('coord-font').addEventListener('input', updatePreview);
    document.getElementById('coord-c1-x').addEventListener('input', updatePreview);
    document.getElementById('coord-c2-x').addEventListener('input', updatePreview);
    document.getElementById('coord-c3-x-offset').addEventListener('input', updatePreview);
    
    document.getElementById('coord-adj-m1').addEventListener('input', updatePreview);
    document.getElementById('coord-adj-m2').addEventListener('input', updatePreview);
    document.getElementById('coord-adj-m3').addEventListener('input', updatePreview);
    updatePreview();
}


function updatePreview() {
    const canvas = document.getElementById('preview-canvas');
    if(!canvas) return;
    
    // Limpiar canvas
    canvas.innerHTML = '';
    
    // Variables maestras
    const baseFontSize = parseFloat(document.getElementById('coord-font').value) || 10;
    
    // El usuario proporcionó 98 y 272 como base
    const base_y = parseFloat(document.getElementById('coord-base-y').value) || 98;
    const global_row_offset_y = parseFloat(document.getElementById('coord-global-y').value) || 272;
    
    // Ajustes manuales independientes
    const adj_m1 = parseFloat(document.getElementById('coord-adj-m1').value) || 0;
    const adj_m2 = parseFloat(document.getElementById('coord-adj-m2').value) || 0;
    const adj_m3 = parseFloat(document.getElementById('coord-adj-m3').value) || 0;
    
    // Posiciones Y exactas (Fórmula Lineal + Ajuste Manual Individual)
    const exact_y_positions = [
        base_y + adj_m1, 
        base_y + global_row_offset_y + adj_m2, 
        base_y + (global_row_offset_y * 2) + adj_m3
    ]; 

    const c1_x = parseFloat(document.getElementById('coord-c1-x').value) || 30;
    const c2_x = parseFloat(document.getElementById('coord-c2-x').value) || 230;
    const c3_x = c2_x + (parseFloat(document.getElementById('coord-c3-x-offset').value) || 200);
    
    // El punto 0,0 en PDF es abajo izquierda. En CSS es arriba izquierda.
    const canvasHeight = canvas.clientHeight; 
    
    const tbody = document.getElementById('elements-tbody');
    const rows = tbody.querySelectorAll('tr');
    
    // Leer valores de la tabla
    const configElements = {};
    rows.forEach(row => {
        const chk = row.querySelector('.el-chk');
        if(!chk) return;
        const key = chk.dataset.key;
        configElements[key] = {
            enabled: chk.checked,
            x_add: parseFloat(row.querySelector('.el-x').value) || 0,
            y_offset: parseFloat(row.querySelector('.el-y').value) || 0,
            f_add: parseFloat(row.querySelector('.el-f').value) || 0,
            w: parseFloat(row.querySelector('.el-w').value) || 0,
            h: parseFloat(row.querySelector('.el-h').value) || 0
        };
    });

    // Mapeo de textos y valores dummy por llave
    const getDummyText = (key, isCol3, row_idx) => {
        const folioStr = `0000${row_idx + 1}`;
        if(key === 'col1_np') return 'M13125';
        if(key === 'col1_folio') return folioStr;
        if(key === 'titulo') return isCol3 ? 'PRIMER CONTEO' : 'SEGUNDO CONTEO';
        if(key === 'fecha') return 'SEPTIEMBRE 2026';
        if(key === 'folio_horizontal') return `${folioStr}`;
        if(key === 'lbl_clave') return 'Clave:';
        if(key === 'val_clave') return 'M13125';
        if(key === 'lbl_unidad') return 'Unidad:';
        if(key === 'val_unidad') return 'PZA';
        if(key === 'lbl_empaque') return 'Empaque:';
        if(key === 'val_empaque') return 'CAJA';
        if(key === 'lbl_almacen') return 'Almacén:';
        if(key === 'val_almacen') return 'NAVE A';
        if(key === 'lbl_cantidad') return 'Cantidad:';
        if(key === 'val_cantidad') return '1,500.00';
        if(key === 'lbl_contado') return 'Contado por:';
        if(key === 'val_contado') return 'JUAN P.';
        return '';
    };

    // Iteramos por las 3 filas
    for (let row_idx = 0; row_idx < 3; row_idx++) {
        const current_y = exact_y_positions[row_idx];
        // Convertimos current_y (desde abajo) a CSS Top (desde arriba)
        const cssTopZero = canvasHeight - current_y;

        // 1. Dibujar Columna 1 (Rotada)
        const col1Container = document.createElement('div');
        col1Container.style.position = 'absolute';
        col1Container.style.left = `${c1_x}px`;
        col1Container.style.top = `${cssTopZero}px`;
        col1Container.style.width = '0px';
        col1Container.style.height = '0px';
        col1Container.style.transformOrigin = '0 0';
        col1Container.style.transform = 'rotate(-90deg)'; 
        canvas.appendChild(col1Container);

        // Función para dibujar un bloque
        const drawConteoBlock = (baseX, isCol3) => {
            for (const [key, val] of Object.entries(configElements)) {
                if (val.enabled === false) continue; // Si está apagado el check, no dibujarlo

                const isCol1Element = key.startsWith('col1_');
                if (isCol1Element && baseX !== null) continue;
                if (!isCol1Element && baseX === null) continue;

                const el = document.createElement('div');
                el.style.position = 'absolute';
                
                if (isCol1Element) {
                    el.style.left = `${val.x_add}px`;
                    el.style.transform = 'translateX(-50%)'; 
                    el.style.top = `${ -val.y_offset - (baseFontSize + val.f_add) }px`;
                    
                    el.textContent = getDummyText(key, false, row_idx);
                    el.style.fontFamily = 'Helvetica, Arial, sans-serif';
                    el.style.fontSize = `${baseFontSize + val.f_add}px`;
                    el.style.fontWeight = 'bold';
                    el.style.color = 'black';
                    el.style.whiteSpace = 'nowrap';
                    
                    col1Container.appendChild(el);
                    continue;
                }

                // Elementos Normales
                el.style.left = `${baseX + val.x_add}px`;
                
                if (key.startsWith('rect_')) {
                    el.style.width = `${val.w}px`;
                    el.style.height = `${val.h}px`;
                    el.style.border = '1px solid black';
                    el.style.backgroundColor = 'transparent';
                    
                    el.style.top = `${cssTopZero - val.y_offset - val.h}px`;
                    
                } else {
                    const isTitle = key === 'titulo';
                    const isFolio = key === 'folio_horizontal';
                    const isCenteredVal = ['val_unidad', 'val_empaque', 'val_cantidad', 'val_contado'].includes(key);

                    el.textContent = getDummyText(key, isCol3, row_idx);
                    el.style.fontFamily = 'Helvetica, Arial, sans-serif';
                    el.style.fontSize = `${baseFontSize + val.f_add}px`;
                    el.style.color = 'black';
                    el.style.whiteSpace = 'nowrap';
                    if(isTitle || isFolio) el.style.fontWeight = 'bold';
                    
                    el.style.top = `${cssTopZero - val.y_offset - (baseFontSize + val.f_add)}px`;
                    
                    if (isCenteredVal) {
                        el.style.transform = 'translateX(-50%)'; 
                    }

                    if (key.startsWith('val_')) {
                        el.style.zIndex = 10;
                    }
                }
                canvas.appendChild(el);
            }
        };

        // Dibujar elementos de la fila actual
        drawConteoBlock(null, false); // Col 1
        drawConteoBlock(c2_x, false); // Col 2
        drawConteoBlock(c3_x, true);  // Col 3
    }
}

async function saveCoords() {
        const data = {
            base_y: parseFloat(document.getElementById('coord-base-y').value),
            global_row_offset_y: parseFloat(document.getElementById('coord-global-y').value),
            ajuste_m1_y: parseFloat(document.getElementById('coord-adj-m1').value) || 0,
            ajuste_m2_y: parseFloat(document.getElementById('coord-adj-m2').value) || 0,
            ajuste_m3_y: parseFloat(document.getElementById('coord-adj-m3').value) || 0,
            font_size: parseFloat(document.getElementById('coord-font').value),
            col1: { x: parseFloat(document.getElementById('coord-c1-x').value) },
            col2: { x: parseFloat(document.getElementById('coord-c2-x').value) },
            col3: { x_offset_from_col2: parseFloat(document.getElementById('coord-c3-x-offset').value) },
            elements: {}
        };
        
        // Harvest elements from table
        const tbody = document.getElementById('elements-tbody');
        const rows = tbody.querySelectorAll('tr');
        rows.forEach(row => {
            const key = row.querySelector('.el-chk').dataset.key;
            data.elements[key] = { enabled: row.querySelector('.el-chk').checked };
            
            const x = row.querySelector('.el-x');
            if(!x.disabled && x.value !== '') data.elements[key].x_add = parseFloat(x.value);
            
            const y = row.querySelector('.el-y');
            if(!y.disabled && y.value !== '') data.elements[key].y_offset = parseFloat(y.value);
            
            const w = row.querySelector('.el-w');
            if(w && w.value !== '') data.elements[key].w = parseFloat(w.value);
            
            const h = row.querySelector('.el-h');
            if(h && h.value !== '') data.elements[key].h = parseFloat(h.value);
            
            const f = row.querySelector('.el-f');
            if(!f.disabled && f.value !== '') data.elements[key].font_size_add = parseFloat(f.value);
        });

        await fetch('/api/config/coords', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        alert('Configuración de Plantilla guardada');
    }

// 4. CUPS
async function loadPrinters() {
    const select = document.getElementById('printer-select');
    select.innerHTML = '<option>Cargando...</option>';
    const res = await fetch('/api/printers');
    const json = await res.json();
    
    select.innerHTML = '';
    if(json.printers.length === 0) {
        select.innerHTML = '<option value="">No hay impresoras (o error CUPS)</option>';
        return;
    }
    json.printers.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p;
        opt.textContent = p;
        select.appendChild(opt);
    });
}

async function saveCupsConfig() {
    const data = {
        name: document.getElementById('printer-select').value,
        batch_size: parseInt(document.getElementById('printer-batch').value),
        sleep_time: parseInt(document.getElementById('printer-sleep').value),
    };
    await fetch('/api/config/printer', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(data)
    });
    alert('Configuración CUPS guardada');
}

async function testDummyPrint() {
    alert("Enviando impresión de prueba...");
    const res = await fetch('/api/print/dummy', {method: 'POST'});
    const json = await res.json();
    if (json.success) {
        alert("Enviado correctamente a CUPS");
    } else {
        alert("Error: " + json.error);
    }
}

// Ejecuciones
let dtPool = null;
let dtCruce = null;
let dtQuery = null;

let dtExistencias = null;



async function executeExistencias() {
    document.getElementById('btn-exec-existencias').disabled = true;
    addLog("[MODULO 2] Iniciando extracción de Existencias (Query Secundario)...");
    
    try {
        const res = await fetch('/api/execute/existencias', { method: 'POST' });
        const json = await res.json();
        if(json.success) {
            addLog(`[EXITO] Extracción finalizada. ${json.count} registros obtenidos y guardados.`);
            loadTables();
        } else {
            addLog(`[ERROR] Falló la extracción: ${json.error}`, true);
        }
    } catch(e) {
        addLog(`[ERROR] Error de conexión: ${e.message}`, true);
    } finally {
        document.getElementById('btn-exec-existencias').disabled = false;
    }
}


let currentFlujo = 'flujo1_excel';

function switchFlujo(flujo) {
    currentFlujo = flujo;
    checkPDFs(); // Update UI for the new active flow
}

async function executeProcess(flujo) {
    const isF1 = flujo === 'flujo1_excel';
    const isF3 = flujo === 'flujo3_vacios';
    const btnId = isF1 ? 'btn-execute-f1' : (isF3 ? 'btn-execute-f3' : 'btn-execute-f2');
    
    let endpoint = isF1 ? '/api/execute/stream' : '/api/execute/stream_ubicaciones';
    
    document.getElementById('console-output').innerHTML = ''; 
    
    if (isF1) {
        const fileInput = document.getElementById('excel-run-file');
        if (!fileInput || !fileInput.files[0]) return alert("Selecciona un archivo Excel definitivo");
        const formData = new FormData();
        formData.append('file', fileInput.files[0]);
        document.getElementById(btnId).disabled = true;
        addLog(`[INICIO] Subiendo archivo para Flujo 1...`);
        try {
            const upRes = await fetch('/api/execute/upload', { method: 'POST', body: formData });
            const upJson = await upRes.json();
            if(!upJson.success) throw new Error(upJson.error);
        } catch (e) {
            addLog(`[ERROR] ${e.message}`, true);
            document.getElementById(btnId).disabled = false;
            return;
        }
    } else if (isF3) {
        const qty = parseInt(document.getElementById('input-qty-vacios').value);
        if(!qty || qty <= 0) return alert("Ingresa una cantidad válida mayor a 0");
        document.getElementById(btnId).disabled = true;
        endpoint = `/api/execute/stream_vacios?qty=${qty}`;
        addLog(`[INICIO] Arrancando Flujo 3: Generación de ${qty} marbetes en blanco...`);
    } else {
        document.getElementById(btnId).disabled = true;
        addLog(`[INICIO] Arrancando Flujo 2 (Ubicaciones) desde Query...`);
    }

    const evtSource = new EventSource(endpoint);
    evtSource.onmessage = function(e) {
        const data = JSON.parse(e.data);
        addLog(data.msg, data.status === 'error');
        
        if (data.status === 'done' || data.status === 'error') {
            evtSource.close();
            document.getElementById(btnId).disabled = false;
            if(data.status === 'done') {
                if(data.txn) addLog(`[INFO] Transacción generada: ${data.txn}`);
                checkPDFs();
                loadTables();
            }
        }
    };
    evtSource.onerror = function() {
        evtSource.close();
        document.getElementById(btnId).disabled = false;
        addLog("[ERROR] Conexión perdida con el servidor.", true);
    };
}


async function loadTables() {
    const res = await fetch('/api/data/logs');
    const data = await res.json();
    
    if(dtPool) dtPool.destroy();
    if(dtCruce) dtCruce.destroy();
    if(dtQuery) dtQuery.destroy();
    if(dtExistencias) dtExistencias.destroy();
    
    const poolTbody = document.querySelector('#table-pool tbody');
    if(poolTbody && data.cruce) {
        poolTbody.innerHTML = data.cruce.map(r => `<tr>
            <td><strong class="text-warning">${r.folio || '-'}</strong></td>
            <td>${r.np}</td><td>${r.sheet}</td>
            <td><div style="max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${r.descripcion}">${r.descripcion}</div></td>
            <td>${r.unidad}</td><td>${r.empaque}</td><td>${r.almacen}</td>
            <td>${r.cantidad}</td><td>${r.contado_por}</td>
        </tr>`).join('');
    }

    const cruceTbody = document.querySelector('#table-cruce tbody');
    if(cruceTbody && data.cruce) {
        cruceTbody.innerHTML = data.cruce.map(r => `<tr>
            <td>${r.np}</td><td>${r.sheet}</td>
            <td><div style="max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${r.descripcion}">${r.descripcion}</div></td>
            <td>${r.unidad}</td><td>${r.empaque}</td><td>${r.almacen}</td>
            <td>${r.cantidad}</td><td>${r.contado_por}</td>
            <td><span class="badge bg-success">${r.estado}</span></td>
        </tr>`).join('');
    }
    
    const queryTbody = document.querySelector('#table-query tbody');
    if(queryTbody && data.query) {
        queryTbody.innerHTML = data.query.map(r => `<tr>
            <td>${r.np}</td>
            <td><div style="max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${r.descripcion}">${r.descripcion}</div></td>
            <td>${r.unidad}</td><td>${r.empaque}</td><td>${r.almacen}</td>
            <td>${r.cantidad}</td><td>${r.contado_por}</td>
        </tr>`).join('');
    }
    
    // Render dynamic table for existencias
    if (data.existencias && data.existencias.length > 0) {
        const existHead = document.getElementById('table-existencias-head');
        const existTbody = document.querySelector('#table-existencias tbody');
        
        // Get columns from first row keys
        const columns = Object.keys(data.existencias[0]);
        if(existHead) existHead.innerHTML = columns.map(c => `<th>${c}</th>`).join('');
        
        if(existTbody) {
            existTbody.innerHTML = data.existencias.map(r => `<tr>
                ${columns.map(c => `<td><div style="max-width: 250px; overflow: hidden; text-overflow: ellipsis;" title="${r[c]}">${r[c] !== null && r[c] !== undefined ? r[c] : ''}</div></td>`).join('')}
            </tr>`).join('');
        }
    } else {
        const existHead = document.getElementById('table-existencias-head');
        if(existHead) existHead.innerHTML = '<th>Sin Datos</th>';
        const existTbody = document.querySelector('#table-existencias tbody');
        if(existTbody) existTbody.innerHTML = '<tr><td>No hay registros de existencias. Ejecuta el Módulo 2.</td></tr>';
    }

    
    if(document.getElementById('table-pool')) {
        dtPool = $('#table-pool').DataTable({
            pageLength: 50, scrollX: true, language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' }
        });
    }
    if(document.getElementById('table-cruce')) {
        dtCruce = $('#table-cruce').DataTable({
            pageLength: 50, scrollX: true, language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' }
        });
    }
    if(document.getElementById('table-query')) {
        dtQuery = $('#table-query').DataTable({
            pageLength: 50, scrollX: true, language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' }
        });
    }
    if(document.getElementById('table-existencias')) {
        dtExistencias = $('#table-existencias').DataTable({
            pageLength: 50, scrollX: true, language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' }
        });
    }
}

async function printAction(action) {
    if(action === 'pause') addLog("[ACCION] Usuario solicitó PAUSAR la impresión.");
    if(action === 'resume') {
        addLog("[ACCION] Usuario solicitó REANUDAR la impresión.");
        document.getElementById('ui-print-status').textContent = 'Estado: Imprimiendo...';
        document.getElementById('ui-print-status').className = 'badge bg-success p-2';
    }
    
    await fetch('/api/print/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action})
    });
}

async function addPaperUI() {
    const qty = prompt("¿Cuántas hojas extras vas a añadir a la bandeja?");
    if(qty && !isNaN(parseInt(qty))) {
        await fetch('/api/print/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'add_paper', count: parseInt(qty)})
        });
        addLog(`[ACCION] Se agregaron ${qty} hojas al contador virtual.`);
    }
}





async function updateNextFolioUI() {
    try {
        const r = await fetch('/api/pool/next_folio');
        const d = await r.json();
        const lbl = document.getElementById('lbl-next-folio');
        if(lbl) lbl.textContent = d.next_folio;
    } catch(e){}
}

async function checkPDFs() {
    updateNextFolioUI();

    const elCount = document.getElementById('pdf-count');
    if(!elCount) return;

    try {
        const res = await fetch(`/api/pdfs/status?flujo=${currentFlujo}`);
        const json = await res.json();
        
        elCount.textContent = json.count;
        document.getElementById('folio-count').textContent = json.folios_aprox;
        
        const hasPdfs = json.count > 0;
        const btnPrint = document.getElementById('btn-print');
        if(btnPrint) {
            btnPrint.disabled = !hasPdfs;
            btnPrint.style.display = 'block'; 
        }

        const txnRow = document.getElementById('txn-row');
        const txnLabel = document.getElementById('txn-label');
        if(txnRow && txnLabel) {
            if(hasPdfs && json.transaction) {
                txnLabel.textContent = json.transaction;
                txnRow.classList.remove('d-none');
            } else {
                txnLabel.textContent = '—';
                txnRow.classList.add('d-none');
            }
        }
        
        const printControls = document.getElementById('print-controls');
        if(printControls) printControls.style.display = 'none'; 
        
        const statusBadge = document.getElementById('ui-print-status');
        if(statusBadge) {
            if(hasPdfs) {
                 statusBadge.textContent = 'Estado: Listo (' + (currentFlujo === 'flujo1_excel' ? 'V. Ubicaciones' : 'Ubicaciones') + ')';
                 statusBadge.className = 'badge bg-success p-2';
            } else {
                 statusBadge.textContent = 'Estado: Sin Archivos';
                 statusBadge.className = 'badge bg-secondary p-2';
            }
        }
    } catch(e) {
        console.error("Error checking PDFs:", e);
    }
}

// Init
window.onload = () => {
    if (document.getElementById('printer-select')) loadPrinters();
    if (document.getElementById('pdf-count')) checkPDFs();
    if (document.getElementById('elements-data')) renderElementsTable();
    if (document.getElementById('table-pool')) loadTables();
    if (document.getElementById('table-pool-final')) loadPoolFinal();
    if (document.getElementById('table-matrix')) loadMatriz();
    if (document.getElementById('table-auditoria')) loadAuditoria();
};


async function purgePDFs(flujo) {
    if(!confirm(`¿Seguro que quieres vaciar los PDFs del flujo: ${flujo === 'flujo1_excel' ? 'Varias Ubicaciones' : 'Ubicaciones'}?`)) return;
    try {
        await fetch('/api/pdfs/purge', {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({flujo: flujo})
        });
        addLog(`[SISTEMA] Carpeta de PDFs (${flujo}) vaciada correctamente.`);
        checkPDFs(); 
    } catch(e) {
        addLog(`[ERROR] No se pudo purgar la carpeta: ${e.message}`, true);
    }
}



let statePoller = null;
let printEventSource = null;

async function startPrinting() {
    const paperQty = prompt("¿Cuántas hojas de papel tamaño carta has cargado físicamente en la bandeja?");
    if(!paperQty || isNaN(parseInt(paperQty))) return alert("Operación cancelada. Ingresa un número válido.");
    
    await fetch('/api/print/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'add_paper', count: parseInt(paperQty)})
    });

    if(!confirm(`Se han registrado ${paperQty} hojas. ¿Iniciar envío masivo a CUPS?`)) return;
    
    document.getElementById('btn-print').disabled = true;
    document.getElementById('btn-print').style.display = 'none'; // hide main button
    document.getElementById('print-controls').style.display = 'flex'; // show controls
    
    document.getElementById('btn-pause').disabled = false;
    document.getElementById('btn-resume').disabled = true;
    document.getElementById('btn-stop').disabled = false;
    document.getElementById('btn-paper').disabled = false;
    
    document.getElementById('ui-print-status').textContent = 'Estado: Imprimiendo...';
    document.getElementById('ui-print-status').className = 'badge bg-success p-2';
    
    addLog("[IMPRESION] Iniciando rutina de impresión CUPS...");

    if (printEventSource) printEventSource.close();
    printEventSource = new EventSource(`/api/print/start?flujo=${currentFlujo}`);
    
    printEventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);
        if(data.msg) addLog(data.msg, data.status === 'error');
        
        if (data.status === 'pause') {
            document.getElementById('ui-print-status').textContent = 'Estado: PAUSADO';
            document.getElementById('ui-print-status').className = 'badge bg-warning text-dark p-2';
            document.getElementById('btn-pause').disabled = true;
            document.getElementById('btn-resume').disabled = false;
        } else if (data.status === 'done' || data.status === 'error') {
            printEventSource.close();
            resetPrintUI(data.status);
            if(data.status === 'done') addLog("[EXITO] IMPRESIÓN MASIVA FINALIZADA.");
        }
    };
    
    // Start polling state
    if(statePoller) clearInterval(statePoller);
    statePoller = setInterval(async () => {
        try {
            const res = await fetch('/api/print/state');
            const st = await res.json();
            document.getElementById('ui-paper-count').textContent = st.paper_count;
        } catch(e){}
    }, 2000);
}

function resetPrintUI(finalStatus) {
    if(statePoller) clearInterval(statePoller);
    document.getElementById('btn-print').style.display = 'block'; // show main button again
    document.getElementById('print-controls').style.display = 'none'; // hide controls
    
    if(finalStatus === 'error') {
        document.getElementById('ui-print-status').textContent = 'Estado: ERROR/DETENIDO';
        document.getElementById('ui-print-status').className = 'badge bg-danger p-2';
    } else {
        document.getElementById('ui-print-status').textContent = 'Estado: Finalizado';
        document.getElementById('ui-print-status').className = 'badge bg-secondary p-2';
    }
}

async function printAction(action) {
    if(action === 'pause') {
        addLog("[ACCION] Usuario solicitó PAUSAR la impresión.");
        document.getElementById('btn-pause').disabled = true;
        document.getElementById('btn-resume').disabled = false;
    }
    if(action === 'resume') {
        addLog("[ACCION] Usuario solicitó REANUDAR la impresión.");
        document.getElementById('ui-print-status').textContent = 'Estado: Imprimiendo...';
        document.getElementById('ui-print-status').className = 'badge bg-success p-2';
        document.getElementById('btn-pause').disabled = false;
        document.getElementById('btn-resume').disabled = true;
    }
    if(action === 'stop') {
        addLog("[ACCION] Usuario solicitó DETENER (ABORTAR) la impresión.");
        if (printEventSource) printEventSource.close();
        resetPrintUI('error');
    }
    
    await fetch('/api/print/action', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action})
    });
}

async function addPaperUI() {
    const qty = prompt("¿Cuántas hojas extras vas a añadir a la bandeja?");
    if(qty && !isNaN(parseInt(qty))) {
        await fetch('/api/print/action', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({action: 'add_paper', count: parseInt(qty)})
        });
        addLog(`[ACCION] Se agregaron ${qty} hojas al contador virtual.`);
    }
}



async function copyToPoolFinal() {
    if(!confirm("¿Estás seguro de que la impresión fue exitosa y quieres guardar estos folios en el historial permanente (Pool Final)?")) return;
    
    try {
        const res = await fetch('/api/pool/copy', { method: 'POST' });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Ocurrió un error al contactar al servidor: " + e.message);
    }
}

async function emptyPoolFinal() {
    const rows = poolData || [];
    if(rows.length === 0) return alert("El Pool Final ya está vacío.");
    const code = prompt(`⚠️ ACCIÓN CRÍTICA - VACIAR TODO EL POOL FINAL\n\nSe eliminarán TODOS los ${rows.length} marbetes cerrados.\nAntes se guardará un respaldo automático.\n\nPara confirmar escribe la palabra:\n\nVACIAR\n\n(escribe exactamente así, en mayúsculas)`);
    if(code === null) return;
    if(code !== 'VACIAR') {
        return alert("❌ Cancelado: la palabra de confirmación no coincide. No se eliminó nada.");
    }
    if(!confirm(`¿Confirmas la eliminación TOTAL de los ${rows.length} marbetes del Pool Final?`)) return;
    try {
        const res = await fetch('/api/pool/empty', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'pool'}) });
        const json = await res.json();
        if(json.success) {
            alert(`✅ Pool Final vaciado: ${json.removed} registro(s) eliminado(s). Respaldo guardado en Pool Final Backup.`);
            await loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

let dtPoolFinal = null;
let poolData = [];

async function loadPoolFinal() {
    try {
        const res = await fetch('/api/pool/data');
        const json = await res.json();
        poolData = json.data;
        
        const tbody = document.querySelector('#table-pool-final tbody');
        if(!tbody) return;
        
        // Render initial data
        renderPoolTable(poolData);
        
        // Populate Selects for Filtering
        const sheets = [...new Set(poolData.map(item => item.sheet))].filter(Boolean).sort();
        const almacenes = [...new Set(poolData.map(item => item.almacen))].filter(Boolean).sort();
        const empaques = [...new Set(poolData.map(item => item.empaque))].filter(Boolean).sort();
        const ubicaciones = [...new Set(poolData.map(item => item.almacen_pool))].filter(Boolean).sort();
        
        const selSheet = document.getElementById('filter-sheet');
        selSheet.innerHTML = '<option value="">-- Mostrar Todas --</option>' + sheets.map(s => `<option value="${s}">${s}</option>`).join('');
        
        const selAlmacen = document.getElementById('filter-almacen');
        selAlmacen.innerHTML = '<option value="">-- Mostrar Todas --</option>' + almacenes.map(a => `<option value="${a}">${a}</option>`).join('');

        const selEmpaque = document.getElementById('filter-empaque');
        selEmpaque.innerHTML = '<option value="">-- Mostrar Todos --</option>' + empaques.map(e => `<option value="${e}">${e}</option>`).join('');

        const selUbicacion = document.getElementById('filter-ubicacion');
        selUbicacion.innerHTML = '<option value="">-- Mostrar Todas --</option>' + ubicaciones.map(u => `<option value="${u}">${u}</option>`).join('');
        
    } catch(e) {
        console.error(e);
    }
}

function renderPoolTable(data) {
    if(dtPoolFinal) {
        dtPoolFinal.destroy();
    }
    
    const tbody = document.querySelector('#table-pool-final tbody');
    tbody.innerHTML = data.map(r => {
if(poolEditMode && poolEditValues[r.folio]) {
            return `<tr>
                <td class="text-center"><input type="checkbox" class="chk-pool-row" value="${_escPool(r.folio)}" data-sheet="${_escPool(r.sheet)}" data-almacen="${_escPool(r.almacen)}"></td>
                <td><strong class="text-warning">${_escPool(r.folio)}</strong></td>
                ${renderPoolEditRow(r)}
                <td class="text-nowrap small">${_escPool(r.auditoria || '')}</td>
            </tr>`;
        }
        return `<tr>
            <td class="text-center"><input type="checkbox" class="chk-pool-row" value="${_escPool(r.folio)}" data-sheet="${_escPool(r.sheet)}" data-almacen="${_escPool(r.almacen)}"></td>
            <td><strong class="text-warning">${_escPool(r.folio)}</strong></td>
            <td>${_escPool(r.np)}</td><td>${_escPool(r.sheet)}</td>
            <td><div style="max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${_escPool(r.descripcion)}">${_escPool(r.descripcion)}</div></td>
            <td>${_escPool(r.unidad)}</td><td>${_escPool(r.empaque)}</td><td>${_escPool(r.almacen)}</td>
            <td title="${_escPool(r.almacen_pool || '')}">${_escPool(r.almacen_pool || '')}</td>
            <td class="text-center">${variasBadge(r)}</td>
            <td class="text-center">${layoutBadge(r)}</td>
            <td>${_escPool(r.cantidad)}</td><td>${_escPool(r.contado_por)}</td>
            <td class="text-nowrap small">${_escPool(r.auditoria || '')}</td>
        </tr>`;
    }).join('');
    
    // Checkbox master reset
    const chkAll = document.getElementById('chk-all-pool');
    if(chkAll) chkAll.checked = false;
    
    dtPoolFinal = $('#table-pool-final').DataTable({
        pageLength: 50, scrollX: true, language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
        order: [[1, 'desc']], // Order by folio (index 1 now since checkbox is 0)
        columnDefs: [ { orderable: false, targets: 0 } ] // Disbale sort on checkbox
    });
    dtPoolFinal.on('draw.dt', applyPoolEditInputs);
}

function applyPoolFilters() {
    const sheet = document.getElementById('filter-sheet').value;
    const almacen = document.getElementById('filter-almacen').value;
    const empaque = document.getElementById('filter-empaque').value;
    const ubicacion = document.getElementById('filter-ubicacion').value;
    const varias = document.getElementById('filter-varias').value;
    const desc = document.getElementById('filter-desc').value.trim().toLowerCase();
    const np = document.getElementById('filter-np').value.trim().toLowerCase();
    
    let filtered = poolData;
    if(sheet) filtered = filtered.filter(r => r.sheet === sheet);
    if(almacen) filtered = filtered.filter(r => r.almacen === almacen);
    if(empaque) filtered = filtered.filter(r => r.empaque === empaque);
    if(ubicacion) filtered = filtered.filter(r => r.almacen_pool === ubicacion);
    if(varias !== '') filtered = filtered.filter(r => String(r.varias_ubicaciones) === varias);
    if(desc) filtered = filtered.filter(r => (r.descripcion || '').toLowerCase().includes(desc));
    if(np) filtered = filtered.filter(r => (r.np || '').toLowerCase().includes(np));
    
    renderPoolTable(filtered);
}

function toggleAllPool(source) {
    // We only select the checkboxes currently rendered in the table by DataTables
    const checkboxes = document.querySelectorAll('.chk-pool-row');
    for (let i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = source.checked;
    }
}

async function deleteSelectedPool() {
    // DataTables might hide checkboxes on other pages.
    // To be surgical and true to "select what is filtered", we use DataTables API to get all nodes matching the filter
    
    if(!dtPoolFinal) return;
    
    const selectedNodes = dtPoolFinal.$('input[type="checkbox"].chk-pool-row:checked');
    if (selectedNodes.length === 0) return alert("No hay registros seleccionados para eliminar.");
    
    let folios = [];
    let sheetsSet = new Set();
    let almacenesSet = new Set();
    
    selectedNodes.each(function() {
        folios.push(this.value);
        sheetsSet.add(this.dataset.sheet);
        almacenesSet.add(this.dataset.almacen);
    });
    
    const sheetsStr = Array.from(sheetsSet).join(', ');
    const almacenesStr = Array.from(almacenesSet).join(', ');
    
    const msg = `⚠️ ADVERTENCIA ⚠️

¿Estás seguro de ELIMINAR ${folios.length} registros?

Proceden de:
- Pestañas: [${sheetsStr}]
- Ubicaciones: [${almacenesStr}]`;
    
    if(!confirm(msg)) return;
    
    try {
        const res = await fetch('/api/pool/delete_selected', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({folios})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            loadPoolFinal(); // Reload data from backend
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

function exportPoolExcel() {
    window.location.href = '/api/pool/export';
}

function exportPoolCSV() {
    window.location.href = '/api/pool/export_csv';
}

function exportWmsExcel() {
    window.location.href = '/api/wms/export';
}
function exportSaldosExcel() {
    window.location.href = '/api/saldos/export';
}
function exportEtqmangExcel() {
    window.location.href = '/api/etqmang/export';
}
function exportEptsExcel() {
    window.location.href = '/api/epts/export';
}
function exportEptsComparativoExcel() {
    window.location.href = '/api/epts/comparativo/export';
}
async function generarAjusteCarga() {
    const btn = document.getElementById('btn-af-ajuste-carga') || document.getElementById('btn-ajuste-carga');
    if(btn) { btn.disabled = true; btn.textContent = '⌛ Generando...'; }
    try {
        const res = await fetch('/api/epts/generar_ajuste_carga', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'analisis_final'})
        });
        const json = await res.json();
        const box = document.getElementById('af-ajuste-carga-info');
        if(json.ok) {
            const txt = `✅ ${json.filas} líneas al archivo (AUMENTO/DISMINUYO/SIN CAMBIO) · ⛔ ${json.bajas} no pasaron (BAJA) · Total ${json.total} · archivocargaetp/${json.ruta}`;
            if(box) { box.className = 'alert alert-success d-block py-2 small fw-bold'; box.textContent = txt; }
            alert(`✅ ${json.msg}\n${txt}`);
        } else {
            const txt = '❌ ERROR: ' + json.msg;
            if(box) { box.className = 'alert alert-danger d-block py-2 small fw-bold'; box.textContent = txt; }
            alert(txt);
        }
    } catch(e) {
        const txt = '❌ Error: ' + e.message;
        const box = document.getElementById('af-ajuste-carga-info');
        if(box) { box.className = 'alert alert-danger d-block py-2 small fw-bold'; box.textContent = txt; }
        alert(txt);
    } finally {
        if(btn) { btn.disabled = false; btn.textContent = '📄 Generar ajuste-ept-carga'; }
    }
}

async function generarPropCliCarga() {
    await generarPropCli('carga', 'btn-af-propcli-carga', 'af-propcli-carga-info', 'acepta AUMENTO/DISMINUYO', 'archivocargapropcliente');
}
async function generarPropCliBaja() {
    await generarPropCli('baja', 'btn-af-propcli-baja', 'af-propcli-baja-info', 'BAJA', 'archivobajaprocliente');
}

async function generarPropCli(tipo, btnId, boxId, accionesLabel, carpeta) {
    const btn = document.getElementById(btnId);
    if(btn) { btn.disabled = true; btn.textContent = '⌛ Generando...'; }
    try {
        const res = await fetch('/api/analisis_final/generar_propcli', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'analisis_final', tipo})
        });
        const json = await res.json();
        const box = document.getElementById(boxId);
        if(json.ok) {
            const aud = json.audit ? json.audit[tipo] : null;
            let audTxt = '';
            if(aud && aud.generado) {
                audTxt = ` · Auditoría: ${aud.filas} filas comparadas vs modelo · ${aud.discrepancias} discrepancias`;
            }
            const txt = `✅ ${json.filas} líneas al archivo (${accionesLabel}) · Total ${json.total} · ${carpeta}/${json.ruta}${audTxt}`;
            if(box) { box.className = 'alert alert-success d-block py-2 small fw-bold'; box.textContent = txt; }
            alert(`✅ ${json.msg}\n${txt}`);
        } else {
            const txt = '❌ ERROR: ' + json.msg;
            if(box) { box.className = 'alert alert-danger d-block py-2 small fw-bold'; box.textContent = txt; }
            alert(txt);
        }
    } catch(e) {
        const txt = '❌ Error: ' + e.message;
        const box = document.getElementById(boxId);
        if(box) { box.className = 'alert alert-danger d-block py-2 small fw-bold'; box.textContent = txt; }
        alert(txt);
    } finally {
        if(btn) { btn.disabled = false; btn.textContent = tipo === 'carga' ? '📄 Generar ajuste-propcli-carga' : '📄 Generar ajuste-propcli-baja'; }
    }
}

async function generarBaCarga() {
    await generarBa('carga', 'btn-af-ba-carga', 'af-ba-carga-info', 'acepta AUMENTO/DISMINUYO', 'archivocargaba');
}
async function generarBaBaja() {
    await generarBa('baja', 'btn-af-ba-baja', 'af-ba-baja-info', 'BAJA', 'archivobajaba');
}

async function generarBa(tipo, btnId, boxId, accionesLabel, carpeta) {
    const btn = document.getElementById(btnId);
    if(btn) { btn.disabled = true; btn.textContent = '⌛ Generando...'; }
    try {
        const res = await fetch('/api/analisis_final/generar_ba', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'analisis_final', tipo})
        });
        const json = await res.json();
        const box = document.getElementById(boxId);
        if(json.ok) {
            const aud = json.audit ? json.audit[tipo] : null;
            let audTxt = '';
            if(aud && aud.generado) {
                audTxt = ` · Auditoría: ${aud.filas} filas comparadas vs modelo · ${aud.discrepancias} discrepancias`;
            }
            const txt = `✅ ${json.filas} líneas al archivo (${accionesLabel}) · Total ${json.total} · ${carpeta}/${json.ruta}${audTxt}`;
            if(box) { box.className = 'alert alert-success d-block py-2 small fw-bold'; box.textContent = txt; }
            alert(`✅ ${json.msg}\n${txt}`);
        } else {
            const txt = '❌ ERROR: ' + json.msg;
            if(box) { box.className = 'alert alert-danger d-block py-2 small fw-bold'; box.textContent = txt; }
            alert(txt);
        }
    } catch(e) {
        const txt = '❌ Error: ' + e.message;
        const box = document.getElementById(boxId);
        if(box) { box.className = 'alert alert-danger d-block py-2 small fw-bold'; box.textContent = txt; }
        alert(txt);
    } finally {
        if(btn) { btn.disabled = false; btn.textContent = tipo === 'carga' ? '📄 Generar ajuste-ba-carga' : '📄 Generar ajuste-ba-baja'; }
    }
}

async function generarInsumosCarga() {
    await generarInsumos('carga', 'btn-af-insumos-carga', 'af-insumos-carga-info', 'acepta AUMENTO/DISMINUYO', 'archivocargaba');
}
async function generarInsumosBaja() {
    await generarInsumos('baja', 'btn-af-insumos-baja', 'af-insumos-baja-info', 'BAJA', 'archivobajaba');
}

async function generarInsumos(tipo, btnId, boxId, accionesLabel, carpeta) {
    const btn = document.getElementById(btnId);
    if(btn) { btn.disabled = true; btn.textContent = '⌛ Generando...'; }
    try {
        const res = await fetch('/api/analisis_final/generar_insumos', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'analisis_final', tipo})
        });
        const json = await res.json();
        const box = document.getElementById(boxId);
        if(json.ok) {
            const aud = json.audit ? json.audit[tipo] : null;
            let audTxt = '';
            if(aud && aud.generado) {
                audTxt = ` · Auditoría: ${aud.filas} filas comparadas vs modelo · ${aud.discrepancias} discrepancias`;
            }
            const txt = `✅ ${json.filas} líneas al archivo (${accionesLabel}) · Total ${json.total} · ${carpeta}/${json.ruta}${audTxt}`;
            if(box) { box.className = 'alert alert-success d-block py-2 small fw-bold'; box.textContent = txt; }
            alert(`✅ ${json.msg}\n${txt}`);
        } else {
            const txt = '❌ ERROR: ' + json.msg;
            if(box) { box.className = 'alert alert-danger d-block py-2 small fw-bold'; box.textContent = txt; }
            alert(txt);
        }
    } catch(e) {
        const txt = '❌ Error: ' + e.message;
        const box = document.getElementById(boxId);
        if(box) { box.className = 'alert alert-danger d-block py-2 small fw-bold'; box.textContent = txt; }
        alert(txt);
    } finally {
        if(btn) { btn.disabled = false; btn.textContent = tipo === 'carga' ? '📄 Generar ajuste-insumos-carga' : '📄 Generar ajuste-insumos-baja'; }
    }
}

async function deleteSelectedWms() {
    await deleteSelectedModule('wms', 'WMS', 'chk-wms-row', loadWmsData);
}
async function deleteSelectedSaldos() {
    await deleteSelectedModule('saldos', 'Saldos', 'chk-saldos-row', loadSaldosData);
}
async function deleteSelectedEtqmang() {
    await deleteSelectedModule('etqmang', 'Etiquetas y Mangas', 'chk-etqmang-row', loadEtqmangData);
}
async function deleteSelectedEpts() {
    await deleteSelectedModule('epts', 'EPTS', 'chk-epts-row', loadEptsData);
}

async function deleteSelectedModule(module, label, chkClass, reloadFn) {
    const selected = [];
    document.querySelectorAll(`input[type="checkbox"].${chkClass}:checked`).forEach(cb => {
        selected.push(cb.value);
    });
    if (selected.length === 0) {
        return alert("No hay registros seleccionados para eliminar.");
    }
    if (!confirm(`⚠️ ADVERTENCIA ⚠️\n\n¿Estás seguro de ELIMINAR DEFINITIVAMENTE ${selected.length} registro(s) del modelo ${label}?\n\nEsta acción NO se puede deshacer.`)) return;
    try {
        const res = await fetch(`/api/${module}/delete`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module, ids: selected})
        });
        const json = await res.json();
        if (json.success) {
            alert("✅ " + (json.msg || "Registros eliminados."));
            if (typeof reloadFn === 'function') reloadFn();
        } else {
            alert("❌ ERROR: " + (json.msg || "No se pudieron eliminar."));
        }
    } catch (e) {
        alert("❌ Error: " + e.message);
    }
}


async function updatePoolDescriptions() {
    if(!poolData || poolData.length === 0) return alert("No hay registros en Pool Final para procesar.");
    if(!confirm(`¿Deseas ejecutar el Query 1 (maestro) para actualizar las DESCRIPCIONES de los ${poolData.length} registros de Pool Final?\n\nSolo se reescriben los NPs cuya descripción venga de Odoo.`)) return;
    const btn = document.querySelector('button[onclick="updatePoolDescriptions()"]');
    const origText = btn ? btn.innerHTML : '';
    if(btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Actualizando Descripciones... (puede tardar)';
    }
    try {
        const res = await fetch('/api/pool/update_descriptions', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'pool'}) });
        if(!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if(json.success) {
            alert(`✅ Descripciones actualizadas: ${json.updated} (de ${json.processed} NPs procesados).\n- Descriptivos coincidentes en Query 1: ${json.matched_q1}\n- Con descripción no vacía: ${json.with_desc}`);
            await loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    } finally {
        if(btn) {
            btn.disabled = false;
            btn.innerHTML = origText;
        }
    }
}

async function fillLocationPool() {
    if(!poolData || poolData.length === 0) return alert("No hay registros en Pool Final para procesar.");
    if(!confirm(`¿Deseas ejecutar el Query maestro para llenar la columna "Ubicación" (almacen_pool) de los ${poolData.length} registros?\n\nLos SKUs sin datos en Odoo quedarán en blanco.`)) return;
    try {
        const res = await fetch('/api/pool/fill_location', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'pool'}) });
        const json = await res.json();
        if(json.success) {
            let det = `✅ Ubicaciones actualizadas: ${json.filled_q1 ?? json.updated} registros (de ${json.processed} NPs procesados).`;
            if(json.filled_q3 !== undefined) {
                det += `\n- Query 1 (stock actual): ${json.filled_q1}\n- Query 3 (pool data): ${json.filled_q3}\n- Aún sin ubicación (en blanco): ${json.still_blank}`;
            }
            alert(det);
            loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

async function fillLocationPoolQ2() {
    if(!poolData || poolData.length === 0) return alert("No hay registros en Pool Final para procesar.");
    if(!confirm(`¿Deseas ejecutar el Query 2 (existencias) para actualizar la ubicación de los ${poolData.length} registros?\n\nSe tomará la PRIMERA ubicación del array y se marcará "Varias" si hay más de una.`)) return;
    const btn = document.querySelector('button[onclick="fillLocationPoolQ2()"]');
    const origText = btn ? btn.innerHTML : '';
    if(btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Procesando Query 2... (puede tardar)';
    }
    try {
        const res = await fetch('/api/pool/fill_location_q2', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'pool'}) });
        if(!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if(json.success) {
            alert(`✅ Ubicaciones actualizadas: ${json.updated} (de ${json.processed} NPs).\n- NPs ubicados: ${json.matched_q2}\n- Con VARIAS ubicaciones: ${json.with_varias}\n- Aún sin ubicación: ${json.still_blank}`);
            await loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    } finally {
        if(btn) {
            btn.disabled = false;
            btn.innerHTML = origText;
        }
    }
}

async function markAuditAll() {
    if(!poolData || poolData.length === 0) return alert("No hay registros en Pool Final.");
    if(!confirm(`¿Deseas marcar auditoría (fecha/hora actual: ${new Date().toISOString().slice(0,19).replace('T',' ')}) en TODOS los ${poolData.length} registros?`)) return;
    try {
        const res = await fetch('/api/pool/mark_audit', { method: 'POST' });
        const json = await res.json();
        if(json.success) {
            alert(`✅ Auditoría marcada en ${json.updated} registros.`);
            loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

async function createPoolBackup() {
    if(!poolData || poolData.length === 0) return alert("No hay registros en Pool Final para respaldar.");
    if(!confirm(`¿Deseas crear un respaldo de seguridad copiando los ${poolData.length} registros actuales de Pool Final a su espejo (backup)?`)) return;
    try {
        const res = await fetch('/api/pool/create_backup', { method: 'POST' });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

async function restorePoolBackup() {
    if(!confirm("⚠️ ADVERTENCIA: Esta acción deshará la última eliminación.\n\nSe restaurará la tabla de Pool Final exactamente al estado en que estaba antes de tu último borrado.\n\n¿Deseas proceder?")) return;
    try {
        const res = await fetch('/api/pool/restore_backup', { method: 'POST' });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

// ============ MODO EDICIÓN POOL FINAL ============
let poolEditMode = false;
let poolEditValues = {};   // folio -> {field: value}

const POOL_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por'];

function _escPool(v) {
    return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function variasBadge(r) {
    const v = Number(r.varias_ubicaciones) === 1;
    return v
        ? '<span class="badge bg-warning text-dark fw-bold">SÍ</span>'
        : '<span class="badge bg-secondary text-white fw-bold">NO</span>';
}

function layoutBadge(r) {
    const v = Number(r.layout) === 1;
    return v
        ? '<span class="badge bg-success text-white fw-bold">SÍ</span>'
        : '<span class="badge bg-secondary text-white fw-bold">NO</span>';
}

function setPoolEditButtons(editing) {
    document.getElementById('btn-edit-pool').classList.toggle('d-none', editing);
    document.getElementById('btn-save-pool').classList.toggle('d-none', !editing);
    document.getElementById('btn-cancel-pool').classList.toggle('d-none', !editing);
}

function editSelectedPool() {
    if(!dtPoolFinal) return;
    const selected = dtPoolFinal.$('input[type="checkbox"].chk-pool-row:checked');
    if(selected.length === 0) return alert("Selecciona al menos un registro para editar (usa casillas).");

    poolEditValues = {};
    selected.each(function() {
        const folio = this.value;
        const rec = poolData.find(r => String(r.folio) === String(folio));
        if(!rec) return;
        poolEditValues[folio] = {};
        POOL_EDIT_FIELDS.forEach(f => { poolEditValues[folio][f] = rec[f] ?? ''; });
    });

    poolEditMode = true;
    setPoolEditButtons(true);
    renderPoolTable(poolData);
    alert(`Modo edición activado para ${selected.length} registro(s).\nEdita los campos y presiona "Confirmar y Guardar".`);
}

function renderPoolEditRow(r) {
    const vals = poolEditValues[r.folio] || {};
    let cells = '';
    POOL_EDIT_FIELDS.forEach(f => {
        cells += `<td><input class="pool-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:90px; padding:2px 6px;" data-folio="${_escPool(r.folio)}" data-field="${f}" value="${_escPool(vals[f])}" onchange="updatePoolEditValue(this)"></td>`;
        if(f === 'almacen_pool') {
            cells += `<td class="text-center">${variasBadge(r)}</td>`;
            cells += `<td class="text-center">${layoutBadge(r)}</td>`;
        }
    });
    return cells;
}

function updatePoolEditValue(input) {
    const folio = input.dataset.folio;
    const field = input.dataset.field;
    if(!poolEditValues[folio]) poolEditValues[folio] = {};
    poolEditValues[folio][field] = input.value;
}

function applyPoolEditInputs() {
    if(!poolEditMode) return;
    document.querySelectorAll('#table-pool-final tbody tr').forEach(tr => {
        const folioTd = tr.querySelector('td:nth-child(2)');
        const folio = folioTd ? folioTd.textContent.trim() : '';
        if(!folio || !poolEditValues[folio]) return;
        if(tr.querySelector('input.pool-edit-input')) return;
        const vals = poolEditValues[folio];
        const cells = Array.from(tr.querySelectorAll('td'));
        POOL_EDIT_FIELDS.forEach((f, idx) => {
            const skipBadges = idx > POOL_EDIT_FIELDS.indexOf('almacen_pool') ? 2 : 0;
            const td = cells[idx + 2 + skipBadges];
            if(!td) return;
            if(td.querySelector('input')) return;
            td.innerHTML = `<input class="pool-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:90px; padding:2px 6px;" data-folio="${_escPool(folio)}" data-field="${f}" value="${_escPool(vals[f])}" onchange="updatePoolEditValue(this)">`;
        });
    });
}

async function saveEditedPool() {
    if(!poolEditMode) return;
    const records = Object.keys(poolEditValues).map(folio => {
        const rec = { folio };
        POOL_EDIT_FIELDS.forEach(f => { rec[f] = poolEditValues[folio][f] ?? ''; });
        return rec;
    });
    if(records.length === 0) return;

    if(!confirm(`¿Confirmas guardar los cambios de ${records.length} registro(s) en Pool Final?\n\nSe hará un snapshot de seguridad y podrás revertir con Rollback.`)) return;

    try {
        const res = await fetch('/api/pool/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'pool', records})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            poolEditMode = false;
            setPoolEditButtons(false);
            loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

function cancelEditPool() {
    poolEditMode = false;
    poolEditValues = {};
    setPoolEditButtons(false);
    loadPoolFinal();
}

let dtMatriz = null;

async function loadMatriz() {
    try {
        const res = await fetch('/api/pool/matrix');
        const json = await res.json();
        const {columns, rows} = json;

        if(dtMatriz) {
            dtMatriz.destroy();
        }

        document.querySelector('#table-matrix thead').innerHTML = `<tr><th>NP</th>${columns.map(c => `<th>${_escPool(c)}</th>`).join('')}</tr>`;
        document.querySelector('#table-matrix tbody').innerHTML = rows.map(r => {
            const cells = columns.map(c => {
                const has = r.locations.includes(c);
                return `<td class="text-center">${has ? '<strong class="text-success fw-bold">X</strong>' : ''}</td>`;
            }).join('');
            return `<tr><td class="fw-bold text-warning">${_escPool(r.np)}</td>${cells}</tr>`;
        }).join('');

        const info = document.getElementById('matrix-info');
        if(info) {
            info.innerHTML = `Mostrando <strong>${rows.length}</strong> producto(s) que se encuentran en más de 1 ubicación. Total ubicaciones dinámicas: <strong>${columns.length}</strong>.${rows.length === 0 ? '<br><span class="text-warning">⚠ Ningún NP está actualmente en más de una ubicación en Pool Final.</span>' : ''}`;
        }

        dtMatriz = $('#table-matrix').DataTable({
            pageLength: 50,
            scrollX: true,
            language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
            order: [[0, 'asc']],
            columnDefs: [{ orderable: false, targets: '_all' }]
        });
    } catch(e) {
        console.error(e);
        alert("❌ Error cargando la matriz: " + e.message);
    }
}

function filterMatriz() {
    if(dtMatriz) {
        dtMatriz.search(document.getElementById('matrix-search').value.trim()).draw();
    }
}


/* =================== Cargas WMS =================== */
let wmsTables = {};

function _wmsTh(label) {
    return `<th>${label}</th>`;
}

const WMS_COLUMNS = [
    ['folio', 'Folio Físico'],
    ['np', 'NP'],
    ['sheet', 'Pestaña'],
    ['descripcion', 'Descripción'],
    ['unidad', 'Unidad'],
    ['empaque', 'Empaque'],
    ['almacen', 'Almacén'],
    ['almacen_pool', 'Ubicación'],
    ['varias_ubicaciones', 'Varias'],
    ['layout', 'Layout'],
    ['cantidad', 'Cantidad'],
    ['contado_por', 'Contado Por'],
    ['auditoria', 'Auditoría'],
];

function wmsBadgeValue(val, activeLabel, activeClass) {
    const v = Number(val) === 1;
    return v
        ? `<span class="badge ${activeClass} fw-bold">${activeLabel}</span>`
        : '<span class="badge bg-secondary text-white fw-bold">NO</span>';
}

const WMS_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por'];
let wmsEditMode = false;
let wmsEditValues = {};

function setWmsEditButtons(editing) {
    const editBtn = document.getElementById('btn-edit-wms');
    const saveBtn = document.getElementById('btn-save-wms');
    const cancelBtn = document.getElementById('btn-cancel-wms');
    if(editBtn) editBtn.classList.toggle('d-none', editing);
    if(saveBtn) saveBtn.classList.toggle('d-none', !editing);
    if(cancelBtn) cancelBtn.classList.toggle('d-none', !editing);
}

function renderWmsTables() {
    const ids = {
        'table-wms-b1': 'WMS-B1',
        'table-wms-cedis4': 'WMS-CEDIS 4',
        'table-wms-nave5': 'WMS-NAVE 5',
        'table-wms-resumen': null,
    };

    for (const [tableId, sheet] of Object.entries(ids)) {
        const thead = document.querySelector(`#${tableId} thead`);
        const tbody = document.querySelector(`#${tableId} tbody`);
        if(!thead || !tbody) continue;

        thead.innerHTML = '<tr><th></th>' + WMS_COLUMNS.map(c => _wmsTh(c[1])).join('') + '</tr>';

        const filterFn = sheet
            ? r => String(r.sheet || '').trim() === sheet
            : r => true;

        const filtered = wmsData.filter(filterFn);
        tbody.innerHTML = filtered.map(r => {
            const chk = `<td class="text-center"><input type="checkbox" class="chk-wms-row" value="${_escPool(r.id)}"></td>`;
            const folioTd = `<td>${_escPool(r.folio)}</td>`;
            if(wmsEditMode && wmsEditValues[r.id]) {
                const vals = wmsEditValues[r.id] || {};
                let cells = '';
                WMS_EDIT_FIELDS.forEach(f => {
                    if(f === 'almacen_pool') {
                        cells += `<td><input class="wms-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:150px; padding:2px 6px;" data-id="${_escPool(r.id)}" data-field="almacen_pool" value="${_escPool(vals.almacen_pool ?? r.almacen_pool)}" onchange="updateWmsEditValue(this)"></td>`;
                        cells += `<td class="text-center">${wmsBadgeValue(r.varias_ubicaciones, 'SÍ', 'bg-warning text-dark')}</td>`;
                        cells += `<td class="text-center">${wmsBadgeValue(r.layout, 'SÍ', 'bg-success text-white')}</td>`;
                    } else {
                        cells += `<td><input class="wms-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:${f === 'descripcion' ? '180' : '90'}px; padding:2px 6px;" data-id="${_escPool(r.id)}" data-field="${f}" value="${_escPool(vals[f] ?? r[f])}" onchange="updateWmsEditValue(this)"></td>`;
                    }
                });
                return `<tr data-wms-id="${_escPool(r.id)}">${chk}${folioTd}${cells}<td class="text-nowrap small">${_escPool(r.auditoria || '')}</td></tr>`;
            }
            return `<tr data-wms-id="${_escPool(r.id)}">
                ${chk}${folioTd}
                <td>${_escPool(r.np)}</td>
                <td>${_escPool(r.sheet)}</td>
                <td><div style="max-width: 220px; overflow: hidden; text-overflow: ellipsis;" title="${_escPool(r.descripcion)}">${_escPool(r.descripcion)}</div></td>
                <td>${_escPool(r.unidad)}</td>
                <td>${_escPool(r.empaque)}</td>
                <td>${_escPool(r.almacen)}</td>
                <td title="${_escPool(r.almacen_pool || '')}">${_escPool(r.almacen_pool || '')}</td>
                <td class="text-center">${wmsBadgeValue(r.varias_ubicaciones, 'SÍ', 'bg-warning text-dark')}</td>
                <td class="text-center">${wmsBadgeValue(r.layout, 'SÍ', 'bg-success text-white')}</td>
                <td>${_escPool(r.cantidad)}</td>
                <td>${_escPool(r.contado_por)}</td>
                <td class="text-nowrap small">${_escPool(r.auditoria || '')}</td>
            </tr>`;
        }).join('');

        if(wmsTables[tableId]) {
            wmsTables[tableId].destroy();
        }
        wmsTables[tableId] = $(`#${tableId}`).DataTable({
            pageLength: 50,
            lengthMenu: [25, 50, 100, 200],
            scrollX: true,
            language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
            order: [[2, 'asc']],
        });
        wmsTables[tableId].on('draw.dt', applyWmsEditInputs);
    }

    const counts = { 'WMS-B1': 0, 'WMS-CEDIS 4': 0, 'WMS-NAVE 5': 0 };
    wmsData.forEach(r => {
        const s = String(r.sheet || '').trim();
        if(counts[s] !== undefined) counts[s]++;
    });
    document.getElementById('wms-count-b1').textContent = counts['WMS-B1'];
    document.getElementById('wms-count-cedis4').textContent = counts['WMS-CEDIS 4'];
    document.getElementById('wms-count-nave5').textContent = counts['WMS-NAVE 5'];

    const info = document.getElementById('wms-info');
    if(info && typeof wmsData !== 'undefined') {
        info.innerHTML = `Total registros cargados: <strong>${wmsData.length}</strong>. WMS-B1: <strong>${counts['WMS-B1']}</strong> | WMS-CEDIS 4: <strong>${counts['WMS-CEDIS 4']}</strong> | WMS-NAVE 5: <strong>${counts['WMS-NAVE 5']}</strong>. Paginación de 50 registros por tabla.`;
    }
}

function editSelectedWms() {
    const idSet = new Set();
    document.querySelectorAll('input.chk-wms-row:checked').forEach(cb => idSet.add(cb.value));
    if(idSet.size === 0) return alert("Selecciona al menos un registro para editar (usa casillas).");

    wmsEditValues = {};
    idSet.forEach(id => {
        const rec = wmsData.find(r => String(r.id) === String(id));
        if(!rec) return;
        wmsEditValues[id] = {};
        WMS_EDIT_FIELDS.forEach(f => { wmsEditValues[id][f] = rec[f] ?? ''; });
    });

    wmsEditMode = true;
    setWmsEditButtons(true);
    renderWmsTables();
    alert(`Modo edición activado para ${idSet.size} registro(s).\nEdita los campos y presiona "Confirmar y Guardar".`);
}

function updateWmsEditValue(input) {
    const id = input.dataset.id;
    const field = input.dataset.field;
    if(!wmsEditValues[id]) wmsEditValues[id] = {};
    wmsEditValues[id][field] = input.value;
}

function applyWmsEditInputs() {
    if(!wmsEditMode) return;
    document.querySelectorAll('tr[data-wms-id]').forEach(tr => {
        const id = tr.dataset.wmsId;
        if(!id || !wmsEditValues[id]) return;
        if(tr.querySelector('input.wms-edit-input')) return;
        const vals = wmsEditValues[id];
        const cells = Array.from(tr.querySelectorAll('td'));
        const baseIdx = 2;
        WMS_EDIT_FIELDS.forEach((f, idx) => {
            const skipBadges = idx > WMS_EDIT_FIELDS.indexOf('almacen_pool') ? 2 : 0;
            const td = cells[baseIdx + idx + skipBadges];
            if(!td || td.querySelector('input')) return;
            const width = f === 'descripcion' ? '180' : (f === 'almacen_pool' ? '150' : '90');
            td.innerHTML = `<input class="wms-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:${width}px; padding:2px 6px;" data-id="${_escPool(id)}" data-field="${f}" value="${_escPool(vals[f] ?? '')}" onchange="updateWmsEditValue(this)">`;
        });
    });
}

async function saveEditedWms() {
    if(!wmsEditMode) return;
    const records = Object.keys(wmsEditValues).map(id => {
        const rec = { id: Number(id) };
        WMS_EDIT_FIELDS.forEach(f => { rec[f] = wmsEditValues[id][f] ?? ''; });
        return rec;
    });
    if(records.length === 0) return;

    if(!confirm(`¿Confirmas guardar los cambios de ${records.length} registro(s) en WMS?`)) return;

    try {
        const res = await fetch('/api/wms/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'wms', records})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            wmsEditMode = false;
            wmsEditValues = {};
            setWmsEditButtons(false);
            await loadWmsData();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

function cancelEditWms() {
    wmsEditMode = false;
    wmsEditValues = {};
    setWmsEditButtons(false);
    renderWmsTables();
}

let wmsData = [];

async function loadWmsData() {
    if(!document.getElementById('table-wms-b1')) return;
    try {
        const res = await fetch('/api/wms/data');
        const json = await res.json();
        wmsData = json.data || [];
        renderWmsTables();
    } catch(e) {
        console.error('Error cargando WMS:', e);
    }
}

async function fillWmsUomEmpaque() {
    const btn = document.getElementById('btn-wms-uom');
    if(!btn) return;
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando UoM & Empaque...';
    try {
        const res = await fetch('/api/wms/fill_uom_empaque', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'wms'}) });
        const json = await res.json();
        if(json.success) {
            alert(`✅ UoM & Empaque actualizado.\n\nProcesados: ${json.processed}\nCon Unidad: ${json.with_uom}\nCon Empaque: ${json.with_empaque}`);
            await loadWmsData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🧮 UoM & Empaque';
    }
}

async function fillWmsLocationsQ2() {
    const btn = document.getElementById('btn-wms-q2');
    if(!btn) return;
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando Query 2 (puede tardar)...';
    try {
        const res = await fetch('/api/wms/fill_locations_q2', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'wms'}) });
        const json = await res.json();
        if(json.success) {
            alert(`✅ Ubicaciones Query 2 actualizado en wms_data.\n\nProcesados: ${json.processed}\nCoincidentes: ${json.matched_q2}\nCon Varias Ubicaciones: ${json.with_varias}`);
            await loadWmsData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '📍 Llenar Ubicaciones (Query 2)';
    }
}

async function uploadWmsFiles() {
    const btn = document.getElementById('btn-wms-upload');
    const b1 = document.getElementById('wms-b1');
    const c4 = document.getElementById('wms-cedis4');
    const n5 = document.getElementById('wms-nave5');

    if(!b1.files.length && !c4.files.length && !n5.files.length) {
        return alert("Selecciona al menos un archivo para cargar.");
    }

    const fd = new FormData();
    fd.append('module', 'wms');
    if(b1.files.length) fd.append('b1', b1.files[0]);
    if(c4.files.length) fd.append('cedis4', c4.files[0]);
    if(n5.files.length) fd.append('nave5', n5.files[0]);

    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando cargas WMS...';
    try {
        const res = await fetch('/api/wms/upload', { method: 'POST', body: fd });
        const json = await res.json();
        if(json.success) {
            alert('✅ ' + json.msg);
            await loadWmsData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error al subir: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⬆️ Cargar y Reemplazar Datos WMS';
    }
}

document.addEventListener('DOMContentLoaded', function() {
    if(document.getElementById('table-wms-b1')) {
        loadWmsData();
    }
    if(document.getElementById('table-saldos')) {
        loadSaldosData();
    }
    if(document.getElementById('table-etqmang')) {
        loadEtqmangData();
    }
    if(document.getElementById('table-epts')) {
        loadEptsData();
    }
    if(document.getElementById('table-epts-comp')) {
        loadEptsComparativo();
    }
});

/* =================== Cargas Saldos =================== */
let saldosTable = null;
let saldosData = [];
let saldosEditMode = false;
let saldosEditValues = {};

const SALDOS_COLUMNS = [
    ['folio', 'Folio Físico'],
    ['np', 'NP'],
    ['sheet', 'Pestaña'],
    ['descripcion', 'Descripción'],
    ['unidad', 'Unidad'],
    ['empaque', 'Empaque'],
    ['almacen', 'Almacén'],
    ['almacen_pool', 'Ubicación'],
    ['varias_ubicaciones', 'Varias'],
    ['layout', 'Layout'],
    ['cantidad', 'Cantidad'],
    ['contado_por', 'Contado Por'],
    ['auditoria', 'Auditoría'],
];

const SALDOS_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por'];

function setSaldosEditButtons(editing) {
    const editBtn = document.getElementById('btn-edit-saldos');
    const saveBtn = document.getElementById('btn-save-saldos');
    const cancelBtn = document.getElementById('btn-cancel-saldos');
    if(editBtn) editBtn.classList.toggle('d-none', editing);
    if(saveBtn) saveBtn.classList.toggle('d-none', !editing);
    if(cancelBtn) cancelBtn.classList.toggle('d-none', !editing);
}

function renderSaldosTable() {
    const thead = document.querySelector('#table-saldos thead');
    const tbody = document.querySelector('#table-saldos tbody');
    if(!thead || !tbody) return;

    thead.innerHTML = '<tr><th></th>' + SALDOS_COLUMNS.map(c => _wmsTh(c[1])).join('') + '</tr>';

    tbody.innerHTML = saldosData.map(r => {
        const chk = `<td class="text-center"><input type="checkbox" class="chk-saldos-row" value="${_escPool(r.id)}"></td>`;
        const folioTd = `<td>${_escPool(r.folio)}</td>`;
        if(saldosEditMode && saldosEditValues[r.id]) {
            const vals = saldosEditValues[r.id] || {};
            let cells = '';
            SALDOS_EDIT_FIELDS.forEach(f => {
                if(f === 'almacen_pool') {
                    cells += `<td><input class="saldos-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:150px; padding:2px 6px;" data-id="${_escPool(r.id)}" data-field="almacen_pool" value="${_escPool(vals.almacen_pool ?? r.almacen_pool)}" onchange="updateSaldosEditValue(this)"></td>`;
                    cells += `<td class="text-center">${wmsBadgeValue(r.varias_ubicaciones, 'SÍ', 'bg-warning text-dark')}</td>`;
                    cells += `<td class="text-center">${wmsBadgeValue(r.layout, 'SÍ', 'bg-success text-white')}</td>`;
                } else {
                    cells += `<td><input class="saldos-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:${f === 'descripcion' ? '180' : '90'}px; padding:2px 6px;" data-id="${_escPool(r.id)}" data-field="${f}" value="${_escPool(vals[f] ?? r[f])}" onchange="updateSaldosEditValue(this)"></td>`;
                }
            });
            return `<tr data-saldos-id="${_escPool(r.id)}">${chk}${folioTd}${cells}<td class="text-nowrap small">${_escPool(r.auditoria || '')}</td></tr>`;
        }
        return `<tr data-saldos-id="${_escPool(r.id)}">
            ${chk}${folioTd}
            <td>${_escPool(r.np)}</td>
            <td>${_escPool(r.sheet)}</td>
            <td><div style="max-width: 220px; overflow: hidden; text-overflow: ellipsis;" title="${_escPool(r.descripcion)}">${_escPool(r.descripcion)}</div></td>
            <td>${_escPool(r.unidad)}</td>
            <td>${_escPool(r.empaque)}</td>
            <td>${_escPool(r.almacen)}</td>
            <td title="${_escPool(r.almacen_pool || '')}">${_escPool(r.almacen_pool || '')}</td>
            <td class="text-center">${wmsBadgeValue(r.varias_ubicaciones, 'SÍ', 'bg-warning text-dark')}</td>
            <td class="text-center">${wmsBadgeValue(r.layout, 'SÍ', 'bg-success text-white')}</td>
            <td>${_escPool(r.cantidad)}</td>
            <td>${_escPool(r.contado_por)}</td>
            <td class="text-nowrap small">${_escPool(r.auditoria || '')}</td>
        </tr>`;
    }).join('');

    if(saldosTable) {
        saldosTable.destroy();
    }
    saldosTable = $('#table-saldos').DataTable({
        pageLength: 50,
        lengthMenu: [25, 50, 100, 200],
        scrollX: true,
        language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
        order: [[2, 'asc']],
    });
    saldosTable.on('draw.dt', applySaldosEditInputs);

    const info = document.getElementById('saldos-info');
    if(info) {
        info.innerHTML = `Total registros cargados: <strong>${saldosData.length}</strong> | Pestaña: Saldos. Paginación de 50 registros.`;
    }
}

function editSelectedSaldos() {
    const idSet = new Set();
    document.querySelectorAll('input.chk-saldos-row:checked').forEach(cb => idSet.add(cb.value));
    if(idSet.size === 0) return alert("Selecciona al menos un registro para editar (usa casillas).");

    saldosEditValues = {};
    idSet.forEach(id => {
        const rec = saldosData.find(r => String(r.id) === String(id));
        if(!rec) return;
        saldosEditValues[id] = {};
        SALDOS_EDIT_FIELDS.forEach(f => { saldosEditValues[id][f] = rec[f] ?? ''; });
    });

    saldosEditMode = true;
    setSaldosEditButtons(true);
    renderSaldosTable();
    alert(`Modo edición activado para ${idSet.size} registro(s).\nEdita los campos y presiona "Confirmar y Guardar".`);
}

function updateSaldosEditValue(input) {
    const id = input.dataset.id;
    const field = input.dataset.field;
    if(!saldosEditValues[id]) saldosEditValues[id] = {};
    saldosEditValues[id][field] = input.value;
}

function applySaldosEditInputs() {
    if(!saldosEditMode) return;
    document.querySelectorAll('tr[data-saldos-id]').forEach(tr => {
        const id = tr.dataset.saldosId;
        if(!id || !saldosEditValues[id]) return;
        if(tr.querySelector('input.saldos-edit-input')) return;
        const vals = saldosEditValues[id];
        const cells = Array.from(tr.querySelectorAll('td'));
        const baseIdx = 2;
        SALDOS_EDIT_FIELDS.forEach((f, idx) => {
            const skipBadges = idx > SALDOS_EDIT_FIELDS.indexOf('almacen_pool') ? 2 : 0;
            const td = cells[baseIdx + idx + skipBadges];
            if(!td || td.querySelector('input')) return;
            const width = f === 'descripcion' ? '180' : (f === 'almacen_pool' ? '150' : '90');
            td.innerHTML = `<input class="saldos-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:${width}px; padding:2px 6px;" data-id="${_escPool(id)}" data-field="${f}" value="${_escPool(vals[f] ?? '')}" onchange="updateSaldosEditValue(this)">`;
        });
    });
}

async function saveEditedSaldos() {
    if(!saldosEditMode) return;
    const records = Object.keys(saldosEditValues).map(id => {
        const rec = { id: Number(id) };
        SALDOS_EDIT_FIELDS.forEach(f => { rec[f] = saldosEditValues[id][f] ?? ''; });
        return rec;
    });
    if(records.length === 0) return;

    if(!confirm(`¿Confirmas guardar los cambios de ${records.length} registro(s) en Saldos?`)) return;

    try {
        const res = await fetch('/api/saldos/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'saldos', records})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            saldosEditMode = false;
            saldosEditValues = {};
            setSaldosEditButtons(false);
            await loadSaldosData();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

function cancelEditSaldos() {
    saldosEditMode = false;
    saldosEditValues = {};
    setSaldosEditButtons(false);
    renderSaldosTable();
}

async function loadSaldosData() {
    if(!document.getElementById('table-saldos')) return;
    try {
        const res = await fetch('/api/saldos/data');
        const json = await res.json();
        saldosData = json.data || [];
        renderSaldosTable();
    } catch(e) {
        console.error('Error cargando Saldos:', e);
    }
}

async function fillSaldosUomEmpaque() {
    const btn = document.getElementById('btn-saldos-uom');
    if(!btn) return;
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando UoM & Empaque...';
    try {
        const res = await fetch('/api/saldos/fill_uom_empaque', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'saldos'}) });
        const json = await res.json();
        if(json.success) {
            alert(`✅ UoM & Empaque actualizado.\n\nProcesados: ${json.processed}\nCon Unidad: ${json.with_uom}\nCon Empaque: ${json.with_empaque}`);
            await loadSaldosData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🧮 UoM & Empaque';
    }
}

async function fillSaldosLocationsQ2() {
    const btn = document.getElementById('btn-saldos-q2');
    if(!btn) return;
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando Query 2 (puede tardar)...';
    try {
        const res = await fetch('/api/saldos/fill_locations_q2', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'saldos'}) });
        const json = await res.json();
        if(json.success) {
            alert(`✅ Ubicaciones Query 2 actualizado en saldos_data.\n\nProcesados: ${json.processed}\nCoincidentes: ${json.matched_q2}\nCon Varias Ubicaciones: ${json.with_varias}`);
            await loadSaldosData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '📍 Llenar Ubicaciones (Query 2)';
    }
}

async function uploadSaldosFiles() {
    const btn = document.getElementById('btn-saldos-upload');
    const fileInput = document.getElementById('saldos-file');
    if(!fileInput || !fileInput.files.length) {
        return alert("Selecciona un archivo de Saldos para cargar.");
    }
    const fd = new FormData();
    fd.append('module', 'saldos');
    fd.append('file', fileInput.files[0]);

    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando carga Saldos...';
    try {
        const res = await fetch('/api/saldos/upload', { method: 'POST', body: fd });
        const json = await res.json();
        if(json.success) {
            alert('✅ ' + json.msg);
            await loadSaldosData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error al subir: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⬆️ Cargar y Reemplazar Datos Saldos';
    }
}

/* =================== Etiquetas y Mangas =================== */
let etqmangTable = null;
let etqmangData = [];
let etqmangEditMode = false;
let etqmangEditValues = {};

const ETQMANG_COLUMNS = [
    ['folio', 'Folio Físico'],
    ['np', 'NP'],
    ['sheet', 'Pestaña'],
    ['descripcion', 'Descripción'],
    ['unidad', 'Unidad'],
    ['empaque', 'Empaque'],
    ['almacen', 'Almacén'],
    ['almacen_pool', 'Ubicación'],
    ['varias_ubicaciones', 'Varias'],
    ['layout', 'Layout'],
    ['cantidad', 'Cantidad'],
    ['contado_por', 'Contado Por'],
    ['auditoria', 'Auditoría'],
];

const ETQMANG_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por'];

function setEtqmangEditButtons(editing) {
    const editBtn = document.getElementById('btn-edit-etqmang');
    const saveBtn = document.getElementById('btn-save-etqmang');
    const cancelBtn = document.getElementById('btn-cancel-etqmang');
    if(editBtn) editBtn.classList.toggle('d-none', editing);
    if(saveBtn) saveBtn.classList.toggle('d-none', !editing);
    if(cancelBtn) cancelBtn.classList.toggle('d-none', !editing);
}

function renderEtqmangTable() {
    const thead = document.querySelector('#table-etqmang thead');
    const tbody = document.querySelector('#table-etqmang tbody');
    if(!thead || !tbody) return;

    thead.innerHTML = '<tr><th></th>' + ETQMANG_COLUMNS.map(c => _wmsTh(c[1])).join('') + '</tr>';

    tbody.innerHTML = etqmangData.map(r => {
        const chk = `<td class="text-center"><input type="checkbox" class="chk-etqmang-row" value="${_escPool(r.id)}"></td>`;
        const folioTd = `<td>${_escPool(r.folio)}</td>`;
        if(etqmangEditMode && etqmangEditValues[r.id]) {
            const vals = etqmangEditValues[r.id] || {};
            let cells = '';
            ETQMANG_EDIT_FIELDS.forEach(f => {
                if(f === 'almacen_pool') {
                    cells += `<td><input class="etqmang-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:150px; padding:2px 6px;" data-id="${_escPool(r.id)}" data-field="almacen_pool" value="${_escPool(vals.almacen_pool ?? r.almacen_pool)}" onchange="updateEtqmangEditValue(this)"></td>`;
                    cells += `<td class="text-center">${wmsBadgeValue(r.varias_ubicaciones, 'SÍ', 'bg-warning text-dark')}</td>`;
                    cells += `<td class="text-center">${wmsBadgeValue(r.layout, 'SÍ', 'bg-success text-white')}</td>`;
                } else {
                    cells += `<td><input class="etqmang-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:${f === 'descripcion' ? '180' : '90'}px; padding:2px 6px;" data-id="${_escPool(r.id)}" data-field="${f}" value="${_escPool(vals[f] ?? r[f])}" onchange="updateEtqmangEditValue(this)"></td>`;
                }
            });
            return `<tr data-etqmang-id="${_escPool(r.id)}">${chk}${folioTd}${cells}<td class="text-nowrap small">${_escPool(r.auditoria || '')}</td></tr>`;
        }
        return `<tr data-etqmang-id="${_escPool(r.id)}">
            ${chk}${folioTd}
            <td>${_escPool(r.np)}</td>
            <td title="${_escPool(r.sheet)}">${_escPool(r.sheet)}</td>
            <td><div style="max-width: 220px; overflow: hidden; text-overflow: ellipsis;" title="${_escPool(r.descripcion)}">${_escPool(r.descripcion)}</div></td>
            <td>${_escPool(r.unidad)}</td>
            <td>${_escPool(r.empaque)}</td>
            <td title="${_escPool(r.almacen)}">${_escPool(r.almacen)}</td>
            <td title="${_escPool(r.almacen_pool || '')}">${_escPool(r.almacen_pool || '')}</td>
            <td class="text-center">${wmsBadgeValue(r.varias_ubicaciones, 'SÍ', 'bg-warning text-dark')}</td>
            <td class="text-center">${wmsBadgeValue(r.layout, 'SÍ', 'bg-success text-white')}</td>
            <td>${_escPool(r.cantidad)}</td>
            <td>${_escPool(r.contado_por)}</td>
            <td class="text-nowrap small">${_escPool(r.auditoria || '')}</td>
        </tr>`;
    }).join('');

    if(etqmangTable) {
        etqmangTable.destroy();
    }
    etqmangTable = $('#table-etqmang').DataTable({
        pageLength: 50,
        lengthMenu: [25, 50, 100, 200],
        scrollX: true,
        language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
        order: [[2, 'asc']],
    });
    etqmangTable.on('draw.dt', applyEtqmangEditInputs);

    const info = document.getElementById('etqmang-info');
    if(info) {
        const sheets = new Set(etqmangData.map(r => String(r.sheet || '').trim()).filter(Boolean));
        info.innerHTML = `Total registros cargados: <strong>${etqmangData.length}</strong> | Pestañas: <strong>${sheets.size}</strong> (ODOO excluida). Paginación de 50 registros.`;
    }
}

function editSelectedEtqmang() {
    const idSet = new Set();
    document.querySelectorAll('input.chk-etqmang-row:checked').forEach(cb => idSet.add(cb.value));
    if(idSet.size === 0) return alert("Selecciona al menos un registro para editar (usa casillas).");

    etqmangEditValues = {};
    idSet.forEach(id => {
        const rec = etqmangData.find(r => String(r.id) === String(id));
        if(!rec) return;
        etqmangEditValues[id] = {};
        ETQMANG_EDIT_FIELDS.forEach(f => { etqmangEditValues[id][f] = rec[f] ?? ''; });
    });

    etqmangEditMode = true;
    setEtqmangEditButtons(true);
    renderEtqmangTable();
    alert(`Modo edición activado para ${idSet.size} registro(s).\nEdita los campos y presiona "Confirmar y Guardar".`);
}

function updateEtqmangEditValue(input) {
    const id = input.dataset.id;
    const field = input.dataset.field;
    if(!etqmangEditValues[id]) etqmangEditValues[id] = {};
    etqmangEditValues[id][field] = input.value;
}

function applyEtqmangEditInputs() {
    if(!etqmangEditMode) return;
    document.querySelectorAll('tr[data-etqmang-id]').forEach(tr => {
        const id = tr.dataset.etqmangId;
        if(!id || !etqmangEditValues[id]) return;
        if(tr.querySelector('input.etqmang-edit-input')) return;
        const vals = etqmangEditValues[id];
        const cells = Array.from(tr.querySelectorAll('td'));
        const baseIdx = 2;
        ETQMANG_EDIT_FIELDS.forEach((f, idx) => {
            const skipBadges = idx > ETQMANG_EDIT_FIELDS.indexOf('almacen_pool') ? 2 : 0;
            const td = cells[baseIdx + idx + skipBadges];
            if(!td || td.querySelector('input')) return;
            const width = f === 'descripcion' ? '180' : (f === 'almacen_pool' ? '150' : '90');
            td.innerHTML = `<input class="etqmang-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:${width}px; padding:2px 6px;" data-id="${_escPool(id)}" data-field="${f}" value="${_escPool(vals[f] ?? '')}" onchange="updateEtqmangEditValue(this)">`;
        });
    });
}

async function saveEditedEtqmang() {
    if(!etqmangEditMode) return;
    const records = Object.keys(etqmangEditValues).map(id => {
        const rec = { id: Number(id) };
        ETQMANG_EDIT_FIELDS.forEach(f => { rec[f] = etqmangEditValues[id][f] ?? ''; });
        return rec;
    });
    if(records.length === 0) return;

    if(!confirm(`¿Confirmas guardar los cambios de ${records.length} registro(s) en Etiquetas y Mangas?`)) return;

    try {
        const res = await fetch('/api/etqmang/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'etqmang', records})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            etqmangEditMode = false;
            etqmangEditValues = {};
            setEtqmangEditButtons(false);
            await loadEtqmangData();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

function cancelEditEtqmang() {
    etqmangEditMode = false;
    etqmangEditValues = {};
    setEtqmangEditButtons(false);
    renderEtqmangTable();
}

async function loadEtqmangData() {
    if(!document.getElementById('table-etqmang')) return;
    try {
        const res = await fetch('/api/etqmang/data');
        const json = await res.json();
        etqmangData = json.data || [];
        renderEtqmangTable();
    } catch(e) {
        console.error('Error cargando Etiquetas y Mangas:', e);
    }
}

async function fillEtqmangUomEmpaque() {
    const btn = document.getElementById('btn-etqmang-uom');
    if(!btn) return;
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando UoM & Empaque...';
    try {
        const res = await fetch('/api/etqmang/fill_uom_empaque', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'etqmang'}) });
        const json = await res.json();
        if(json.success) {
            alert(`✅ UoM & Empaque actualizado.\n\nProcesados: ${json.processed}\nCon Unidad: ${json.with_uom}\nCon Empaque: ${json.with_empaque}`);
            await loadEtqmangData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🧮 UoM & Empaque';
    }
}

async function fillEtqmangLocationsQ2() {
    const btn = document.getElementById('btn-etqmang-q2');
    if(!btn) return;
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando Query 2 (puede tardar)...';
    try {
        const res = await fetch('/api/etqmang/fill_locations_q2', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'etqmang'}) });
        const json = await res.json();
        if(json.success) {
            alert(`✅ Ubicaciones Query 2 actualizado en etqmang_data.\n\nProcesados: ${json.processed}\nCoincidentes: ${json.matched_q2}\nCon Varias Ubicaciones: ${json.with_varias}`);
            await loadEtqmangData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '📍 Llenar Ubicaciones (Query 2)';
    }
}

async function uploadEtqmangFiles() {
    const btn = document.getElementById('btn-etqmang-upload');
    const fileInput = document.getElementById('etqmang-file');
    const sheetInput = document.getElementById('etqmang-sheet');
    if(!fileInput || !fileInput.files.length) {
        return alert("Selecciona el archivo de Inventario Etiquetas para cargar.");
    }
    const fd = new FormData();
    fd.append('module', 'etqmang');
    fd.append('file', fileInput.files[0]);
    if(sheetInput && sheetInput.value.trim()) {
        fd.append('sheet', sheetInput.value.trim());
    }

    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando Inventario Etiquetas...';
    try {
        const res = await fetch('/api/etqmang/upload', { method: 'POST', body: fd });
        const json = await res.json();
        if(json.success) {
            alert('✅ ' + json.msg);
            await loadEtqmangData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error al subir: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⬆️ Cargar y Reemplazar Datos';
    }
}

// ============ TRASPASO DE MÓDULOS A POOL FINAL ============
const TRANSFER_CFG = {
    wms:     { table: 'wms_data',     dataVar: () => wmsData,     reload: loadWmsData,     url: '/api/wms/transfer',     show: 'Cargas WMS' },
    saldos:  { table: 'saldos_data',  dataVar: () => saldosData,  reload: loadSaldosData,  url: '/api/saldos/transfer',  show: 'Cargas Saldos' },
    etqmang: { table: 'etqmang_data', dataVar: () => etqmangData, reload: loadEtqmangData, url: '/api/etqmang/transfer', show: 'Etiquetas y Mangas' },
    epts:    { table: 'epts_data',    dataVar: () => eptsData,    reload: loadEptsData,    url: '/api/epts/transfer',    show: 'EPTS' }
};

async function transferToPool(module) {
    const cfg = TRANSFER_CFG[module];
    if(!cfg) return alert("Módulo no soportado.");
    const rows = cfg.dataVar() || [];
    if(rows.length === 0) return alert(`No hay registros cargados en ${cfg.show} para traspasar.`);
    if(!confirm(`📤 ¿Generar ${rows.length} marbete(s) NUEVO(S) con folios consecutivos y cerrarlos en Pool Final?\n\n- Origen: ${cfg.show}\n- Se creará un marbete por cada registro cargado.\n- Los registros quedarán marcados con su folio (no se duplicarán al repetir el clic).`)) return;

    const btn = document.getElementById(`btn-${module}-transfer`);
    const origText = btn ? btn.innerHTML : '';
    if(btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Generando Marbetes... (puede tardar)';
    }
    try {
        const res = await fetch(cfg.url, { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module}) });
        if(!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if(json.success) {
            alert(`✅ ${json.msg}`);
            await cfg.reload();
            if(typeof loadPoolFinal === 'function') await loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    } finally {
        if(btn) {
            btn.disabled = false;
            btn.innerHTML = origText;
        }
    }
}

// ============ AUDITORÍA DE FOLIOS (Papelera) ============
let dtAuditoria = null;
let dtLost = null;
let auditData = [];
let lostData = [];
let auditEditMode = false;
let auditEditValues = {};   // folio -> {field: value}

const AUDIT_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por'];

function _escAud(v) {
    return String(v ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function estadoBadge(r) {
    const e = r.estado || 'Normal';
    let cls = 'bg-secondary text-white';
    if(e === 'Reconstruido desde PDF') cls = 'bg-info text-dark fw-bold';
    else if(e === 'Irrecuperable / Sin rastro') cls = 'bg-danger text-white fw-bold';
    return `<span class="badge ${cls}">${_escAud(e)}</span>`;
}

async function loadAuditoria() {
    try {
        const res = await fetch('/api/auditoria/data');
        const json = await res.json();
        auditData = json.deleted || [];
        lostData = json.lost || [];
        renderAuditoriaTable(auditData);
        renderLostTable(lostData);
    } catch(e) {
        console.error(e);
    }
}

function renderAuditoriaTable(data) {
    if(dtAuditoria) dtAuditoria.destroy();

    const tbody = document.querySelector('#table-auditoria tbody');
    tbody.innerHTML = data.map(r => {
        if(auditEditMode && auditEditValues[r.folio]) {
            return `<tr>
                <td class="text-center"><input type="checkbox" class="chk-audit-row" value="${_escAud(r.folio)}"></td>
                <td><strong class="text-warning">${_escAud(r.folio)}</strong></td>
                ${renderAuditoriaEditRow(r)}
                <td class="text-nowrap small">${_escAud(r.auditoria || '')}</td>
            </tr>`;
        }
        return `<tr>
            <td class="text-center"><input type="checkbox" class="chk-audit-row" value="${_escAud(r.folio)}"></td>
            <td><strong class="text-warning">${_escAud(r.folio)}</strong></td>
            <td>${_escAud(r.np)}</td><td>${_escAud(r.sheet)}</td>
            <td><div style="max-width: 200px; overflow: hidden; text-overflow: ellipsis;" title="${_escAud(r.descripcion)}">${_escAud(r.descripcion)}</div></td>
            <td>${_escAud(r.unidad)}</td><td>${_escAud(r.empaque)}</td><td>${_escAud(r.almacen)}</td>
            <td title="${_escAud(r.almacen_pool || '')}">${_escAud(r.almacen_pool || '')}</td>
            <td class="text-center">${variasBadge(r)}</td>
            <td class="text-center">${layoutBadge(r)}</td>
            <td>${_escAud(r.cantidad)}</td><td>${_escAud(r.contado_por)}</td>
            <td class="text-nowrap small">${estadoBadge(r)}</td>
            <td class="text-nowrap small">${_escAud(r.auditoria || '')}</td>
        </tr>`;
    }).join('');

    const chkAll = document.getElementById('chk-all-aud');
    if(chkAll) chkAll.checked = false;

    dtAuditoria = $('#table-auditoria').DataTable({
        pageLength: 50, scrollX: true, language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
        order: [[1, 'desc']],
        columnDefs: [ { orderable: false, targets: 0 } ]
    });
    dtAuditoria.on('draw.dt', applyAuditEditInputs);
}

function renderLostTable(data) {
    if(dtLost) dtLost.destroy();

    const tbody = document.querySelector('#table-lost tbody');
    tbody.innerHTML = data.map(r => {
        return `<tr>
            <td><strong class="text-danger">${_escAud(r.folio)}</strong></td>
            <td class="text-nowrap small">${_escAud(r.estado)}</td>
        </tr>`;
    }).join('');

    dtLost = $('#table-lost').DataTable({
        pageLength: 50, language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
        order: [[0, 'asc']]
    });
}

function toggleAllAuditoria(source) {
    const checkboxes = document.querySelectorAll('.chk-audit-row');
    for (let i = 0; i < checkboxes.length; i++) {
        checkboxes[i].checked = source.checked;
    }
}

function setAuditEditButtons(editing) {
    document.getElementById('btn-edit-aud').classList.toggle('d-none', editing);
    document.getElementById('btn-save-aud').classList.toggle('d-none', !editing);
    document.getElementById('btn-cancel-aud').classList.toggle('d-none', !editing);
}

function editSelectedAuditoria() {
    if(!dtAuditoria) return;
    const selected = dtAuditoria.$('input[type="checkbox"].chk-audit-row:checked');
    if(selected.length === 0) return alert("Selecciona al menos un registro para editar (usa casillas).");

    auditEditValues = {};
    selected.each(function() {
        const folio = this.value;
        const rec = auditData.find(r => String(r.folio) === String(folio));
        if(!rec) return;
        auditEditValues[folio] = {};
        AUDIT_EDIT_FIELDS.forEach(f => { auditEditValues[folio][f] = rec[f] ?? ''; });
    });

    auditEditMode = true;
    setAuditEditButtons(true);
    renderAuditoriaTable(auditData);
    alert(`Modo edición activado para ${selected.length} registro(s).\nEdita los campos y presiona "Confirmar y Guardar".`);
}

function renderAuditoriaEditRow(r) {
    const vals = auditEditValues[r.folio] || {};
    let cells = '';
    AUDIT_EDIT_FIELDS.forEach(f => {
        cells += `<td><input class="audit-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:90px; padding:2px 6px;" data-folio="${_escAud(r.folio)}" data-field="${f}" value="${_escAud(vals[f])}" onchange="updateAuditEditValue(this)"></td>`;
        if(f === 'almacen_pool') {
            cells += `<td class="text-center">${variasBadge(r)}</td>`;
            cells += `<td class="text-center">${layoutBadge(r)}</td>`;
        }
    });
    cells += `<td class="text-center"><span class="badge bg-info text-dark fw-bold">Edición en curso</span></td>`;
    return cells;
}

function updateAuditEditValue(input) {
    const folio = input.dataset.folio;
    const field = input.dataset.field;
    if(!auditEditValues[folio]) auditEditValues[folio] = {};
    auditEditValues[folio][field] = input.value;
}

function applyAuditEditInputs() {
    if(!auditEditMode) return;
    document.querySelectorAll('#table-auditoria tbody tr').forEach(tr => {
        const folioTd = tr.querySelector('td:nth-child(2)');
        const folio = folioTd ? folioTd.textContent.trim() : '';
        if(!folio || !auditEditValues[folio]) return;
        if(tr.querySelector('input.audit-edit-input')) return;
        const vals = auditEditValues[folio];
        const cells = Array.from(tr.querySelectorAll('td'));
        AUDIT_EDIT_FIELDS.forEach((f, idx) => {
            const skipBadges = idx > AUDIT_EDIT_FIELDS.indexOf('almacen_pool') ? 2 : 0;
            const td = cells[idx + 2 + skipBadges];
            if(!td) return;
            if(td.querySelector('input')) return;
            td.innerHTML = `<input class="audit-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:90px; padding:2px 6px;" data-folio="${_escAud(folio)}" data-field="${f}" value="${_escAud(vals[f])}" onchange="updateAuditEditValue(this)">`;
        });
    });
}

async function saveEditedAuditoria() {
    if(!auditEditMode) return;
    const records = Object.keys(auditEditValues).map(folio => {
        const rec = { folio };
        AUDIT_EDIT_FIELDS.forEach(f => { rec[f] = auditEditValues[folio][f] ?? ''; });
        return rec;
    });
    if(records.length === 0) return;

    if(!confirm(`¿Confirmas guardar los cambios de ${records.length} registro(s) en la Papelera de Auditoría?\n\n(Sin snapshot: el Pool Final no se ve afectado.)`)) return;

    try {
        const res = await fetch('/api/auditoria/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'auditoria', records})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            auditEditMode = false;
            auditEditValues = {};
            setAuditEditButtons(false);
            loadAuditoria();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

function cancelEditAuditoria() {
    auditEditMode = false;
    auditEditValues = {};
    setAuditEditButtons(false);
    loadAuditoria();
}

async function restoreSelectedAuditoria() {
    if(!dtAuditoria) return;
    const selected = dtAuditoria.$('input[type="checkbox"].chk-audit-row:checked');
    if(selected.length === 0) return alert("Selecciona al menos un registro para restaurar.");

    let folios = [];
    selected.each(function() { folios.push(this.value); });

    if(!confirm(`↩️ ¿Restaurar ${folios.length} registro(s) de la Papelera al Pool Final?\n\nSe conservará su folio original.\n- Si un folio ya existe en Pool Final, ese registro NO se restaura (permanece en la Papelera).`)) return;

    try {
        const res = await fetch('/api/auditoria/restore', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'auditoria', folios})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            loadAuditoria();
            if(typeof loadPoolFinal === 'function') await loadPoolFinal();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

async function reconstructAuditoria() {
    if(!confirm("🛠️ ¿Reconstruir desde los PDFs físicos?\n\nSe agregarán a la Papelera los folios que existen como archivo generado (pdfs/) pero que NO están ni en Pool Final ni en la Papelera, con estado 'Reconstruido desde PDF'.\n\nPool Final NO se modifica. ¿Proceder?")) return;

    const btn = document.getElementById('btn-aud-reconstruct');
    const origText = btn ? btn.innerHTML : '';
    if(btn) {
        btn.disabled = true;
        btn.innerHTML = '⏳ Reconstruyendo...';
    }
    try {
        const res = await fetch('/api/auditoria/reconstruct', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'auditoria'})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            loadAuditoria();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    } finally {
        if(btn) {
            btn.disabled = false;
            btn.innerHTML = origText;
        }
    }
}

// ============ MÓDULO EPTS ============
let eptsTable = null;
let eptsData = [];
let eptsEditMode = false;
let eptsEditValues = {};

const EPTS_COLUMNS = [
    ['lote', 'Lote'],
    ['np', 'NP'],
    ['sheet', 'Pestaña'],
    ['descripcion', 'Descripción'],
    ['unidad', 'Unidad'],
    ['empaque', 'Empaque'],
    ['almacen', 'Almacén'],
    ['almacen_pool', 'Ubicación'],
    ['varias_ubicaciones', 'Varias'],
    ['layout', 'Layout'],
    ['cantidad', 'Cantidad'],
    ['unidad_file', 'Unidad Archivo'],
    ['contado_por', 'Contado Por'],
    ['auditoria', 'Auditoría'],
];

const EPTS_EDIT_FIELDS = ['np', 'sheet', 'descripcion', 'unidad', 'empaque', 'almacen', 'almacen_pool', 'cantidad', 'contado_por', 'lote', 'unidad_file'];

function setEptsEditButtons(editing) {
    const editBtn = document.getElementById('btn-edit-epts');
    const saveBtn = document.getElementById('btn-save-epts');
    const cancelBtn = document.getElementById('btn-cancel-epts');
    if(editBtn) editBtn.classList.toggle('d-none', editing);
    if(saveBtn) saveBtn.classList.toggle('d-none', !editing);
    if(cancelBtn) cancelBtn.classList.toggle('d-none', !editing);
}

function _eptsCellContent(r, edit, key, vals) {
    const isEdit = edit && EPTS_EDIT_FIELDS.includes(key);
    const width = key === 'descripcion' ? '180' : (key === 'almacen_pool' ? '150' : '90');
    if(key === 'varias_ubicaciones') {
        return `<td class="text-center">${wmsBadgeValue(r.varias_ubicaciones, 'SÍ', 'bg-warning text-dark')}</td>`;
    }
    if(key === 'layout') {
        return `<td class="text-center">${wmsBadgeValue(r.layout, 'SÍ', 'bg-success text-white')}</td>`;
    }
    if(isEdit) {
        return `<td><input class="epts-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:${width}px; padding:2px 6px;" data-id="${_escPool(r.id)}" data-field="${key}" value="${_escPool(vals[key] !== undefined ? vals[key] : r[key])}" onchange="updateEptsEditValue(this)"></td>`;
    }
    if(key === 'descripcion') {
        return `<td><div style="max-width: 220px; overflow: hidden; text-overflow: ellipsis;" title="${_escPool(r.descripcion)}">${_escPool(r.descripcion)}</div></td>`;
    }
    if(key === 'auditoria') {
        return `<td class="text-nowrap small">${_escPool(r.auditoria || '')}</td>`;
    }
    return `<td>${_escPool(r[key] ?? '')}</td>`;
}

function renderEptsTable() {
    const thead = document.querySelector('#table-epts thead');
    const tbody = document.querySelector('#table-epts tbody');
    if(!thead || !tbody) return;

    thead.innerHTML = '<tr><th></th><th>Folio Físico</th>' + EPTS_COLUMNS.map(c => _wmsTh(c[1])).join('') + '</tr>';

    tbody.innerHTML = eptsData.map(r => {
        const chk = `<td class="text-center"><input type="checkbox" class="chk-epts-row" value="${_escPool(r.id)}"></td>`;
        const folioTd = `<td>${_escPool(r.folio)}</td>`;
        const vals = eptsEditValues[r.id] || {};
        const cells = EPTS_COLUMNS.map(c => _eptsCellContent(r, eptsEditMode, c[0], vals)).join('');
        return `<tr data-epts-id="${_escPool(r.id)}">${chk}${folioTd}${cells}</tr>`;
    }).join('');

    if(eptsTable) {
        eptsTable.destroy();
    }
    eptsTable = $('#table-epts').DataTable({
        pageLength: 50,
        lengthMenu: [25, 50, 100, 200],
        scrollX: true,
        language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
        order: [[1, 'asc']],
    });
    eptsTable.on('draw.dt', applyEptsEditInputs);

    const info = document.getElementById('epts-info');
    if(info) {
        info.innerHTML = `Total registros cargados: <strong>${eptsData.length}</strong> | Pestaña: EPTS. Paginación de 50 registros.`;
    }
}

function editSelectedEpts() {
    const idSet = new Set();
    document.querySelectorAll('input.chk-epts-row:checked').forEach(cb => idSet.add(cb.value));
    if(idSet.size === 0) return alert("Selecciona al menos un registro para editar (usa casillas).");

    eptsEditValues = {};
    idSet.forEach(id => {
        const rec = eptsData.find(r => String(r.id) === String(id));
        if(!rec) return;
        eptsEditValues[id] = {};
        EPTS_EDIT_FIELDS.forEach(f => { eptsEditValues[id][f] = rec[f] ?? ''; });
    });

    eptsEditMode = true;
    setEptsEditButtons(true);
    renderEptsTable();
    alert(`Modo edición activado para ${idSet.size} registro(s).\nEdita los campos y presiona "Confirmar y Guardar".`);
}

function updateEptsEditValue(input) {
    const id = input.dataset.id;
    const field = input.dataset.field;
    if(!eptsEditValues[id]) eptsEditValues[id] = {};
    eptsEditValues[id][field] = input.value;
}

function applyEptsEditInputs() {
    if(!eptsEditMode) return;
    document.querySelectorAll('tr[data-epts-id]').forEach(tr => {
        const id = tr.dataset.eptsId;
        if(!id || !eptsEditValues[id]) return;
        if(tr.querySelector('input.epts-edit-input')) return;
        const vals = eptsEditValues[id];
        const cells = Array.from(tr.querySelectorAll('td'));
        const baseIdx = 2;
        EPTS_COLUMNS.forEach((c, idx) => {
            const field = c[0];
            if(!EPTS_EDIT_FIELDS.includes(field)) return;
            const td = cells[baseIdx + idx];
            if(!td || td.querySelector('input')) return;
            const width = field === 'descripcion' ? '180' : (field === 'almacen_pool' ? '150' : '90');
            td.innerHTML = `<input class="epts-edit-input form-control form-control-sm bg-dark text-white border-secondary" style="min-width:${width}px; padding:2px 6px;" data-id="${_escPool(id)}" data-field="${field}" value="${_escPool(vals[field] ?? '')}" onchange="updateEptsEditValue(this)">`;
        });
    });
}

async function saveEditedEpts() {
    if(!eptsEditMode) return;
    const records = Object.keys(eptsEditValues).map(id => {
        const rec = { id: Number(id) };
        EPTS_EDIT_FIELDS.forEach(f => { rec[f] = eptsEditValues[id][f] ?? ''; });
        return rec;
    });
    if(records.length === 0) return;

    if(!confirm(`¿Confirmas guardar los cambios de ${records.length} registro(s) en EPTS?`)) return;

    try {
        const res = await fetch('/api/epts/update', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'epts', records})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            eptsEditMode = false;
            eptsEditValues = {};
            setEptsEditButtons(false);
            await loadEptsData();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    }
}

function cancelEditEpts() {
    eptsEditMode = false;
    eptsEditValues = {};
    setEptsEditButtons(false);
    renderEptsTable();
}

async function loadEptsData() {
    if(!document.getElementById('table-epts')) return;
    try {
        const res = await fetch('/api/epts/data');
        const json = await res.json();
        eptsData = json.data || [];
        renderEptsTable();
    } catch(e) {
        console.error('Error cargando EPTS:', e);
    }
}

/* =================== Comparativo EPTS (Query EPTS vs Datos EPTS) =================== */
let eptsCompTable = null;
let eptsCompData = [];

const EPTS_COMP_COLUMNS = [
    ['np', 'NP'],
    ['lote', 'Lote'],
    ['descripcion', 'Descripción'],
    ['unidad', 'Unidad'],
    ['empaque', 'Empaque'],
    ['almacen', 'Almacén'],
    ['almacen_pool', 'Ubicación'],
    ['varias_ubicaciones', 'Varias'],
    ['layout', 'Layout'],
    ['qty_odoo', 'QTY Odoo'],
    ['qty_conteo', 'QTY Conteo'],
    ['diff', 'DIFF'],
    ['accion', 'Acción'],
    ['ajuste', 'Ajuste'],
];

function _eptsCompProcedenciaBadge(p) {
    const map = {
        'AMBOS': ['bg-success text-white', 'AMBOS'],
        'SOLO ODOO': ['bg-info text-dark', 'SOLO ODOO'],
        'SOLO CONTEO': ['bg-warning text-dark', 'SOLO CONTEO'],
    };
    const [cls, label] = map[p] || ['bg-secondary text-white', p];
    return `<span class="badge ${cls} fw-bold">${label}</span>`;
}

function _eptsCompAccionBadge(a) {
    const map = {
        'BAJA': ['bg-danger text-white', 'BAJA'],
        'DISMINUYO': ['bg-warning text-dark', 'DISMINUYO'],
        'AUMENTO': ['bg-success text-white', 'AUMENTO'],
        'SIN CAMBIO': ['bg-secondary text-white', 'SIN CAMBIO'],
    };
    const [cls, label] = map[a] || ['bg-secondary text-white', a || ''];
    return `<span class="badge ${cls} fw-bold">${label}</span>`;
}

function _fmtNum(v) {
    const n = Number(v);
    return Number.isFinite(n) ? n.toLocaleString('en-US', {maximumFractionDigits: 4}) : '0';
}

function renderEptsComparativo() {
    const thead = document.querySelector('#table-epts-comp thead');
    const tbody = document.querySelector('#table-epts-comp tbody');
    if(!thead || !tbody) return;

    thead.innerHTML = '<tr><th>Procedencia</th>' + EPTS_COMP_COLUMNS.map(c => _wmsTh(c[1])).join('') + '</tr>';

    tbody.innerHTML = eptsCompData.map(r => {
        let cells = `<td>${_eptsCompProcedenciaBadge(r.procedencia)}</td>`;
        cells += EPTS_COMP_COLUMNS.map(([key, label]) => {
            if(key === 'qty_odoo' || key === 'qty_conteo') {
                return `<td class="text-end">${_fmtNum(r[key])}</td>`;
            }
            if(key === 'diff') {
                const n = Number(r.diff);
                const cls = n !== 0 ? 'text-danger fw-bold' : 'text-secondary';
                return `<td class="text-end ${cls}">${_fmtNum(n)}</td>`;
            }
            if(key === 'ajuste') {
                const n = Number(r.ajuste);
                const cls = n < 0 ? 'text-danger fw-bold' : (n > 0 ? 'text-success fw-bold' : 'text-secondary');
                return `<td class="text-end ${cls}">${_fmtNum(n)}</td>`;
            }
            if(key === 'accion') {
                return `<td class="text-center">${_eptsCompAccionBadge(r.accion)}</td>`;
            }
            if(key === 'varias_ubicaciones') {
                return `<td class="text-center">${variasBadge(r)}</td>`;
            }
            if(key === 'layout') {
                return `<td class="text-center">${layoutBadge(r)}</td>`;
            }
            if(key === 'descripcion') {
                return `<td><div style="max-width: 220px; overflow: hidden; text-overflow: ellipsis;" title="${_escPool(r.descripcion)}">${_escPool(r.descripcion)}</div></td>`;
            }
            return `<td>${_escPool(r[key] ?? '')}</td>`;
        }).join('');
        return `<tr>${cells}</tr>`;
    }).join('');

    if(eptsCompTable) {
        eptsCompTable.destroy();
    }
    eptsCompTable = $('#table-epts-comp').DataTable({
        pageLength: 50,
        lengthMenu: [25, 50, 100, 200],
        scrollX: true,
        language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
        order: [[0, 'asc']],
    });

    const info = document.getElementById('epts-comp-info');
    if(info) {
        const count = p => eptsCompData.filter(r => r.procedencia === p).length;
        info.innerHTML = `Total: <strong>${eptsCompData.length}</strong> | AMBOS: <strong>${count('AMBOS')}</strong> | SOLO ODOO: <strong>${count('SOLO ODOO')}</strong> | SOLO CONTEO: <strong>${count('SOLO CONTEO')}</strong>`;
    }
}

async function loadEptsComparativo() {
    if(!document.getElementById('table-epts-comp')) return;
    try {
        const res = await fetch('/api/epts/comparativo');
        const json = await res.json();
        eptsCompData = json.data || [];
        renderEptsComparativo();
    } catch(e) {
        console.error('Error cargando comparativo EPTS:', e);
    }
}

async function fillEptsUomEmpaque() {
    const btn = document.getElementById('btn-epts-uom');
    if(!btn) return;
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando UoM & Empaque...';
    try {
        const res = await fetch('/api/epts/fill_uom_empaque', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'epts'}) });
        const json = await res.json();
        if(json.success) {
            let extra = '';
            if(json.sync) extra = `\nComparativo EPTS: ${json.sync.msg}`;
            alert(`✅ UoM & Empaque actualizado.\n\nProcesados: ${json.processed}\nCon Unidad: ${json.with_uom}\nCon Empaque: ${json.with_empaque}${extra}`);
            await loadEptsData();
            await loadEptsComparativo();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🧮 UoM & Empaque';
    }
}

async function fillEptsLocationsQ2() {
    const btn = document.getElementById('btn-epts-q2');
    if(!btn) return;
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando Query 2 (puede tardar)...';
    try {
        const res = await fetch('/api/epts/fill_locations_q2', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({module: 'epts'}) });
        const json = await res.json();
        if(json.success) {
            let extra = '';
            if(json.sync) extra = `\nComparativo EPTS: ${json.sync.msg}`;
            alert(`✅ Ubicaciones Query 2 actualizado en epts_data.\n\nProcesados: ${json.processed}\nCoincidentes: ${json.matched_q2}\nCon Varias Ubicaciones: ${json.with_varias}${extra}`);
            await loadEptsData();
            await loadEptsComparativo();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '📍 Llenar Ubicaciones (Query 2)';
    }
}

async function uploadEptsFiles() {
    const btn = document.getElementById('btn-epts-upload');
    const fileInput = document.getElementById('epts-file');
    if(!fileInput || !fileInput.files.length) {
        return alert("Selecciona un archivo de Inventario de EPT's para cargar.");
    }
    const fd = new FormData();
    fd.append('module', 'epts');
    fd.append('file', fileInput.files[0]);
    const sheetInput = document.getElementById('epts-sheet');
    if(sheetInput && sheetInput.value.trim()) {
        fd.append('sheet', sheetInput.value.trim());
    }

    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando carga EPTS...';
    try {
        const res = await fetch('/api/epts/upload', { method: 'POST', body: fd });
        const json = await res.json();
        if(json.success) {
            alert('✅ ' + json.msg);
            await loadEptsData();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch(e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⬆️ Cargar y Reemplazar Datos EPTS';
    }
}

async function emptyEptsData() {
    const btn = document.getElementById('btn-epts-empty');
    if(!confirm("⚠️ ¿VACIAR el MODELO EPTS?\n\nEsto ELIMINARÁ todos los registros de epts_data (solo este módulo; no afecta Pool Final, WMS, Saldos, Etiquetas ni la Papelera de Auditoría).\n\n¿Deseas proceder?")) return;

    btn.disabled = true;
    btn.innerHTML = '⏳ Vaciando...';
    try {
        const res = await fetch('/api/epts/empty', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'epts'})
        });
        const json = await res.json();
        if(json.success) {
            alert("✅ " + json.msg);
            await loadEptsData();
        } else {
            alert("❌ ERROR: " + json.msg);
        }
    } catch(e) {
        alert("❌ Error: " + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🗑️ Vaciar Modelo EPTS';
    }
}

/* =================== Análisis Final =================== */

const AF_COLUMNS = [
    ['np', 'NP'],
    ['descripcion', 'Descripción'],
    ['almacen', 'Ubicación'],
    ['unidad', 'Unidad'],
    ['lote', 'Lote'],
    ['qty_odoo', 'QTY Odoo'],
    ['qty_conteo', 'QTY Conteo'],
    ['diff', 'DIFF'],
    ['accion', 'Acción'],
    ['ajuste', 'Ajuste'],
];

function _afDiff(d) {
    return Math.round((Number(d) || 0) * 10000) / 10000;
}

function _afAccion(qty_odoo, qty_conteo) {
    if (qty_odoo > qty_conteo && qty_conteo == 0) return 'BAJA';
    if (qty_odoo > qty_conteo && qty_conteo > 0) return 'DISMINUYO';
    if (qty_odoo < qty_conteo) return 'AUMENTO';
    return 'SIN CAMBIO';
}

function _afAjuste(accion, diff) {
    if (accion === 'BAJA') return _afDiff(diff);
    if (accion === 'AUMENTO' || accion === 'DISMINUYO') return _afDiff(diff * -1);
    if (accion === 'SIN CAMBIO') return 0;
    return 0;
}

function _afDiffCell(r) {
    const odoo = Number(r.qty_odoo) || 0;
    const conteo = Number(r.qty_conteo) || 0;
    const n = _afDiff(odoo - conteo);
    const cls = n !== 0 ? 'text-danger fw-bold' : 'text-secondary';
    return `<td class="text-end ${cls}">${_fmtNum(n)}</td>`;
}

function _afAccionCell(r) {
    const odoo = Number(r.qty_odoo) || 0;
    const conteo = Number(r.qty_conteo) || 0;
    const a = _afAccion(odoo, conteo);
    return `<td class="text-center">${_eptsCompAccionBadge(a)}</td>`;
}

function _afAjusteCell(r) {
    const odoo = Number(r.qty_odoo) || 0;
    const conteo = Number(r.qty_conteo) || 0;
    const a = _afAccion(odoo, conteo);
    const n = _afAjuste(a, _afDiff(odoo - conteo));
    const cls = n < 0 ? 'text-danger fw-bold' : (n > 0 ? 'text-success fw-bold' : 'text-secondary');
    return `<td class="text-end ${cls}">${_fmtNum(n)}</td>`;
}

const AF_BLOCK_TABS = {
    'B&A': { tableId: 'table-af-ba', countId: 'af-count-ba', infoId: 'af-info-ba' },
    'Insumos': { tableId: 'table-af-insumos', countId: 'af-count-insumos', infoId: 'af-info-insumos' },
    'Prop. Cliente': { tableId: 'table-af-propcte', countId: 'af-count-propcte', infoId: 'af-info-propcte' },
    'EPT': { tableId: 'table-af-ept', countId: 'af-count-ept', infoId: 'af-info-ept' },
};

let afData = [];
let afTables = {};

function renderAnalisisFinal() {
    for (const [bloque, cfg] of Object.entries(AF_BLOCK_TABS)) {
        const rows = afData.filter(r => r.bloque === bloque);
        const thead = document.querySelector(`#${cfg.tableId} thead`);
        const tbody = document.querySelector(`#${cfg.tableId} tbody`);
        if (!thead || !tbody) continue;

        thead.innerHTML = '<tr><th><input type="checkbox" class="af-check-all" data-block="' + bloque + '"></th>' +
            AF_COLUMNS.map(c => _wmsTh(c[1])).join('') + '</tr>';

        tbody.innerHTML = rows.map(r => {
            const isQc = (r.procedencia || '') === 'QC Query Auditoría 1';
            let cells = `<td><input type="checkbox" class="af-row-check" data-id="${r.id}"></td>`;
            cells += AF_COLUMNS.map(([key]) => {
                if (key === 'diff') return _afDiffCell(r);
                if (key === 'accion') return _afAccionCell(r);
                if (key === 'ajuste') return _afAjusteCell(r);
                if (key === 'qty_odoo' || key === 'qty_conteo') {
                    const n = Number(r[key]);
                    return `<td class="text-end">${_fmtNum(n)}</td>`;
                }
                if (key === 'descripcion') {
                    return `<td><div style="max-width:280px;overflow:hidden;text-overflow:ellipsis;" title="${_escPool(r.descripcion)}">${_escPool(r.descripcion)}</div></td>`;
                }
                if (key === 'almacen') {
                    return `<td><div style="max-width:300px;overflow:hidden;text-overflow:ellipsis;" title="${_escPool(r.almacen)}">${_escPool(r.almacen)}</div></td>`;
                }
if (key === 'lote' && r.bloque === 'EPT' && String(r[key] ?? '').toLowerCase() === 'nan') {
                    return '<td></td>';
                }
                return `<td>${_escPool(r[key] ?? '')}</td>`;
            }).join('');
            return `<tr class="${isQc ? 'af-qc-added' : ''}">${cells}</tr>`;
        }).join('');

        document.getElementById(cfg.countId).textContent = rows.length;
        document.getElementById(cfg.infoId).textContent = `Total: ${rows.length} items`;
        document.getElementById(cfg.countId).parentElement.style.display = rows.length ? '' : 'none';

        if (afTables[cfg.tableId]) afTables[cfg.tableId].destroy();
        afTables[cfg.tableId] = $(`#${cfg.tableId}`).DataTable({
            pageLength: 50,
            lengthMenu: [25, 50, 100, 200],
            scrollX: true,
            language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
            order: [[1, 'asc']],
        });
    }

    const summary = document.getElementById('af-summary');
    if (summary) {
        const total = afData.length;
        const mpCount = afData.filter(r => r.sheet === 'MP').length;
        const eptCount = afData.filter(r => r.sheet === 'EPT').length;
        const qcCount = afData.filter(r => (r.procedencia || '') === 'QC Query Auditoría 1').length;
        summary.innerHTML = `<div class="d-flex gap-4 flex-wrap fw-bold">
            <span>Total Cargado: <strong class="text-white">${total.toLocaleString()}</strong></span>
            <span class="text-info">Pestaña MP: <strong>${mpCount.toLocaleString()}</strong></span>
            <span class="text-warning">Pestaña EPT: <strong>${eptCount.toLocaleString()}</strong></span>
            <span class="badge" style="background:#fff3cd;color:#212529;">🟡 Agregados desde Query Auditoría 1: ${qcCount.toLocaleString()}</span>
            <span class="badge bg-secondary">Leyenda: filas amarillas = lotes agregados vía Auditoría QC</span>
        </div>`;
    }
}

async function loadAnalisisFinal() {
    if (!document.getElementById('table-af-ba')) return;
    try {
        const res = await fetch('/api/analisis_final/data');
        const json = await res.json();
        afData = json.data || [];
        renderAnalisisFinal();
        applyAFSearch();
        await loadAnalisisFinalAudit();
    } catch (e) {
        console.error('Error cargando Análisis Final:', e);
    }
}

function applyAFSearch() {
    const norm = (s) => (s || '').toString().trim().toUpperCase();
    const np = norm(document.getElementById('af-f-search')?.value);
    const desc = norm(document.getElementById('af-f-desc')?.value);
    const lote = norm(document.getElementById('af-f-lote')?.value);
    const active = document.querySelector('#af-tabs .nav-link.active');
    const blockMap = { '#tab-af-ba': 'B&A', '#tab-af-insumos': 'Insumos', '#tab-af-propcte': 'Prop. Cliente', '#tab-af-ept': 'EPT' };
    const bloque = active ? blockMap[active.getAttribute('href')] : null;

    for (const [b, c] of Object.entries(AF_BLOCK_TABS)) {
        const t = afTables[c.tableId];
        if (!t) continue;
        // Aplica los filtros solo a la tabla de la pestaña activa; resto se limpia
        if (b === bloque) {
            t.column(1).search(np, false, true)
                .column(2).search(desc, false, true)
                .column(5).search(lote, false, true);
        } else {
            t.column(1).search('').column(2).search('').column(5).search('');
        }
        t.draw();
    }
}

let afAuditData = [];
let afAuditTable = null;

function renderAnalisisFinalAudit() {
    const sev = (document.querySelector('input[name="af-aud-sev"]:checked') || {}).value || 'all';
    const rows = sev === 'all' ? afAuditData : afAuditData.filter(f => f.sev === sev);

    const thead = document.querySelector('#table-af-audit thead');
    const tbody = document.querySelector('#table-af-audit tbody');
    if (!thead || !tbody) return;

    thead.innerHTML = '<tr>' + ['Severidad', 'Hallazgo', 'Bloque', 'NP', 'QTY Odoo', 'QTY Conteo', 'Detalle', 'Estado', 'Acción'].map(h => `<th>${h}</th>`).join('') + '</tr>';

    const sevBadge = {
        super_critical: '<span class="badge fw-bold" style="background:#b30000;color:#fff;">🚨 SUPER CRITICAL</span>',
        critical: '<span class="badge bg-danger text-white fw-bold">CRITICAL</span>',
        warning: '<span class="badge bg-warning text-dark fw-bold">WARNING</span>',
        info: '<span class="badge bg-info text-dark fw-bold">INFO</span>',
    };
    const estadoBadge = {
        corregido: '<span class="badge bg-success text-white fw-bold">✔ Corregido</span>',
        anotado: '<span class="badge bg-warning text-dark fw-bold">📝 Anotado</span>',
        '': '<span class="badge bg-secondary text-white">Pendiente</span>',
    };
    const sevRow = {
        super_critical: 'table-danger',
        critical: 'table-danger',
        warning: 'table-warning',
        info: '',
    };
    tbody.innerHTML = rows.map(f => {
        const img = f.sev === 'super_critical'
            ? '<span class="badge fw-bold" style="background:#b30000;color:#fff;">🚨 SUPER CRITICAL</span>'
            : `<span class="badge ${f.sev === 'critical' ? 'bg-danger text-white' : (f.sev === 'warning' ? 'bg-warning text-dark' : 'bg-info text-dark')} fw-bold">${f.sev.toUpperCase()}</span>`;
        return `<tr class="${sevRow[f.sev] || ''}">
            <td>${img}</td>
            <td>${_escPool(f.tipo)}</td>
            <td>${_escPool(f.bloque)}</td>
            <td>${_escPool(f.np)}</td>
            <td class="text-end">${_fmtNum(f.qty_odoo)}</td>
            <td class="text-end">${_fmtNum(f.qty_conteo)}</td>
            <td>${_escPool(f.mensaje)}</td>
            <td>${estadoBadge[f.estado] || estadoBadge['']}</td>
            <td><button class="btn btn-sm btn-outline-light af-aud-review" data-fkey="${_escPool(String(f.fkey || ''))}" data-np="${_escPool(String(f.np || ''))}" data-bloque="${_escPool(String(f.bloque || ''))}">👁️ Revisar</button></td>
        </tr>`;
    }).join('');

    if (!afAuditTable) {
        afAuditTable = $('#table-af-audit').DataTable({
            pageLength: 25,
            lengthMenu: [10, 25, 50, 100],
            scrollX: true,
            language: { url: '//cdn.datatables.net/plug-ins/1.13.6/i18n/es-ES.json' },
            order: [[0, 'asc']],
        });
    }
}

function renderSkuCheckBanner(sku) {
    const el = document.getElementById('af-sku-check');
    if (!el) return;
    if (!sku) { el.innerHTML = ''; return; }
    if (sku.error) {
        el.innerHTML = `<div class="alert alert-warning py-2 mb-0 small fw-bold">⚠️ No se pudo verificar el total de SKU: ${_escPool(sku.error)}</div>`;
        return;
    }
    const a = _fmtNum(sku.archivo_skus);
    const m = _fmtNum(sku.modelo_skus);
    if (sku.coincide) {
        el.innerHTML = `<div class="alert alert-success py-2 mb-0 small fw-bold">✅ TOTAL SKU DEL ARCHIVO: ${a} = Modelo: ${m} · COINCIDE</div>`;
    } else {
        el.innerHTML = `<div class="alert alert-danger py-2 mb-0 small fw-bold blink" style="background:#b30000;color:#fff;">🚨 SUPER CRÍTICO: El total de SKU del archivo (${a}) NO coincide con el modelo (${m}). Acción requerida.</div>`;
    }
}

async function loadAnalisisFinalAudit() {
    if (!document.getElementById('table-af-audit')) return;
    try {
        const res = await fetch('/api/analisis_final/audit');
        renderAuditPayload(await res.json());
    } catch (e) {
        console.error('Error cargando auditoría Análisis Final:', e);
    }
}

function renderAuditPayload(json) {
    afAuditData = json.findings || [];
    afQ1Data = (json.summary?.query_auditoria?.grupos) || [];
    afQ1Resumen = json.summary?.query_auditoria?.resumen || null;
    document.getElementById('af-aud-critical').textContent = 'Critical: ' + (json.summary?.critical ?? 0);
    document.getElementById('af-aud-warning').textContent = 'Warning: ' + (json.summary?.warning ?? 0);
    document.getElementById('af-aud-info').textContent = 'Info: ' + (json.summary?.info ?? 0);
    const sc = document.getElementById('af-aud-super-crit');
    const scCount = json.summary?.super_critical ?? 0;
    sc.textContent = `Super Critical: ${scCount}`;
    sc.className = 'badge ' + (scCount > 0 ? 'text-white fw-bold' : 'bg-secondary') + (scCount > 0 ? ' blink' : '');
    if (scCount > 0) sc.style.background = '#b30000';
    else sc.style.background = '';
    document.getElementById('af-aud-total').textContent = 'Modelo: ' + (json.summary?.total ?? 0) + ' filas';
    renderSkuCheckBanner(json.summary?.sku_check);
    renderSkuQueryBanner(afQ1Resumen);
    if (afAuditTable) { afAuditTable.destroy(); afAuditTable = null; }
    renderAnalisisFinalAudit();
}

let afQ1Data = [];
let afQ1Resumen = null;

function renderSkuQueryBanner(qa) {
    const el = document.getElementById('af-q1-banner');
    if (!el) return;
    if (!qa) { el.innerHTML = ''; return; }
    if (qa.error) {
        el.innerHTML = `<div class="alert alert-warning py-2 mb-0 small fw-bold">⚠️ ${_escPool(qa.error)}</div>`;
        return;
    }
    const coincide = qa.coinciden ? '✅ Coinciden' : '❌ NO coinciden';
    const color = qa.coinciden ? 'success' : 'danger';
    const totalMissMod = qa.faltan_en_modelo ?? 0;
    const totalMissQ = qa.faltan_en_query ?? 0;
    el.innerHTML = `<div class="alert alert-${color} py-2 mb-0 small d-flex justify-content-between flex-wrap gap-2">
        <span class="fw-bold">🧪 Query Auditoría 1 — ${coincide}</span>
        <span>Query: <b>${_fmtNum(qa.query_rows)}</b> lotes · Modelo: <b>${_fmtNum(qa.modelo_rows)}</b> filas (<b>${_fmtNum(qa.modelo_con_lote || 0)}</b> con lote)</span>
        <span>Faltan en Modelo: <b class="text-danger">${_fmtNum(totalMissMod)}</b> lotes · Faltan en Query: <b class="text-warning">${_fmtNum(totalMissQ)}</b> lotes</span>
        <span>Grupos: <b>${_fmtNum(qa.grupos)}</b> · Hallazgos: <b>${_fmtNum(qa.hallazgos)}</b> · Tiempo: <b>${qa.tiempo_ms}ms</b></span>
    </div>`;
}

function openAnalisisFinalQ1Detail(fkey, np, bloque, idx) {
    const g = afQ1Data[idx];
    if (!g) return;
    let html = `<div class="small text-secondary mb-2">NP <b class="text-white">${_escPool(g.np)}</b> · Ubicación <b class="text-white">${_escPool(g.ubicacion)}</b> · Bloque <b class="text-white">${_escPool(g.bloque)}</b></div>`;
    const block = (title, color, lotes) => {
        if (!lotes || !lotes.length) return '';
        return `<div class="mb-2"><b class="text-${color}">${title} (${lotes.length})</b><div class="d-flex flex-wrap gap-1 mt-1">` +
            lotes.map(l => `<span class="badge bg-secondary text-white">${_escPool(l)}</span>`).join(' ') + '</div></div>';
    };
    html += block('🔹 Lotes en Query', 'info', g.lotes_query);
    html += block('🔸 Lotes en Modelo', 'secondary', g.lotes_modelo);
    const fmq = (g.faltan_en_modelo_qty || []).filter(Boolean).filter(x => x && x.lote);
    const sevWarn = (g.sev === 'warning');
    if ((g.faltan_en_modelo || []).length && !fmq.length) {
        html += block((sevWarn ? '⚠️' : '❌') + ' Faltan en Modelo (Query tiene, AF no)', sevWarn ? 'warning' : 'danger', g.faltan_en_modelo);
    } else if (fmq.length) {
        html += `<div class="mb-2"><b class="text-${sevWarn ? 'warning' : 'danger'}">${sevWarn ? '⚠️' : '❌'} Faltan en Modelo (Query tiene, AF no) (${fmq.length})</b><div class="d-flex flex-wrap gap-1 mt-1">` +
            fmq.map(x => `<span class="badge ${sevWarn ? 'bg-warning text-dark' : 'bg-danger text-white'}">${_escPool(x.lote)} <span class="${sevWarn ? 'text-danger' : 'text-warning'} fw-bold">(${_fmtNum(x.qty)})</span></span>`).join(' ') +
            '</div></div>';
    }
    html += block((sevWarn ? '⚠️' : '❌') + ' Faltan en Query (AF tiene, Query no)', sevWarn ? 'warning' : 'danger', g.faltan_en_query);
    html += `<div class="small text-muted mt-2">QTY Odoo: ${_fmtNum(g.qty_odoo)} · QTY Conteo: ${_fmtNum(g.qty_conteo)}</div>`;
    if (fmq.length && g.puede_agregar) {
        html += `<div class="mt-2 pt-2 border-top border-secondary">
            <button class="btn btn-success btn-sm fw-bold" id="btn-af-add-lotes" data-fk="${_escPool(fkey)}" onclick="addAnalisisFinalLotes(this.dataset.fk)">➕ Agregar ${fmq.length} lote(s) al modelo</button>
            <div class="small text-secondary mt-1">Regla por lote: cada lote del Query sin línea (o sin conteo) en el modelo se agrega copiando la info de la fila del NP; solo el lote y la cantidad del Query (qty_conteo 0). Aplica a B&A, Insumos y Prop. Cliente.</div>
        </div>`;
    } else if (fmq.length) {
        const avisoEpt = (g.bloque === 'EPT' && sevWarn)
            ? '⚠️ EPTs: solo auditoría informativa — no se agrega nada al modelo en esta ubicación. Al cargar existencias bajan a 0 y se sube todo nuevo.'
            : '⚠️ No se puede agregar ahora: revisa el estado del hallazgo en el modelo.';
        html += `<div class="mt-2 pt-2 border-top border-secondary small ${sevWarn ? 'text-warning' : 'text-muted'}">${avisoEpt}</div>`;
    }
    document.getElementById('af-audit-modal-body').innerHTML = html;
    document.getElementById('af-audit-modal-title').textContent = '👁️ Revisar Hallazgo Query Auditoría 1';
    window._afAuditFkey = fkey;
    const estado = g.estado || '';
    document.getElementById('af-state-corregido').checked = (estado === 'corregido');
    document.getElementById('af-state-anotado').checked = (estado === 'anotado');
    document.getElementById('af-state-nota').value = g.nota || '';
    $('#modal-af-audit').modal('show');
}

async function addAnalisisFinalLotes(fkey) {
    const g = afQ1Data.find(x => (x.fkey || '') === fkey);
    const n = (g?.faltan_en_modelo_qty || []).length || 0;
    if (!confirm(`¿Agregar ${n} lote(s) de ${g ? g.np : fkey} al modelo Análisis Final?`)) return;
    const btn = document.getElementById('btn-af-add-lotes');
    if (btn) { btn.disabled = true; btn.innerHTML = '⏳ Agregando...'; }
    try {
        const res = await fetch('/api/analisis_final/audit/add_lotes', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ module: 'analisis_final', fkeys: [fkey] })
        });
        const json = await res.json();
        const r = json.results?.[fkey] || {};
        if (json.success && r.ok) {
            alert('✅ ' + r.msg);
            if (json.audit) renderAuditPayload(json.audit);
        } else {
            alert('❌ ERROR: ' + (r.msg || json.msg || 'No se pudo agregar.'));
            if (json.audit) renderAuditPayload(json.audit);
        }
    } catch (e) {
        alert('❌ Error: ' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '➕ Agregar al modelo'; }
    }
}

async function openAnalisisFinalAuditDetail(fkey, np, bloque) {
    try {
        const params = new URLSearchParams({ np: np });
        if (bloque) params.set('bloque', bloque);
        const res = await fetch('/api/analisis_final/audit/detail?' + params.toString());
        const json = await res.json();
        if (!json.blocks || !json.blocks.length) {
            document.getElementById('af-audit-modal-body').innerHTML = '<p class="text-warning">No se encontraron filas para este hallazgo.</p>';
        } else {
            let html = `<div class="small text-secondary mb-2">NP <b class="text-white">${_escPool(json.np || '(vacío)')}</b> — ${json.blocks.reduce((a, b) => a + b.count, 0)} fila(s) en ${json.blocks.length} bloque(s).</div>`;
            json.blocks.forEach(b => {
                html += `<h6 class="mt-3 fw-bold text-warning">📦 ${_escPool(b.bloque)} <span class="badge bg-secondary ms-1">${b.count} filas</span></h6>`;
                html += `<div class="table-responsive"><table class="table table-sm table-dark table-striped w-100" style="font-size:0.8rem;">
                    <thead><tr><th>NP</th><th>Descripción</th><th>Unidad</th><th>Lote</th><th class="text-end">QTY Odoo</th><th class="text-end">QTY Conteo</th></tr></thead><tbody>`;
                b.filas.forEach(x => {
                    html += `<tr><td>${_escPool(x.np)}</td><td>${_escPool(x.descripcion)}</td><td>${_escPool(x.unidad)}</td><td>${_escPool(x.lote)}</td><td class="text-end">${_fmtNum(x.qty_odoo)}</td><td class="text-end">${_fmtNum(x.qty_conteo)}</td></tr>`;
                });
                html += `<tr class="table-active"><td colspan="4" class="fw-bold">Subtotal</td><td class="text-end fw-bold">${_fmtNum(b.total_odoo)}</td><td class="text-end fw-bold">${_fmtNum(b.total_conteo)}</td></tr></tbody></table></div>`;
            });
            document.getElementById('af-audit-modal-body').innerHTML = html;
        }
        document.getElementById('af-audit-modal-title').textContent = '👁️ Revisar Hallazgo' + (fkey ? '  ·  ' + fkey : '');
        window._afAuditFkey = fkey;
        const finding = afAuditData.find(x => (x.fkey || '') === fkey) || {};
        const estado = finding.estado || '';
        const nota = finding.nota || '';
        const rbCorregido = document.getElementById('af-state-corregido');
        const rbAnotado = document.getElementById('af-state-anotado');
        rbCorregido.checked = (estado === 'corregido');
        rbAnotado.checked = (estado === 'anotado');
        document.getElementById('af-state-nota').value = nota;
        $('#modal-af-audit').modal('show');
    } catch (e) {
        console.error('Error cargando detalle del hallazgo:', e);
        alert('❌ Error cargando detalle: ' + e.message);
    }
}

async function saveAnalisisFinalAuditState() {
    const rb = document.querySelector('input[name="af-state"]:checked');
    if (!rb) { return alert('Selecciona un estado (Corregido o Anotado).'); }
    const estado = rb.value;
    const nota = document.getElementById('af-state-nota').value.trim();
    const fkey = window._afAuditFkey || '';
    if (!fkey) { return alert('Falta la clave del hallazgo.'); }
    if (estado === 'anotado' && !nota) { return alert('Debes escribir una nota al marcar "Anotado".'); }
    try {
        const res = await fetch('/api/analisis_final/audit/state', {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ module: 'analisis_final', fkey, estado, nota })
        });
        const json = await res.json();
        if (json.success) {
            $('#modal-af-audit').modal('hide');
            await loadAnalisisFinalAudit();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch (e) {
        alert('❌ Error: ' + e.message);
    }
}

async function uploadAnalisisFinal() {
    const btn = document.getElementById('btn-af-upload');
    const fileInput = document.getElementById('af-file');
    if (!fileInput || !fileInput.files.length) {
        return alert("Selecciona un archivo de Inventario MP para cargar.");
    }
    const fd = new FormData();
    fd.append('module', 'analisis_final');
    fd.append('file', fileInput.files[0]);
    btn.disabled = true;
    btn.innerHTML = '⏳ Procesando...';
    try {
        const res = await fetch('/api/analisis_final/upload', { method: 'POST', body: fd });
        const json = await res.json();
        if (json.success) {
            const s = json.stats || {};
            alert(`✅ ${json.msg}\nMP: ${s.mp_total || 0} total, ${s.mp_loaded || 0} cargados | EPT: ${s.ept_total || 0}\nBloques: ${JSON.stringify(s.bloques || {})}`);
            await loadAnalisisFinal();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch (e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '⬆️ Cargar Excel';
    }
}

async function fillAnalisisFinalUom() {
    const btn = document.getElementById('btn-af-uom');
    btn.disabled = true;
    btn.innerHTML = '⏳ Actualizando UDM...';
    try {
        const res = await fetch('/api/analisis_final/fill_uom', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'analisis_final'})
        });
        const json = await res.json();
        if (json.success) {
            alert(`✅ UDM actualizada.\nProcesados: ${json.processed}\nMatch Query 1: ${json.matched_q1}\nCon Unidad: ${json.with_uom}\nCon Empaque: ${json.with_empaque}\nActualizados: ${json.updated}`);
            await loadAnalisisFinal();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch (e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '🧮 Actualizar UDM';
    }
}

async function fillAnalisisFinalDesc() {
    const btn = document.getElementById('btn-af-desc');
    btn.disabled = true;
    btn.innerHTML = '⏳ Actualizando Descripción...';
    try {
        const res = await fetch('/api/analisis_final/fill_descriptions', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'analisis_final'})
        });
        const json = await res.json();
        if (json.success) {
            alert(`✅ Descripción actualizada.\nProcesados: ${json.processed}\nMatch Query 1: ${json.matched_q1}\nCon Descripción: ${json.with_desc}\nActualizados: ${json.updated}`);
            await loadAnalisisFinal();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch (e) {
        alert('❌ Error: ' + e.message);
    } finally {
        btn.disabled = false;
        btn.innerHTML = '📝 Actualizar Descripción';
    }
}

function exportAnalisisFinalExcel() {
    const activeTab = document.querySelector('#af-tabs .nav-link.active');
    const href = activeTab ? activeTab.getAttribute('href') : '';
    const blockMap = { '#tab-af-ba': 'B&A', '#tab-af-insumos': 'Insumos', '#tab-af-propcte': 'Prop. Cliente', '#tab-af-ept': 'EPT' };
    const bloque = blockMap[href] || '';
    window.location.href = '/api/analisis_final/export' + (bloque ? '?bloque=' + encodeURIComponent(bloque) : '');
}

async function deleteSelectedAnalisisFinal() {
    const checks = document.querySelectorAll('.af-row-check:checked');
    if (!checks.length) return alert('Selecciona al menos una fila para eliminar.');
    if (!confirm(`¿Eliminar ${checks.length} registro(s) permanentemente?`)) return;
    const ids = Array.from(checks).map(c => Number(c.dataset.id));
    try {
        const res = await fetch('/api/analisis_final/delete', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'analisis_final', ids})
        });
        const json = await res.json();
        if (json.success) {
            alert('✅ ' + json.msg);
            await loadAnalisisFinal();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch (e) {
        alert('❌ Error: ' + e.message);
    }
}

async function emptyAnalisisFinal() {
    if (!confirm('¿Vaciar todo el Modelo de Análisis Final? Esta acción es irreversible.')) return;
    try {
        const res = await fetch('/api/analisis_final/empty', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({module: 'analisis_final'})
        });
        const json = await res.json();
        if (json.success) {
            alert('✅ ' + json.msg);
            await loadAnalisisFinal();
        } else {
            alert('❌ ERROR: ' + json.msg);
        }
    } catch (e) {
        alert('❌ Error: ' + e.message);
    }
}

document.addEventListener('DOMContentLoaded', function() {
    if (document.getElementById('table-af-ba')) {
        loadAnalisisFinal();
        document.querySelectorAll('#af-tabs .nav-link').forEach(el => {
            el.addEventListener('shown.bs.tab', applyAFSearch);
        });
        document.querySelectorAll('.af-check-all').forEach(el => {
            el.addEventListener('change', function() {
                const block = this.dataset.block;
                const tbody = document.querySelector(`#table-af-${block === 'Prop. Cliente' ? 'propcte' : block.toLowerCase()} tbody`);
                if (tbody) tbody.querySelectorAll('.af-row-check').forEach(c => c.checked = this.checked);
            });
        });
        document.querySelectorAll('.af-aud-filter').forEach(el => {
            el.addEventListener('change', function() {
                if (afAuditTable) { afAuditTable.destroy(); afAuditTable = null; }
                renderAnalisisFinalAudit();
            });
        });
        const auditTableEl = document.getElementById('table-af-audit');
        if (auditTableEl) {
            auditTableEl.addEventListener('click', function() {
                const btn = event.target.closest('.af-aud-review');
                if (!btn) return;
                const fkey = btn.dataset.fkey || '';
                if (fkey.startsWith('Q1::')) {
                    const idx = afQ1Data.findIndex(g => (g.fkey || '') === fkey);
                    openAnalisisFinalQ1Detail(fkey, btn.dataset.np || '', btn.dataset.bloque || '', idx);
                } else {
                    openAnalisisFinalAuditDetail(fkey, btn.dataset.np || '', btn.dataset.bloque || '');
                }
            });
        }
    }
});

// ===================== MÓDULO PT (PRODUCTO TERMINADO) =====================

function toggleWmsPass(btn) {
    const input = btn.closest('.input-group').querySelector('input');
    if (!input) return;
    input.type = input.type === 'password' ? 'text' : 'password';
}

function collectWmsFields() {
    const wms = {};
    document.querySelectorAll('.wms-field').forEach(el => {
        const key = el.dataset.wms;
        const field = el.dataset.field;
        if (!wms[key]) wms[key] = {};
        wms[key][field] = el.value;
    });
    return wms;
}

async function saveWmsConnections() {
    const wms = collectWmsFields();
    const btn = document.querySelector('button[onclick="saveWmsConnections()"]');
    if (btn) { btn.disabled = true; btn.textContent = '⌛ Guardando...'; }
    const alertDiv = document.getElementById('wms-conn-alert');
    try {
        const res = await fetch('/api/config/pt_wms', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({wms})
        });
        const json = await res.json();
        alertDiv.innerHTML = json.success
            ? '<span class="text-success fw-bold">✅ Conexiones WMS guardadas.</span>'
            : `<span class="text-danger fw-bold">❌ ${json.error}</span>`;
    } catch(e) {
        alertDiv.innerHTML = `<span class="text-danger fw-bold">❌ ${e.message}</span>`;
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Guardar Conexiones WMS'; }
    }
}

async function testWmsConnections() {
    const wms = collectWmsFields();
    const btn = document.querySelector('button[onclick="testWmsConnections()"]');
    if (btn) { btn.disabled = true; btn.textContent = '⌛ Probando...'; }
    const alertDiv = document.getElementById('wms-conn-alert');
    try {
        const res = await fetch('/api/config/pt_wms_test', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({wms})
        });
        const json = await res.json();
        if (!json.success) {
            alertDiv.innerHTML = `<span class="text-danger fw-bold">❌ ${json.error}</span>`;
            return;
        }
        const results = json.results || {};
        let html = '<div class="mt-1">';
        for (const [key, r] of Object.entries(results)) {
            const ok = r.success;
            html += `<div class="d-flex align-items-center gap-2 mb-1">
                <span class="badge ${ok ? 'bg-success' : 'bg-danger'}">${ok ? 'OK' : 'FALLO'}</span>
                <strong>${key}</strong>
                <span class="text-muted small">${ok ? '' : (r.error || '')}</span>
            </div>`;
        }
        html += '</div>';
        alertDiv.innerHTML = html;
    } catch(e) {
        alertDiv.innerHTML = `<span class="text-danger fw-bold">❌ ${e.message}</span>`;
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = 'Probar Todas las Conexiones WMS'; }
    }
}

async function saveTestPtQuery(key) {
    const textarea = document.querySelector(`.pt-query-input[data-key="${key}"]`);
    const btn = document.querySelector(`.pt-save-test[data-key="${key}"]`);
    const resultDiv = document.getElementById(`pt-result-${key}`);
    if (!textarea || !btn || !resultDiv) return;
    const query = textarea.value;
    btn.disabled = true;
    btn.textContent = '⌛ Guardando y probando...';
    resultDiv.style.display = 'block';
    resultDiv.innerHTML = '<div class="text-info small">Ejecutando contra la base de datos...</div>';
    try {
        const res = await fetch('/api/config/pt_query', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({key, query})
        });
        const json = await res.json();
        if (!json.success && json.error) {
            resultDiv.innerHTML = `<div class="text-danger small">Error general: ${json.error}</div>`;
        } else {
            renderPtResult(resultDiv, json.test);
        }
    } catch(e) {
        resultDiv.innerHTML = `<div class="text-danger small">Error: ${e.message}</div>`;
    } finally {
        btn.disabled = false;
        btn.textContent = btn.dataset.update === 'true' ? '💾 Validar y Guardar Query' : '💾 Guardar y Probar Query';
    }
}

function renderPtResult(container, t) {
    if (!t) {
        container.innerHTML = '<div class="text-danger small">Sin resultado.</div>';
        return;
    }
    if (!t.success) {
        container.innerHTML = `<div class="alert alert-danger py-1 px-2 mb-0 small">
            <strong>❌ Error (${t.tiempo_ms !== undefined ? t.tiempo_ms + ' ms' : 'sin pruebas'}):</strong> ${t.error}
        </div>`;
        return;
    }
    let preview = '';
    if (t.preview && t.preview.length) {
        const cols = t.columnas || Object.keys(t.preview[0] || {});
        const head = cols.map(c => `<th class="small">${c}</th>`).join('');
        const body = t.preview.map(row => {
            const tds = cols.map(c => `<td class="small">${row[c] !== undefined ? row[c] : ''}</td>`).join('');
            return `<tr>${tds}</tr>`;
        }).join('');
        preview = `<div class="table-responsive mt-1" style="max-height:180px;">
            <table class="table table-sm table-dark table-bordered mb-0"><thead class="thead-dark">${head}</thead><tbody>${body}</tbody></table>
        </div>
        ${t.filas > 3 ? `<div class="text-muted small mt-1">... y ${t.filas - 3} fila(s) más</div>` : ''}`;
    }
    if (t.is_update) {
        container.innerHTML = `<div class="alert alert-success py-1 px-2 mb-0 small">
            <strong>✅ Query validado y guardado correctamente.</strong>
        </div>`;
    } else if (t.solo_validacion) {
        container.innerHTML = `<div class="alert alert-success py-1 px-2 mb-0 small">
            <strong>✅ Estructura del query validada y guardada correctamente.</strong>
        </div>`;
    } else {
        container.innerHTML = `<div class="alert alert-success py-1 px-2 mb-0 small">
            <strong>✅ OK:</strong> ${t.filas} fila(s) devueltas en ${t.tiempo_ms} ms${t.columnas && t.columnas.length ? ` | Columnas: ${t.columnas.join(', ')}` : ''}
        </div>${preview}`;
    }
}

document.addEventListener('DOMContentLoaded', function() {
    document.querySelectorAll('.pt-save-test').forEach(btn => {
        btn.addEventListener('click', function() {
            saveTestPtQuery(this.dataset.key);
        });
    });
});
