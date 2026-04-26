@echo off
setlocal

where psql >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo FAILED: PostgreSQL client tools are not available on PATH.
    echo Install PostgreSQL or add its bin folder to PATH, then retry.
    echo Expected commands: psql, createdb, dropdb
    pause
    exit /b 1
)

REM Drop DB if exists (backup first!)
echo Dropping existing groundwater DB if present...
dropdb -U postgres -h localhost groundwater --if-exists -f

REM Create fresh DB
echo Creating fresh groundwater database...
createdb -U postgres -h localhost groundwater

if %ERRORLEVEL% neq 0 (
    echo FAILED to create database. Check:
    echo - PostgreSQL running on localhost:5432
    echo - User: postgres with password access
    echo - psql in PATH
    pause
    exit /b %ERRORLEVEL%
)

echo Installing PostGIS extension...
psql -U postgres -h localhost -d groundwater -c "CREATE EXTENSION IF NOT EXISTS postgis;"

echo Running Phase 1: Core spatial tables...
psql -U postgres -h localhost -d groundwater -f phase1_postgis.sql

echo Running Phase 2: ML features...
psql -U postgres -h localhost -d groundwater -f phase2_feature_store.sql

echo Running Phase 3: API tables...
psql -U postgres -h localhost -d groundwater -f phase3_api_support.sql

echo Running Phase 4: Users + advisories...
psql -U postgres -h localhost -d groundwater -f phase4_security_ingestion.sql

if %ERRORLEVEL% neq 0 (
    echo FAILED while applying SQL setup files.
    echo Review the error output above, then rerun after fixing the issue.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo ========================================
echo          SETUP COMPLETE!                
echo ========================================
echo.
echo 1. Verify schema:
echo    psql -U postgres -d groundwater -c "\dt groundwater.*"
echo.
echo 2. Test backend:
echo    cd ..\backend
echo    uvicorn app.main:app --reload --port 8000
echo    curl http://localhost:8000/health  ^(should return {"status":"ok"}^)
echo.
echo 3. Frontend dev server:
echo    cd ..\frontend
echo    npm install
echo    npm run dev  ^(proxy to /api works^)
echo.
pause

