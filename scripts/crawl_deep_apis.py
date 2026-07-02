import json
import requests
import yaml
import os
import faiss
import numpy as np
import torch
from sentence_transformers import SentenceTransformer
from tqdm import tqdm

# CONFIG
INPUT_FILE = "destatis-rag/scripts/curated_apis.json"
OUTPUT_INDEX = "/home/ubuntu/politics-bert_old/scripts/apis_detailed.faiss"
OUTPUT_MAPPING = "/home/ubuntu/politics-bert_old/scripts/apis_detailed_metadata.json"
MODEL_NAME = 'intfloat/multilingual-e5-large'

def get_repo_name(url):
    """
    Infers repo name from bundesapi.github.io link or github.com link.
    Example: https://bundesapi.github.io/abfallnavi-api/ -> abfallnavi-api
    """
    if "bundesapi.github.io" in url:
        return url.split("bundesapi.github.io/")[1].replace("/", "")
    elif "github.com/bundesAPI" in url:
        return url.split("github.com/bundesAPI/")[1].replace("/", "")
    return None

def fetch_openapi_spec(repo_name):
    # Try common locations
    base = f"https://raw.githubusercontent.com/bundesAPI/{repo_name}"
    branches = ["main", "master"]
    files = ["openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"]
    
    for branch in branches:
        for fname in files:
            url = f"{base}/{branch}/{fname}"
            try:
                r = requests.get(url, timeout=5)
                if r.status_code == 200:
                    try:
                        if fname.endswith('.json'):
                            return json.loads(r.text)
                        else:
                            return yaml.safe_load(r.text)
                    except:
                        continue
            except:
                continue
    return None

def extract_chunks_from_spec(title, spec):
    chunks = []
    
    # 1. Endpoints
    paths = spec.get('paths', {})
    for path, methods in paths.items():
        for method, details in methods.items():
            if method in ['get', 'post', 'put', 'delete']:
                summary = details.get('summary', '')
                desc = details.get('description', '')
                
                text = f"passage: API: {title}. Endpoint: {method.upper()} {path}. {summary} {desc}"
                chunks.append({
                    "text": text,
                    "meta": {
                        "code": f"API-EP-{title[:10]}",
                        "title": f"{title} - {path}",
                        "description": summary or desc,
                        "type": "api_endpoint",
                        "link": f"Endpoint: {method.upper()} {path}"
                    }
                })

    # 2. Schema Variables (The "descriptions of all variables")
    components = spec.get('components', {})
    schemas = components.get('schemas', {})
    
    for schema_name, schema_details in schemas.items():
        props = schema_details.get('properties', {})
        for prop_name, prop_details in props.items():
            prop_desc = prop_details.get('description', '')
            prop_type = prop_details.get('type', '')
            
            if prop_desc:
                text = f"passage: API: {title}. Object: {schema_name}. Variable: {prop_name} ({prop_type}). Description: {prop_desc}"
                chunks.append({
                    "text": text,
                    "meta": {
                        "code": f"API-VAR-{prop_name}",
                        "title": f"{title} - Variable: {prop_name}",
                        "description": f"In {schema_name}: {prop_desc}",
                        "type": "api_variable",
                        "link": f"Schema: {schema_name}"
                    }
                })
                
    return chunks

def main():
    with open(INPUT_FILE, 'r') as f:
        apis = json.load(f)
        
    all_chunks = []
    all_metadata = []
    
    print(f"Scanning {len(apis)} APIs for OpenAPI specs...")
    
    for api in tqdm(apis):
        title = api['title']
        link = api['documentation_link']
        
        repo = get_repo_name(link)
        if not repo:
            continue
            
        spec = fetch_openapi_spec(repo)
        if spec:
            chunks = extract_chunks_from_spec(title, spec)
            for c in chunks:
                all_chunks.append(c['text'])
                # Inherit link from parent if generic
                c['meta']['link'] = link 
                all_metadata.append(c['meta'])
        else:
            # Fallback for APIs without spec: just index the description
             text = f"passage: API: {title}. {api['description']}"
             all_chunks.append(text)
             all_metadata.append({
                 "code": "API-GENERIC",
                 "title": title,
                 "description": api['description'],
                 "type": "api_generic",
                 "link": link
             })

    print(f"Found {len(all_chunks)} granular items.")
    
    if not all_chunks:
        print("No chunks found. Exiting.")
        return

    print("Encoding...")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = SentenceTransformer(MODEL_NAME, device=device)
    embeddings = model.encode(all_chunks, convert_to_numpy=True, show_progress_bar=True)
    embeddings = embeddings.astype('float32')
    
    index = faiss.IndexFlatL2(embeddings.shape[1])
    index.add(embeddings)
    
    faiss.write_index(index, OUTPUT_INDEX)
    with open(OUTPUT_MAPPING, 'w') as f:
        json.dump(all_metadata, f, indent=2)
        
    print(f"Saved detailing index to {OUTPUT_INDEX}")

if __name__ == "__main__":
    main()
