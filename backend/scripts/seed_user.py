import argparse
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from backend.app.auth import get_password_hash
from backend.app.config import DB_DSN


async def seed_user(username: str, full_name: str, password: str, role: str) -> None:
    engine = create_async_engine(DB_DSN, echo=False, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.execute(
            text(
                """
                INSERT INTO groundwater.app_users (username, full_name, password_hash, role)
                VALUES (:username, :full_name, :password_hash, :role)
                ON CONFLICT (username)
                DO UPDATE SET
                    full_name = EXCLUDED.full_name,
                    password_hash = EXCLUDED.password_hash,
                    role = EXCLUDED.role;
                """
            ),
            {
                "username": username,
                "full_name": full_name,
                "password_hash": get_password_hash(password),
                "role": role,
            },
        )
    await engine.dispose()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed or update app user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--role", default="admin", choices=["viewer", "engineer", "admin"])
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(seed_user(args.username, args.full_name, args.password, args.role))
    print(f"User '{args.username}' upserted with role '{args.role}'.")
