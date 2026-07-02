import requests
import json
import os
import time
from tqdm import tqdm

BASE_URL = 'https://www-genesis.destatis.de/genesisWS/rest/2020/'
# NOTE: User should update this token if it expires.
TOKEN = os.environ.get("DESTATIS_GENESIS_TOKEN", "")  # set via environment, do not hardcode
SAVE_DIR = "genesis_metadata"
HEADERS = {'Content-Type': 'application/x-www-form-urlencoded', 'username': TOKEN, 'password': ""}

def get_themes(parent_code=None):
    """
    Traverses the 'Themen' tree. 
    If parent_code is None, gets root themes.
    Returns list of leaf nodes (Tabellen) or drill-down nodes.
    """
    # This logic is simplified. Real structure: Themes -> Statistics -> Tables
    # But often Themes -> Subthemes -> ... -> Statistics
    pass

# Better approach provided by genesis: find/find/tables with proper query.
# But 'catalogue/tables' with selection='*' should return ALL tables if paginated.
# The previous script used 'catalogue/statistics' then 'catalogue/tables'.
# Let's try the recursive 'catalogue/nodes' or just iterate statistics more carefully.

# Plan B: Iterate 'catalogue/tables' for ALL statistics.
# The previous script failed because it might have missed some statistics or pagination.

def get_all_statistics():
    print("Fetching all statistics...")
    # Get all statistics code.
    try:
        r = requests.post(f"{BASE_URL}catalogue/statistics", 
                          data={'selection': '*', 'language': 'de', 'pagelength': 20000}, # Increase page length
                          headers=HEADERS, timeout=60)
        data = r.json()
        if 'List' in data:
            return [s['Code'] for s in data['List']]
        else:
            print("No List in response:", data.keys())
            return []
    except Exception as e:
        print(f"Error fetching stats: {e}")
        return []

def get_tables_for_statistic(stat_code):
    try:
        r = requests.post(f"{BASE_URL}catalogue/tables", 
                          data={'selection': f'{stat_code}*', 'language': 'de', 'pagelength': 500},
                          headers=HEADERS, timeout=30)
        data = r.json()
        if 'List' in data:
            return data['List']
    except:
        pass
    return []

def download_metadata(code):
    path = os.path.join(SAVE_DIR, f"{code}.json")
    if os.path.exists(path): return # Skip existing
    
    try:
        r = requests.post(f"{BASE_URL}metadata/table", 
                         data={'name': code, 'language': 'de'},
                         headers=HEADERS, timeout=30)
        if r.status_code == 200:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(r.json(), f, ensure_ascii=False)
    except: pass

def main():
    if not os.path.exists(SAVE_DIR):
        os.makedirs(SAVE_DIR)
        
    print("Starting Comprehensive Crawl...")
    stats = get_all_statistics()
    print(f"Found {len(stats)} Statistics groups.")
    
    all_table_codes = set()
    
    # 1. Collect all Table Codes
    print("Collecting Table Codes...")
    for stat in tqdm(stats):
        tables = get_tables_for_statistic(stat)
        for t in tables:
            all_table_codes.add(t['Code'])
            
    print(f"Total Unique Tables Found: {len(all_table_codes)}")
    
    # 2. Download Metadata
    print("Downloading Metadata...")
    for code in tqdm(list(all_table_codes)):
        download_metadata(code)

if __name__ == "__main__":
    main()
