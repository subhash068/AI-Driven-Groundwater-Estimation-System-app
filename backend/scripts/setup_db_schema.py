import asyncio
import os
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

# Load environment variables
load_dotenv(Path(__file__).resolve().parents[2] / "backend" / ".env")

# Configuration
DB_DSN = os.getenv("DB_DSN")
DB_DIR = Path(__file__).resolve().parents[2] / "database"

engine = create_async_engine(DB_DSN)

async def setup_schema():
    print(f"Connecting to database to set up schema...")
    
    # SQL files to execute in order
    sql_files = [
        "phase1_postgis.sql",
        "phase2_feature_store.sql",
        "phase3_api_support.sql",
        "phase4_security_ingestion.sql",
        "phase5_bootstrap.sql"
    ]
    
    async with engine.begin() as conn:
        # Create schema if not exists (though usually handled in scripts)
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS groundwater;"))
        
        for file_name in sql_files:
            file_path = DB_DIR / file_name
            if not file_path.exists():
                print(f"Warning: {file_name} not found in {DB_DIR}")
                continue
                
            print(f"Executing {file_name}...")
            content = file_path.read_text(encoding="utf-8")
            
            # Split by semicolon to execute statements individually if needed, 
            # but usually for PostgreSQL, we can execute the whole block if it's well-formed.
            # However, some scripts might have multiple statements that sqlalchemy doesn't like in one text() call.
            # We'll try executing the whole block first.
            try:
                # Filter out lines starting with \ (psql commands like \connect)
                clean_lines = [line for line in content.splitlines() if not line.strip().startswith("\\")]
                clean_content = "\n".join(clean_lines)
                
                if clean_content.strip():
                    await conn.execute(text(clean_content))
                    print(f"Successfully applied {file_name}")
            except Exception as e:
                print(f"Error applying {file_name}: {e}")
                
    print("Database schema setup complete!")

if __name__ == "__main__":
    asyncio.run(setup_schema())
