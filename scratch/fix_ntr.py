import pandas as pd
import json

def fix_districts():
    path = 'frontend/public/data/final_dataset.json'
    df = pd.read_json(path)
    
    ntr_patterns = [
        'AKONDURU', 'CHANDARLAPADU', 'GKONDURU', 'GAMPALAGUDEM', 
        'JAGGAYYAPETA', 'KANCHIKACHERLA', 'IBRAHIMPATNAM', 'TIRUVURU', 
        'MYLAVARAM', 'NANDIGAMA', 'PENUGANCHIPROLU', 'VISSANNAPETA', 
        'VATSAVAI', 'VEERULLAPADU', 'VIJAYAWADA', 'REDDIGUDEM'
    ]
    
    def is_ntr(mandal):
        m = str(mandal).upper().replace(' ', '').replace('.', '')
        return any(p in m for p in ntr_patterns)

    df.loc[df['Mandal'].apply(is_ntr), 'District'] = 'NTR'
    
    # Save back
    df.to_json(path, orient='records', indent=2)
    print("New District Counts:")
    print(df['District'].value_counts())
    
    # Verify sensor distribution
    valid_sensors = df[df['GW_Level'] > 0]
    print("\nSensor Distribution:")
    print(valid_sensors['District'].value_counts())

if __name__ == "__main__":
    fix_districts()
