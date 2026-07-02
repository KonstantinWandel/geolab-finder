from typing import Dict, Any

class DataFetchAgentService:
    def __init__(self):
        pass

    async def generate_download_code(self, user_query: str, context: Dict[str, Any], item_type: str) -> str:
        """
        Generates Python code to DOWNLOAD the data.
        """
        if item_type == "api":
            return self._generate_api_code(user_query, context)
        else:
            return self._generate_genesis_code(user_query, context)

    def _generate_api_code(self, query: str, context: Dict[str, Any]) -> str:
        api_title = context.get('title', 'API')
        link = context.get('link', '') 
        # Context from 'apis_detailed.faiss' has 'link' like 'Endpoint: GET /foo'
        
        endpoint_suffix = ""
        if "Endpoint: " in link:
            parts = link.split(" ")
            if len(parts) > 2:
                endpoint_suffix = parts[2] # /v1/foo
            
        return f"""
import requests
import pandas as pd

# Target: {api_title}
# Query: {query}
# Endpoint: {link}

# TODO: Replace with actual Base URL found in {context.get('link', 'docs')}
base_url = "https://api.bund.dev" # Placeholder
endpoint = "{endpoint_suffix}"
url = f"{{base_url}}{{endpoint}}"

# Inferred Parameters
params = {{
    "q": "{query}", 
    "format": "json"
}}

print(f"Fetching {{url}}...")
try:
    response = requests.get(url, params=params, timeout=10)
    response.raise_for_status()
    data = response.json()
    
    # Attempt to normalize
    # df = pd.json_normalize(data)
    # print(df.head())
    print("Data fetched successfully.")
    print(data)
except Exception as e:
    print(f"Error: {{e}}")
"""

    def _generate_genesis_code(self, query: str, context: Dict[str, Any]) -> str:
        code = context.get('code', 'UNKNOWN')
        return f"""
import requests
import pandas as pd
from io import StringIO

# Target: Destatis Table {code}
# query: {query}

GENESIS_URL = "https://www-genesis.destatis.de/genesisWS/rest/2020/data/table"
# User provided token/password
USERNAME = "PLEASE_UPDATE_USERNAME" # Token usually goes with a username, defaulting placeholder
PASSWORD = "PLEASE_UPDATE_TOKEN"

params = {{
    'username': USERNAME,
    'password': PASSWORD,
    'name': '{code}',
    'area': 'all',
    'compress': 'false',
    'language': 'de',
    'format': 'ffcsv'
}}

print(f"Downloading Destatis Table {code}...")
try:
    r = requests.post(GENESIS_URL, data=params)
    r.raise_for_status()
    
    # Parse FFCSV (Flat File CSV)
    csv_data = r.text
    df = pd.read_csv(StringIO(csv_data), sep=';')
    
    print(df.head())
    # Save for harmonization
    # df.to_csv('{code}_raw.csv', index=False)
except Exception as e:
    print(f"Error: {{e}}")
"""
