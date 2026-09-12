import pandas as pd

REQUIRED_SHEETS = [
    'cubetas', 'tambores', 'tapas cub', 'botella', 
    'garrafa', 'tapa env', 'corrugado'
]

def parse_excel_for_marbetes(filepath):
    try:
        # Load all sheets to handle missing gracefully or specifically process required
        excel_data = pd.read_excel(filepath, sheet_name=None)
    except Exception as e:
        raise Exception(f"Failed to read Excel file: {str(e)}")

    marbetes = []
    
    # Create a case-insensitive mapping of actual sheets in the file
    actual_sheets_lower = {k.lower(): k for k in excel_data.keys()}
    
    for req_sheet in REQUIRED_SHEETS:
        req_sheet_lower = req_sheet.lower()
        if req_sheet_lower not in actual_sheets_lower:
            continue # Skip if sheet doesn't exist
            
        actual_sheet_name = actual_sheets_lower[req_sheet_lower]
        df = excel_data[actual_sheet_name]
        
        # Ensure base columns exist
        base_cols = [col for col in df.columns if str(col).strip().upper() in ['NP', 'DESCRIPCION', 'DESCRIPCIÓN', 'TIPO']]
        
        # Identify possible 'Nave' columns
        # We assume any column that isn't NP, Descripcion, Tipo, or unnamed could be a nave/almacen
        skip_cols = [c.upper() for c in base_cols]
        nave_cols = [col for col in df.columns if str(col).upper() not in skip_cols and not str(col).startswith('Unnamed')]

        for index, row in df.iterrows():
            np_val = row.get('NP', '')
            desc_val = row.get('Descripción', row.get('DESCRIPCION', ''))
            tipo_val = row.get('Tipo', row.get('TIPO', ''))
            
            if pd.isna(np_val) or str(np_val).strip() == '':
                continue
                
            np_str = str(np_val).strip().upper()
            
            # Check nave columns
            for nave in nave_cols:
                val = row.get(nave)
                if pd.isna(val):
                    continue
                    
                val_str = str(val).strip().lower()
                # Check for marks indicating presence (including '1.0' from excel floats)
                if val_str in ['true', '1', '1.0', 'x', 'si', 'sí', 'yes']:
                    marbetes.append({
                        'np': np_str,
                        'descripcion': str(desc_val).strip(),
                        'tipo': str(tipo_val).strip(),
                        'almacen': str(nave).strip(),
                        'sheet': actual_sheet_name
                    })

    return marbetes

def extract_unique_nps(filepath):
    marbetes = parse_excel_for_marbetes(filepath)
    unique_nps = list(set([m['np'] for m in marbetes]))
    return unique_nps
