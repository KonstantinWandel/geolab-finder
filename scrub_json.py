import json
import os
import re

files_to_scrub = [
    "/home/ubuntu/destatis-rag/soep_metadata_output/soep_metadata_enriched.json",
    "/home/ubuntu/destatis-rag/soep_metadata_output/soep_metadata_registry.json"
]

def scrub_string(s):
    # Regex to catch typical server paths pointing to destatis-rag or .rds files
    # Also just replace instances of /home/ubuntu with something generic
    s = re.sub(r'/home/ubuntu/[a-zA-Z0-9_\-\./]+', '[LOCAL_SERVER_PATH]', s)
    return s

def scrub_json(data):
    if isinstance(data, dict):
        return {k: scrub_json(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [scrub_json(item) for item in data]
    elif isinstance(data, str):
        return scrub_string(data)
    else:
        return data

for file_path in files_to_scrub:
    if not os.path.exists(file_path):
        print(f"Skipping {file_path}, does not exist.")
        continue
    
    print(f"Scrubbing {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    scrubbed_data = scrub_json(data)
    
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(scrubbed_data, f, ensure_ascii=False, indent=2)
    print(f"Finished scrubbing {file_path}.")
