import pandas as pd
pz_path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\data\raw\PzWaterLevel_2024.xlsx'
df_pz = pd.read_excel(pz_path)
print("PZ Columns:", df_pz.columns.tolist()[:20])
print("PZ Head:\n", df_pz.head())
