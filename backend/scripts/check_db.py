import asyncio
import os
from pathlib import Path
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / "backend" / ".env")
DB_DSN = os.getenv("DB_DSN")
engine = create_async_engine(DB_DSN)

async def check_schemas():
    async with engine.connect() as conn:
        res = await conn.execute(text("SELECT schema_name FROM information_schema.schemata;"))
        schemas = [r[0] for r in res]
        print(f"Existing schemas: {schemas}")
        
        if "groundwater" in schemas:
            print("Groundwater schema exists.")
            res = await conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema = 'groundwater';"))
            tables = [r[0] for r in res]
            print(f"Tables in groundwater: {tables}")
        else:
            print("Groundwater schema DOES NOT exist.")

if __name__ == "__main__":
    asyncio.run(check_schemas())
