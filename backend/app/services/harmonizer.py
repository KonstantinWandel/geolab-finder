import pandas as pd
import os
import difflib
from datetime import datetime

class HarmonizerService:
    def __init__(self):
        self.region_map = self._load_region_map()
        self.name_to_ags = {str(row['Name']).lower(): str(row['AGS']) for _, row in self.region_map.iterrows()}

    def _load_region_map(self):
        path = os.getenv("DESTATIS_RAG_REGION_MAP_PATH", "app/data/region_map.csv")
        # Fallback absolute path if needed
        if not os.path.exists(path):
            path = "/app/data/region_map.csv"
        
        try:
            return pd.read_csv(path, dtype=str)
        except Exception as e:
            print(f"Error loading region map: {e}")
            return pd.DataFrame(columns=["AGS", "Name"])

    def harmonize(self, raw_data: list, source_type: str) -> list:
        """
        Transforms raw data list to CDM.
        CDM: [temporal_id, spatial_id, spatial_type, variable_id, value, source]
        """
        if not raw_data:
            return []
            
        df = pd.DataFrame(raw_data)
        cdm_rows = []
        
        # Heuristics to find columns
        cols = df.columns.astype(str).str.lower()
        
        # 1. TIME
        time_col = next((c for c in cols if 'jahr' in c or 'date' in c or 'time' in c or 'zeit' in c), None)
        
        # 2. SPACE
        space_col = next((c for c in cols if 'ort' in c or 'stadt' in c or 'region' in c or 'land' in c or 'ags' in c), None)
        
        # 3. VALUE
        val_cols = [c for c in cols if c != time_col and c != space_col]
        # Skip purely ID cols if possible
        val_cols = [c for c in val_cols if 'id' not in c or 'value' in c]
        val_col = val_cols[0] if val_cols else None
        
        if not time_col or not val_col:
            return [{"error": "Could not auto-harmonize. Missing standard Time/Value columns.", "raw": str(raw_data[:1])}]

        for _, row in df.iterrows():
            # Spatial ID Lookup
            raw_space = str(row.get(space_col, 'Deutschland')) # Default to nation if no space
            space_id = self._lookup_ags(raw_space)
            
            # Time Normalization (Year only for now)
            raw_time = str(row.get(time_col, datetime.now().year))
            temporal_id = raw_time.split('-')[0].split('.')[0] # 2023-01 -> 2023
            
            cdm_rows.append({
                "temporal_id": temporal_id,
                "spatial_id": space_id,
                "spatial_type": "AGS",
                "variable_id": val_col, # Keeping column name as variable ID
                "value": row.get(val_col),
                "source_original": source_type,
                "raw_region": raw_space
            })
            
        return cdm_rows

    def _lookup_ags(self, name: str) -> str:
        name_lower = name.lower().strip()
        
        # Direct Match
        if name_lower in self.name_to_ags:
            return self.name_to_ags[name_lower]
            
        # Check if input IS likely an AGS (digits)
        if name.isdigit() and (len(name) == 2 or len(name) == 5 or len(name) == 8):
            return name
            
        # Fuzzy Match
        matches = difflib.get_close_matches(name_lower, self.name_to_ags.keys(), n=1, cutoff=0.8)
        if matches:
            return self.name_to_ags[matches[0]]
            
        return f"UNMAPPED:{name}"
