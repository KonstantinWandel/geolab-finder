import subprocess
import sys
import os
import uuid
import json

class ExecutionService:
    def __init__(self):
        # Determine python executable
        # Priority: Env Var -> Current Executable -> Fallback
        self.python_exe = sys.executable
        
        # Hardcoded for this environment if needed, but generic is better
        if "bert-politics-new" not in self.python_exe:
             # Try to find the conda env if we aren't running in it
             pass 

    def execute_script(self, script_content: str) -> dict:
        """
        Runs the python script content in a subprocess.
        Returns {'stdout': str, 'stderr': str, 'success': bool, 'data': any}
        """
        
        # Wrap the script to capture 'data' variable if it exists at the end?
        # Or implicitly expect the script to print JSON.
        # Let's wrap it to be safe: 
        # We append a footer that tries to print 'df.to_json()' or 'data' if they exist in locals.
        
        wrapped_script = script_content + """

# AUTO-APPENDED BY EXECUTION SERVICE
import json
import pandas as pd
import numpy as np

def default_serializer(obj):
    if isinstance(obj, (pd.Timestamp, np.integer, np.floating)):
        return str(obj)
    raise TypeError(f"Type {type(obj)} not serializable")

try:
    if 'df' in locals() and isinstance(df, pd.DataFrame):
        print("___DATA_START___")
        print(df.to_json(orient='records', date_format='iso'))
        print("___DATA_END___")
    elif 'data' in locals() and isinstance(data, (dict, list)):
        print("___DATA_START___")
        # Ensure we dump string, handle datetime/numpy
        print(json.dumps(data, default=default_serializer))
        print("___DATA_END___")
except Exception as e:
    print(f"Serialization Error: {e}")
"""
        
        filename = f"/tmp/script_{uuid.uuid4()}.py"
        try:
            with open(filename, 'w') as f:
                f.write(wrapped_script)
                
            # Run
            result = subprocess.run(
                [self.python_exe, filename],
                capture_output=True,
                text=True,
                timeout=60 # 60s timeout
            )
            
            output = result.stdout
            
            # Extract JSON data if present
            structured_data = None
            if "___DATA_START___" in output and "___DATA_END___" in output:
                try:
                    json_str = output.split("___DATA_START___")[1].split("___DATA_END___")[0].strip()
                    structured_data = json.loads(json_str)
                except:
                    pass
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "data": structured_data
            }
            
        except Exception as e:
            return {
                "success": False,
                "stdout": "",
                "stderr": str(e),
                "data": None
            }
        finally:
            if os.path.exists(filename):
                os.remove(filename)
