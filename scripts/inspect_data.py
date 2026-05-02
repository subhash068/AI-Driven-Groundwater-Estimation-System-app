import pandas as pd
import os

pz_path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\data\raw\PzWaterLevel_2024.xlsx'
pumping_path = r'c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System\data\raw\Pumping Data.xlsx'

print("--- Piezometer Data ---")
df_pz = pd.read_excel(pz_path)
print(df_pz.info())
print(df_pz.head())

print("\n--- Pumping Data ---")
df_pumping = pd.read_excel(pumping_path)
print(df_pumping.info())
print(df_pumping.head())
