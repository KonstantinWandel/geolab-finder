import pandas as pd
import os
import numpy as np
from app.services.soep_search import SOEPSearchService

try:
    import pyreadr
except ImportError:
    pyreadr = None

class SOEPAggregatorService:
    def __init__(self, data_path=None):
        if data_path is None:
            data_path = os.getenv("SOEP_RAW_DATA_PATH", "/app/data/soep_raw")
        self.data_path = data_path
        self.meta_service = SOEPSearchService()
        self.loaded_dfs = {} # Cache: {'pl': df, ...} (Careful with memory!)

    def available(self):
        return pyreadr is not None and os.path.exists(self.data_path)

    def _get_dataframe(self, dataset_name: str):
        """
        Lazy loads the requested dataset (pl, hl, pgen, etc)
        """
        if dataset_name in self.loaded_dfs:
            return self.loaded_dfs[dataset_name]
            
        file_path = os.path.join(self.data_path, f"{dataset_name}.rds")
        if not os.path.exists(file_path):
             # Try without .rds extension or different case?
             return None

        print(f"Loading SOEP dataset: {dataset_name} from {file_path}...")
        try:
            result = pyreadr.read_r(file_path)
            df = result[None]
            # Simple optimization: Convert column names to lower case
            df.columns = df.columns.astype(str).str.lower()
            self.loaded_dfs[dataset_name] = df
            return df
        except Exception as e:
            print(f"Error loading {dataset_name}: {e}")
            return None

    def aggregate_variable(self, variable_name: str, year: int) -> list:
        """
        Aggregates a specific variable from SOEP by Region (Bundesland) for a given year.
        Auto-detects which dataset to load based on metadata.
        """
        variable_name = variable_name.lower().strip()
        
        # 1. Determine Dataset
        dataset = self.meta_service.get_dataset_for_variable(variable_name)
        
        # 2. Load Data
        df = self._get_dataframe(dataset)
        if df is None:
            return [{"error": f"Could not load dataset '{dataset}' for variable {variable_name}"}]
            
        # 3. Check Variables
        if 'syear' not in df.columns:
             return [{"error": f"Dataset '{dataset}' has no 'syear' column. Cannot filter by year."}]
             
        # Filter Year
        df_year = df[df['syear'] == year]
        if df_year.empty:
             return [{"error": f"No data found for year {year} in {dataset}"}]

        if variable_name not in df_year.columns:
            return [{"error": f"Variable {variable_name} not found in {dataset} (Columns: {list(df.columns)[:5]}...)"}]

        # 4. Join with Region
        # Standard SOEP: 'bula' is usually in PL/HL.
        # If not, we might need to join with 'regionl.rds' (TODO: Implement join if needed)
        # For now, check if 'bula' exists
        region_col = 'bula'
        if region_col not in df_year.columns:
            # Fallback: Check if we can merge logic?
            # For this MVP, we return error if region missing
            return [{"error": f"Region column 'bula' not found in {dataset}. Merging not yet implemented."}]
        
        # 5. Aggregate
        try:
            # Ensure numeric
            df_year[variable_name] = pd.to_numeric(df_year[variable_name], errors='coerce')
            
            # Simple Mean Aggregation
            agg = df_year.groupby(region_col)[variable_name].agg(['mean', 'count']).reset_index()
            
            cdm_rows = []
            for _, row in agg.iterrows():
                # Map Bula ID to Standard Name (1-16)
                bula_id = int(row[region_col])
                if bula_id not in SOEP_BULA_MAP:
                    continue # Skip invalid/missing (-1)

                cdm_rows.append({
                    "temporal_id": str(year),
                    "spatial_id": f"BL-{bula_id:02d}", # Standardize ID
                    "spatial_name": SOEP_BULA_MAP[bula_id],
                    "spatial_type": "Bundesland",
                    "variable_id": variable_name,
                    "value": row['mean'],
                    "source_original": f"SOEP_{dataset}",
                    "sample_size": int(row['count'])
                })
                
            return cdm_rows

        except Exception as e:
            return [{"error": f"Aggregation computation failed: {str(e)}"}]

# Mapping for SOEP Bula to Text
SOEP_BULA_MAP = {
    1: "Schleswig-Holstein", 2: "Hamburg", 3: "Niedersachsen", 4: "Bremen",
    5: "Nordrhein-Westfalen", 6: "Hessen", 7: "Rheinland-Pfalz", 8: "Baden-Württemberg",
    9: "Bayern", 10: "Saarland", 11: "Berlin", 12: "Brandenburg",
    13: "Mecklenburg-Vorpommern", 14: "Sachsen", 15: "Sachsen-Anhalt", 16: "Thüringen"
}
