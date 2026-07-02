import os
import json
import pandas as pd
from tqdm import tqdm
import duckdb

# CONFIG
CSV_DIR = "/home/ubuntu/politics-bert_old/scripts/genesis_csv_data"
METADATA_DIR = "/home/ubuntu/politics-bert_old/scripts/genesis_metadata"
OUTPUT_FILE = "/home/ubuntu/destatis-rag/backend/data/values_index.json"

def get_categorical_values(csv_path, max_values=50):
    """
    Reads a CSV and returns unique values for string columns.
    Limits to 'max_values' to avoid exploding index size.
    """
    try:
        # Read only first few rows to infer types? No, we need full unique scan.
        # Use DuckDB for speed on larger files.
        conn = duckdb.connect()
        
        # Get columns
        df_sample = pd.read_csv(csv_path, sep=';', nrows=5, encoding='utf-8', on_bad_lines='skip')
        str_cols = df_sample.select_dtypes(include=['object']).columns
        
        values_map = {}
        for col in str_cols:
            if col in ['Code', 'Unbekannt']: continue # Skip generic keys if needed
            
            # Efficient unique query
            query = f"SELECT DISTINCT \"{col}\" FROM read_csv_auto('{csv_path}', delim=';') LIMIT {max_values + 1}"
            unique_vals = conn.execute(query).fetchall()
            unique_vals = [u[0] for u in unique_vals if u[0]]
            
            if len(unique_vals) <= max_values:
                values_map[col] = unique_vals
            else:
                values_map[col] = unique_vals[:max_values] + ["..."]
                
        return values_map
    except Exception as e:
        # print(f"Error processing {csv_path}: {e}")
        return {}

def main():
    if not os.path.exists(os.path.dirname(OUTPUT_FILE)):
        os.makedirs(os.path.dirname(OUTPUT_FILE))
        
    index = {}
    
    files = [f for f in os.listdir(CSV_DIR) if f.endswith('.csv')]
    print(f"Scanning {len(files)} CSVs for value domains...")
    
    for f_name in tqdm(files):
        table_code = f_name.replace('.csv', '')
        csv_path = os.path.join(CSV_DIR, f_name)
        
        vals = get_categorical_values(csv_path)
        if vals:
            index[table_code] = vals
            
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
        
    print(f"Done. Index saved to {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
