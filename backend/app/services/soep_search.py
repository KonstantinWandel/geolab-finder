import json
import os
from typing import List, Dict

class SOEPSearchService:
    def __init__(self):
        self.metadata = self._load_metadata()

    def _load_metadata(self) -> List[Dict]:
        # Try PDF metadata first, then manual
        metadata_root = os.getenv("SOEP_SEARCH_METADATA_ROOT", "/app/data/soep_search")
        paths = [
            os.path.join(metadata_root, "soep_metadata_pdf.json"),
            os.path.join(metadata_root, "soep_metadata_manual.json"),
            "app/data/soep_metadata_pdf.json",
            "app/data/soep_metadata_manual.json",
        ]
        
        for path in paths:
            if os.path.exists(path):
                try:
                    with open(path, 'r') as f:
                        data = json.load(f)
                        print(f"Loaded {len(data)} SOEP variables from {path}")
                        return data
                except Exception as e:
                    print(f"Error loading {path}: {e}")
        
        return []

    def search(self, query: str) -> List[Dict]:
        """
        Simple text search over label, category, and code.
        """
        q = query.lower().strip()
        results = []
        
        for item in self.metadata:
            # Score logic: Exact code match > Label contains > Category contains
            score = 0
            if q == item['code'].lower():
                score = 100
            elif q in item['label'].lower():
                score = 50
            elif q in item['category'].lower():
                score = 20
            elif q in item['dataset'].lower():
                score = 10
            
            if score > 0:
                results.append({**item, "score": score})
                
        # Sort by score desc
        results.sort(key=lambda x: x['score'], reverse=True)
        return results

    def get_dataset_for_variable(self, variable_code: str) -> str:
        """
        Returns the dataset name (e.g. 'pl', 'hl') for a given code.
        Default to 'pl' if not found.
        """
        for item in self.metadata:
            if item['code'].lower() == variable_code.lower():
                return item['dataset']
        return "pl" # Default fallback
