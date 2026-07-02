import json
import faiss
import numpy as np
import os
import torch
from sentence_transformers import SentenceTransformer

# CONFIG
DATA_FILE = "destatis-rag/scripts/bund_dev_apis.json"
INDEX_PATH = "/home/ubuntu/politics-bert_old/scripts/apis.faiss"
MAPPING_PATH = "/home/ubuntu/politics-bert_old/scripts/apis_metadata.json"
MODEL_NAME = 'intfloat/multilingual-e5-large'

def main():
    print("Loading data...")
    with open(DATA_FILE, 'r', encoding='utf-8') as f:
        apis = json.load(f)

    chunks = []
    metadata = []
    
    for i, api in enumerate(apis):
        # Create a searchable chunk
        # E5 requires "passage: "
        text = f"passage: API: {api['title']}. Beschreibung: {api['description']}"
        chunks.append(text)
        
        metadata.append({
            "code": f"API-{i}", # Artificial Code
            "title": api['title'],
            "description": api['description'],
            "link": api['documentation_link'],
            "type": "external_api"
        })

    print(f"Encoding {len(chunks)} APIs...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL_NAME, device=device)
    
    embeddings = model.encode(chunks, convert_to_numpy=True, show_progress_bar=True)
    embeddings = embeddings.astype('float32')
    
    # FAISS
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    
    print("Saving index...")
    faiss.write_index(index, INDEX_PATH)
    
    with open(MAPPING_PATH, 'w', encoding='utf-8') as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)
        
    print("Done.")

if __name__ == "__main__":
    main()
