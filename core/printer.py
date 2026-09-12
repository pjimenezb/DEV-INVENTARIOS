import subprocess
import time
import os

class PrintState:
    def __init__(self):
        self.paused = False
        self.stopped = False
        self.paper_count = 0
        self.current_file = ""

# Global state
state = PrintState()

def get_printers():
    try:
        result = subprocess.run(['lpstat', '-e'], capture_output=True, text=True)
        if result.returncode != 0:
            return []
            
        printers = []
        for line in result.stdout.split('\n'):
            line = line.strip()
            if line:
                printers.append(line)
        return printers
    except Exception as e:
        print(f"Error getting printers: {e}")
        return []

def print_pdf(printer_name, filepath):
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"PDF no encontrado: {filepath}")
        
    cmd = ['lp', '-d', printer_name, filepath]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise Exception(f"Error en CUPS: {result.stderr}")
    return True

def print_batch_job(printer_name, pdf_dir, batch_size, sleep_time):
    global state
    state.stopped = False
    
    if not printer_name:
        yield 'data: {"status": "error", "msg": "[ERROR] No se seleccionó impresora"}\n\n'
        return

    # Get all PDFs recursively (since they are in sheet subfolders)
    files = []
    for root, dirs, filenames in os.walk(pdf_dir):
        for f in filenames:
            if f.endswith('.pdf'):
                files.append(os.path.join(root, f))
                
    # Sort files naturally based on folios
    files.sort(key=lambda x: os.path.basename(x))

    if not files:
        yield 'data: {"status": "error", "msg": "[ERROR] No hay archivos PDF para imprimir"}\n\n'
        return

    total_files = len(files)
    yield f'data: {{"status": "info", "msg": "[INFO] Iniciando impresión de {total_files} PDFs..."}}\n\n'

    batch_count = 0
    for i, filepath in enumerate(files):
        filename = os.path.basename(filepath)
        
        # Check pause
        while state.paused and not state.stopped:
            time.sleep(1)
            
        if state.stopped:
            yield f'data: {{"status": "error", "msg": "[ERROR] Proceso detenido manualmente en el archivo {filename}"}}\n\n'
            return

        # Check paper
        if state.paper_count <= 0:
            yield 'data: {"status": "pause", "msg": "[ALERTA] Sin papel en la bandeja. Por favor, recarga y reanuda."}\n\n'
            state.paused = True
            while state.paused and not state.stopped:
                time.sleep(1)
            if state.stopped:
                yield f'data: {{"status": "error", "msg": "[ERROR] Proceso detenido manualmente en el archivo {filename}"}}\n\n'
                return

        state.current_file = filename
        try:
            print_pdf(printer_name, filepath)
            state.paper_count -= 1
            yield f'data: {{"status": "info", "msg": "[INFO] Imprimiendo: {filename} ({i+1}/{total_files}). Hojas restantes: {state.paper_count}"}}\n\n'
        except Exception as e:
            yield f'data: {{"status": "error", "msg": "[ERROR] Falla en {filename}: {str(e)}"}}\n\n'
            state.paused = True # Pause on error
            yield 'data: {"status": "pause", "msg": "[ALERTA] Proceso pausado por error. Resuelve y reanuda."}\n\n'

        batch_count += 1
        
        # Check if we need to pause for logistic batching
        if batch_count >= batch_size and (i + 1) < total_files:
            yield f'data: {{"status": "info", "msg": "[INFO] Lote de {batch_size} completado. Pausa logística de {sleep_time}s..."}}\n\n'
            
            # Wait sleep_time, but allow interruption if stopped
            slept = 0
            while slept < sleep_time and not state.stopped:
                time.sleep(1)
                slept += 1
                
            if state.stopped:
                yield f'data: {{"status": "error", "msg": "[ERROR] Proceso detenido manualmente."}}\n\n'
                return
                
            batch_count = 0

    yield 'data: {"status": "done", "msg": "[EXITO] Proceso de impresión masiva finalizado correctamente."}\n\n'
