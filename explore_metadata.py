import pandas as pd
import json
import os

METADATA_PATH = "/home/ubuntu/destatis-rag/soep_metadata_output/soep_metadata_registry.json"

def explore_metadata():
    if not os.path.exists(METADATA_PATH):
        print(f"Error: Metadata file not found at {METADATA_PATH}")
        print("Please run soep_download.R first (in Positron/R).")
        return

    # Load JSON
    with open(METADATA_PATH, 'r') as f:
        data = json.load(f)
    
    df = pd.DataFrame(data)
    
    print(f"--- SOEP Metadata Overview ---")
    print(f"Total Variables: {len(df)}")
    print(f"Datasets found: {df['dataset'].unique()}")
    
    # Show sample
    print("\n--- First 5 Variables Sample ---")
    print(df[['variable_name', 'label', 'dataset']].head())
    
    # Inspect a specific one
    print("\n--- Detailed View (First Variable) ---")
    first = data[0]
    for k, v in first.items():
        if k != "embedding_context":
            print(f"{k}: {v}")
    
    print("\n[Current Embedding Context Preview]")
    print(first["embedding_context"])

if __name__ == "__main__":
    explore_metadata()
