from typing import Dict, Any

class SQLAgentService:
    def __init__(self, data_service):
        self.data_service = data_service
        # In the future: self.llm_client = ...
    
    async def generate_sql(self, user_query: str, context: Dict[str, Any]) -> str:
        """
        Generates DuckDB SQL based on the user query and table metadata.
        """
        table_code = context['code']
        csv_path = os.path.join(self.data_service.data_dir, f"{table_code}.csv")
        
        # TODO: integrate Real LLM here.
        # For now, we'll return a stub or try to implement a basic heuristic if asked.
        # But the plan is to verify connections first.
        
        # Construct the System Prompt
        prompt = f"""
You are a Data Scientist Expert.
User Question: "{user_query}"
Table Metadata: {context}
Local CSV Path: "{csv_path}"

Write a valid DuckDB SQL query to answer the question. 
Return ONLY the SQL.
        """
        
        print("--- LLM PROMPT (SIMULATED) ---")
        print(prompt)
        print("------------------------------")

        # MOCK RETURN for testing without API key yet
        return f"SELECT * FROM read_csv_auto('{csv_path}') LIMIT 10;"

import os
