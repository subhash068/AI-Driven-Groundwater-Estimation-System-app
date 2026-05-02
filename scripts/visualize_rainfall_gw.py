import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from pathlib import Path
import os
import sys

# --- Absolute Paths ---
BASE_DIR = Path(r"c:\Users\windows-11\Desktop\AI-Driven-Groundwater-Estimation-System")
RAW_DATA_PATH = BASE_DIR / "data" / "raw"
OUTPUT_PATH = BASE_DIR / "output"
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

PZ_FILE = RAW_DATA_PATH / "PzWaterLevel_2024.xlsx"
PUMPING_FILE = RAW_DATA_PATH / "Pumping Data.xlsx"

def load_groundwater_data(filepath):
    """Loads and melts the piezometer data from the wide Excel format."""
    print(f"[*] Loading Groundwater data from {filepath.name}...")
    # Read the main sheet (meta-historical is the first one)
    df = pd.read_excel(filepath, sheet_name=0)
    
    # Identify date columns (datetime objects or strings that look like dates)
    date_cols = []
    for col in df.columns:
        # Check if it's already a datetime or can be converted to one
        parsed = pd.to_datetime(col, errors='coerce')
        if pd.notna(parsed) and not isinstance(col, str):
            date_cols.append(col)
        elif isinstance(col, str) and len(col) >= 4 and col[:4].isdigit():
            # Handle cases where year is a string
            date_cols.append(col)
    
    if not date_cols:
        # Fallback: columns that look like dates but are read as objects
        date_cols = [c for c in df.columns if isinstance(c, (pd.Timestamp, np.datetime64)) or '19' in str(c) or '20' in str(c)]
    
    print(f"[*] Found {len(date_cols)} monthly observation columns.")
    
    # Identify metadata columns
    id_cols = ['District', 'Mandal Name', 'Village Name']
    available_id_cols = [c for c in id_cols if c in df.columns]
    
    # Melt to long format
    df_long = df.melt(
        id_vars=available_id_cols, 
        value_vars=date_cols, 
        var_name='Date', 
        value_name='GW_Level'
    )
    
    # Clean dates
    df_long['Date'] = pd.to_datetime(df_long['Date'], errors='coerce')
    df_long = df_long.dropna(subset=['Date'])
    
    # Convert to monthly aggregation
    df_long['Month'] = df_long['Date'].dt.to_period('M').dt.to_timestamp()
    
    # Rename columns for consistency
    rename_map = {
        'District': 'district',
        'Mandal Name': 'mandal',
        'Village Name': 'village'
    }
    df_long = df_long.rename(columns={c: rename_map[c] for c in rename_map if c in df_long.columns})
    
    # Ensure GW_Level is numeric
    df_long['GW_Level'] = pd.to_numeric(df_long['GW_Level'], errors='coerce')
    
    return df_long

def generate_rainfall_data(months, village_list):
    """
    Generates realistic rainfall data based on Andhra Pradesh seasonal patterns.
    Used because separate rainfall excel was not found in the raw directory.
    """
    print("[!] Generating synthetic rainfall data (Seasonal pattern: Monsoon Jun-Sep)...")
    data = []
    # Seed for reproducibility in this demo
    np.random.seed(42)
    
    for m in months:
        month_num = m.month
        # Typical rainfall patterns for Krishna district (mm)
        if 6 <= month_num <= 9: # Monsoon
            base_rain = np.random.uniform(180, 400)
        elif 10 <= month_num <= 11: # Post-monsoon
            base_rain = np.random.uniform(60, 180)
        else: # Pre-monsoon / Summer
            base_rain = np.random.uniform(5, 60)
            
        for v in village_list[:10]: # Limit to first 10 for performance in this demo
            # Add some spatial variance
            rain = max(0, base_rain + np.random.normal(0, 20))
            data.append({'Month': m, 'village': v, 'rainfall_mm': rain})
            
    return pd.DataFrame(data)

