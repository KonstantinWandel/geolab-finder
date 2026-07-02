import duckdb
import os
import pandas as pd

class DataService:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.conn = duckdb.connect(database=':memory:') # Use in-memory DuckDB for speed, pointing to files
        
    def execute_query(self, sql: str) -> pd.DataFrame:
        """
        Executes a SQL query. 
        IMPORTANT: The SQL query must reference the CSV files properly.
        Since we might want to abstract the file path, we can pre-register the CSVs or rely on the LLM to get the full path.
        For safety/ease, we can enforce that the table name in SQL is just the code, and we swap it here.
        """
        
        # Security/Sanity Check: Ensure we don't allow arbitrary file reading outside cwd if possible.
        # But for a local tool, less critical.
        
        print(f"Executing SQL: {sql}")
        
        # We need to ensure the query works. 
        # Strategy: The LLM will likely write "SELECT * FROM '11111-0002.csv'".
        # We need to make sure the working directory for DuckDB is self.data_dir OR we replace the table name.
        
        # Let's try to set the CWD for the DuckDB connection context if possible, or just replace filenames.
        # Simpler: Re-write the SQL to use absolute paths if they are just filenames.
        
        processed_sql = sql
        
        # This is a naive replacement, can be improved.
        # Checks if the SQL contains a table name that looks like a simplified code and maps it to the absolute path.
        # But actually, the safest bet is to rely on the agent to output the correct filename 
        # OR we inject a view.
        
        # Let's try to register the table first if we can parse it?
        # No, easier: logic is "Agent, please query the file at '/absolute/path/to/X.csv'".
        # But that's token heavy.
        
        # Better: Agent queries "t_12345" and we create a view `CREATE VIEW t_12345 AS SELECT * FROM 'path/to/12345.csv'`
        # For now, let's assume the Agent writes valid DuckDB SQL with the full path if we provide it in the prompt,
        # OR the agent writes 'table_code' and we modify it.
        
        # Current decision: The Agent will be told: "The table is located at '{self.data_dir}/{table_code}.csv'. Use `read_csv_auto(...)` or just string path."
        
        try:
            return self.conn.execute(processed_sql).df()
        except Exception as e:
            print(f"DuckDB Error: {e}")
            raise e
