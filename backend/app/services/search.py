import faiss
import json
import numpy as np
import torch
import os
from sentence_transformers import SentenceTransformer
from app.services.soep_search import SOEPSearchService
import difflib

class SearchService:
    def __init__(self, index_path: str, mapping_path: str, metadata_dir: str, api_data_path: str | None = None):
        self.index_path = index_path
        self.mapping_path = mapping_path
        self.metadata_dir = metadata_dir
        
        # Paths to other data sources
        self.api_data_path = api_data_path or os.getenv("DESTATIS_RAG_API_DATA_PATH", "/app/data/curated_apis.json")
        
        # State
        self.model = None
        self.index = None # Destatis FAISS
        self.mapping = None # Destatis Metadata
        self.api_list = [] # List of API Dicts
        self.soep_service = SOEPSearchService() # Reuse existing service
        
        self.model_name = os.getenv("DESTATIS_RAG_EMBEDDING_MODEL", 'intfloat/multilingual-e5-large')
        requested_device = os.getenv("DESTATIS_RAG_DEVICE", "cuda")
        self.device = requested_device if requested_device == "cpu" or torch.cuda.is_available() else "cpu"

    def load_resources(self):
        # 1. Load Destatis Vector Model/Index
        if self.model is None:
            print(f"Loading SentenceTransformer on {self.device}...")
            # Ideally load model only if needed for vector search
            try:
                self.model = SentenceTransformer(self.model_name, device=self.device)
            except Exception as e:
                print(f"Model load failed: {e}")
        
        if self.index is None and os.path.exists(self.index_path):
            print(f"Loading FAISS index from {self.index_path}...")
            self.index = faiss.read_index(self.index_path)
            
        if self.mapping is None and os.path.exists(self.mapping_path):
            print(f"Loading mapping from {self.mapping_path}...")
            try:
                with open(self.mapping_path, 'r', encoding='utf-8') as f:
                    self.mapping = json.load(f)
            except:
                self.mapping = []

        # 2. Load APIs (Simple JSON List)
        if not self.api_list and os.path.exists(self.api_data_path):
            try:
                with open(self.api_data_path, 'r') as f:
                    data = json.load(f)
                    # Handle if it's a dict wrapper or list
                    if isinstance(data, list):
                        self.api_list = data
                    elif isinstance(data, dict) and "apis" in data:
                        self.api_list = data["apis"]
                    print(f"Loaded {len(self.api_list)} APIs.")
            except Exception as e:
                print(f"Error loading APIs: {e}")

    def search(self, query: str, k: int = 5):
        self.load_resources()
        results = []
        
        # --- Source A: Destatis (Vector Search) ---
        if self.model and self.index and self.mapping:
            try:
                query_emb = self.model.encode([f"query: {query}"], convert_to_numpy=True)
                dists, idxs = self.index.search(query_emb.astype('float32'), k)
                for i in range(k):
                    idx = idxs[0][i]
                    if idx < 0 or idx >= len(self.mapping): continue
                    item = self.mapping[idx]
                    results.append({
                        "id": item['code'],
                        "title": item['title'],
                        "source": "Destatis",
                        "type": "table",
                        "description": "Federal Statistical Office Table",
                        "score": float(dists[0][i]) # Lower is better? Depends on metric. InnerProduct is higher better. L2 is lower better. Assuming L2 based on prev code.
                    })
            except Exception as e:
                print(f"Vector search failed: {e}")
                
        # --- Source B: APIs (Keyword/Fuzzy Search) ---
        # Very simple ranking: title match
        q_lower = query.lower()
        for api in self.api_list:
            score = 0
            title = api.get('title', '').lower()
            desc = api.get('description', '').lower()
            
            if q_lower in title: score += 10
            if q_lower in desc: score += 5
            
            if score > 0:
                results.append({
                    "id": f"API-{api.get('id', 'unknown')}", # Fake ID if needed
                    "title": api.get('title'),
                    "source": "External API",
                    "type": "api",
                    "description": api.get('description', 'API Endpoint'),
                    "score": 0.5 # Normalizing score to fit with others is hard, just distinctive
                })

        # --- Source C: SOEP (Metadata Search) ---
        # Use existing SOEP search service
        soep_hits = self.soep_service.search(query)
        for hit in soep_hits[:3]: # Top 3 SOEP matches
            results.append({
                "id": hit['code'],
                "title": f"{hit['label']} ({hit['code']})",
                "source": "SOEP v40",
                "type": "microdata",
                "description": f"Variable in {hit['dataset']} dataset. Category: {hit['category']}",
                "score": 0.1 # Placeholder
            })
            
        # Sort or Mix?
        # For now, return mixed list. 
        # Ideally weinterleave them or sort by type priority.
        # Let's prioritize: Destatis (Massive) -> APIs -> SOEP
        
        return results

    def get_api_context(self, api_code: str):
        # ... (Implementation needed if generating code for APIs)
        return {"title": "API", "url": "..."} 

    def get_metadata_context(self, table_code: str):
        # ... (Keep existing logic)
        return {"title": "Metadata", "variables": []}
