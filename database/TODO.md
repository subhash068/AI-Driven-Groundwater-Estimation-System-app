# Database Setup Checklist

This project includes `database/run_setup.bat` for local PostgreSQL setup.

## Prerequisites

- PostgreSQL is running on `localhost:5432`
- Database user `postgres` can authenticate
- PostgreSQL client tools are on `PATH`
  - Required commands: `psql`, `createdb`, `dropdb`
- PostGIS is available to the local PostgreSQL installation

## Current Local Defaults

- Database: `groundwater`
- User: `postgres`
- Host: `localhost`
- Port: `5432`

## Setup Steps

1. Open a terminal in the `database` directory.
2. Run:

```bat
run_setup.bat
```

3. Verify the schema:

```powershell
psql -U postgres -d groundwater -c "\dt groundwater.*"
```

4. Start the backend:

```powershell
cd ..\backend
uvicorn app.main:app --reload --port 8000
```

5. Check backend health:

```powershell
curl http://localhost:8000/health
```

6. Start the frontend:

```powershell
cd ..\frontend
npm install
npm run dev
```

## Notes

- The frontend dev server uses a Vite proxy to `/api`, so the backend should be reachable at `http://127.0.0.1:8000` or `http://localhost:8000`.
- Backend environment defaults are documented in `backend/.env.example`.
- If `run_setup.bat` fails immediately, the most common cause is missing PostgreSQL client tools on `PATH`.