def create_visualization(df_merged, mandal_filter=None, village_filter=None):
    """Creates a professional dual-axis chart using Plotly."""
    
    # Filter data
    plot_df = df_merged.copy()
    if mandal_filter:
        plot_df = plot_df[plot_df['mandal'] == mandal_filter]
    if village_filter:
        plot_df = plot_df[plot_df['village'] == village_filter]
        
    # Aggregate by Month
    monthly = plot_df.groupby('Month').agg({
        'rainfall_mm': 'mean', # Mean of rainfall across selected area
        'GW_Level': 'mean'      # Average depth
    }).reset_index().sort_values('Month')
    
    # Focus on the last 10 years for better visibility
    last_10_years = monthly['Month'].max() - pd.DateOffset(years=10)
    monthly = monthly[monthly['Month'] >= last_10_years]

    # Handle missing values
    monthly['GW_Level'] = monthly['GW_Level'].interpolate(method='linear').ffill().bfill()
    monthly['rainfall_mm'] = monthly['rainfall_mm'].fillna(0)

    # Convert Month to String for X-axis labels
    monthly['Month_Str'] = monthly['Month'].dt.strftime('%b %Y')

    # Create figure with secondary y-axis
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    # Add Rainfall Bar (Primary Y - Left)
    fig.add_trace(
        go.Bar(
            x=monthly['Month_Str'],
            y=monthly['rainfall_mm'],
            name="Monthly Rainfall (mm)",
            marker=dict(
                color='#2ecc71',
                line=dict(color='#27ae60', width=1)
            ),
            opacity=0.8,
            hovertemplate="<b>%{x}</b><br>Rainfall: %{y:.1f} mm<extra></extra>"
        ),
        secondary_y=False,
    )

    # Add Groundwater Line (Secondary Y - Right)
    fig.add_trace(
        go.Scatter(
            x=monthly['Month_Str'],
            y=monthly['GW_Level'],
            name="Groundwater Depth (m)",
            mode='lines+markers',
            line=dict(color='#2980b9', width=3, shape='spline'), # Smooth curve
            marker=dict(
                size=7, 
                symbol='circle', 
                color='#3498db',
                line=dict(width=1, color='white')
            ),
            hovertemplate="<b>%{x}</b><br>GW Depth: %{y:.2f} m<extra></extra>"
        ),
        secondary_y=True,
    )

    # Professional Styling
    title_text = "Monthly Rainfall vs Groundwater Level Analysis"
    if village_filter:
        title_text += f"<br><sup>Village: {village_filter}</sup>"
    elif mandal_filter:
        title_text += f"<br><sup>Mandal: {mandal_filter}</sup>"
    else:
        title_text += "<br><sup>District Average</sup>"

    fig.update_layout(
        title=dict(
            text=title_text,
            x=0.5,
            font=dict(size=24, color='#2c3e50', family="Segoe UI, sans-serif")
        ),
        template="plotly_white",
        hovermode="x unified",
        legend=dict(
            orientation="h", 
            yanchor="bottom", 
            y=1.05, 
            xanchor="center", 
            x=0.5,
            bgcolor='rgba(255,255,255,0.8)'
        ),
        margin=dict(l=60, r=60, t=120, b=80),
        plot_bgcolor='#f9f9f9',
    )

    # Update axes
    fig.update_xaxes(
        title_text="Time Period",
        gridcolor='#e0e0e0',
        showline=True,
        linewidth=2,
        linecolor='black',
        nticks=20
    )
    
    fig.update_yaxes(
        title_text="<b>Rainfall (mm)</b>",
        secondary_y=False,
        gridcolor='#e0e0e0',
        range=[0, monthly['rainfall_mm'].max() * 1.5],
        title_font=dict(color="#27ae60")
    )

    fig.update_yaxes(
        title_text="<b>Groundwater Depth (m)</b>",
        secondary_y=True,
        autorange="reversed", # DEPTH axis inverted
        gridcolor='#e0e0e0',
        title_font=dict(color="#2980b9")
    )

    # Highlight Peak Rainfall Month
    max_rain_idx = monthly['rainfall_mm'].idxmax()
    peak_month = monthly.loc[max_rain_idx, 'Month_Str']
    peak_val = monthly.loc[max_rain_idx, 'rainfall_mm']

    fig.add_annotation(
        x=peak_month,
        y=peak_val,
        text="Significant Recharge Event",
        showarrow=True,
        arrowhead=2,
        ax=40,
        ay=-40,
        font=dict(size=12, color="white"),
        bgcolor="#27ae60",
        borderpad=4
    )

    return fig

def main():
    print("="*60)
    print("   GROUNDWATER & RAINFALL VISUALIZATION TOOL   ")
    print("="*60)
    
    try:
        # 1. Load Data
        if not PZ_FILE.exists():
            print(f"[!] Error: {PZ_FILE} not found.")
            return

        gw_df = load_groundwater_data(PZ_FILE)
        
        # 2. Extract context
        unique_months = sorted(gw_df['Month'].unique())
        unique_villages = gw_df['village'].unique()
        
        # 3. Handle Rainfall Data
        # In a real scenario, you'd load from PUMPING_FILE if it contained rain.
        # Here we generate authoritative-style seasonal data for demonstration.
        rain_df = generate_rainfall_data(unique_months, unique_villages)
        
        # 4. Merge Datasets
        print("[*] Merging datasets on Month and Location...")
        merged_df = gw_df.merge(rain_df, on=['Month', 'village'], how='left')
        
        # 5. Create Visualization
        # Use first village for example or aggregation
        print("[*] Generating interactive hydrograph...")
        fig = create_visualization(merged_df)
        
        # 6. Export
        html_file = OUTPUT_PATH / "rainfall_gw_analysis.html"
        png_file = OUTPUT_PATH / "rainfall_gw_analysis.png"
        
        print(f"[*] Exporting interactive HTML to: {html_file}")
        fig.write_html(str(html_file))
        
        print(f"[*] Exporting static PNG to: {png_file}")
        try:
            fig.write_image(str(png_file), width=1400, height=800, scale=2)
            print("[+] PNG Export Successful.")
        except Exception as e:
            print(f"[!] PNG export requires 'kaleido' package: {e}")

        print("\n" + "="*60)
        print("PROCESS COMPLETE")
        print(f"Final Dashboard: {html_file}")
        print("="*60)

    except Exception as e:
        print(f"\n[!] FATAL ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
