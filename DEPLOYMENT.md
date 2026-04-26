# Deployment Guide (Docker)

This project now includes a production-style Docker deployment stack in `infra/docker-compose.yml`.

## What Gets Deployed

- `postgres`: PostGIS database with initialization SQL scripts
- `redis`: cache layer
- `bootstrap`: one-shot deterministic file-to-DB bootstrap job
- `backend`: FastAPI app (`uvicorn`)
- `frontend`: Nginx serving built Vite app and proxying `/api/*` to backend

## 1) Prepare Environment

From the repository root:

```bash
cd infra
cp .env.example .env
```

Update `infra/.env` values for production, especially:
- `POSTGRES_PASSWORD`
- `JWT_SECRET_KEY`

## 2) Build and Start

```bash
cd infra
docker compose up -d --build
```

## 3) Verify Services

```bash
cd infra
docker compose ps
docker compose logs -f backend
```

Health checks:
- Frontend: `http://localhost/`
- Backend health: `http://localhost:8000/health`
- API via frontend proxy: `http://localhost/api/health`

Bootstrap verification:
```bash
cd infra
docker compose logs bootstrap
```

## 4) Seed Admin User (Optional but Recommended)

```bash
cd infra
docker compose exec backend python -m backend.scripts.seed_user --username admin --full-name "System Admin" --password "ChangeMe123!" --role admin
```

## 5) Stop / Restart

```bash
cd infra
docker compose down
docker compose up -d
```

To remove persistent DB data too:

```bash
cd infra
docker compose down -v
```

## Notes

- Database SQL scripts run automatically only on first DB initialization.
- Frontend API target is controlled at build time with `VITE_API_BASE` (default `/api`).
- If you deploy on a server, expose port `80` (or set `FRONTEND_PORT` in `.env`).
