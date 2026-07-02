import pandas as pd

file_path = '/home/ubuntu/politics-bert_old/scripts/Geospatial_Data_Sources.xlsx'
try:
    df = pd.read_excel(file_path)
    print("Columns:", df.columns.tolist())
    print("\nFirst 5 rows:")
    print(df.head().to_string())
except Exception as e:
    print(e)
