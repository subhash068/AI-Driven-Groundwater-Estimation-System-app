# Cache flushed for NTR district reconciliation at 2026-05-03T03:22:00
from datetime import date
from pathlib import Path

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordRequestForm
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from sqlalchemy.ext.asyncio import AsyncSession

from .auth import authenticate_user, create_access_token, get_current_user, require_roles
from .cache import cache_get_json, cache_set_json
from .config import CORS_ALLOW_ORIGIN_REGEX, CORS_ALLOW_ORIGINS, REPORTS_DIR
from .db import get_db
from .schemas import (
    AnomalyAlert,
    AnomalyAlertResponse,
    FarmerAdvisory,
    FarmerAdvisoryCreate,
    FarmerAdvisoryResponse,
    HealthResponse,
    RechargeRecommendationResponse,
    TokenResponse,
    UserProfile,
    VillageEstimateUpsert,
    VillageForecastResponse,
    VillageStatusResponse,
)
from .services import (
    fetch_anomaly_alerts,
    fetch_farmer_advisories,
    fetch_map_data,
    fetch_model_upgrade_summary,
    fetch_predict,
    fetch_predict_live,
    fetch_recharge_recommendations,
    fetch_recharge_zones,
    fetch_village_forecast_lstm,
    fetch_village_status,
    insert_farmer_advisory,
    locate_village_by_point,
    upsert_village_estimate,
)
from .services.prediction_service import gnn_service
from .utils.key import build_location_key
from .api import v2



app = FastAPI(title="Groundwater Insight API", version="1.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000)

app.include_router(v2.router)
@app.post("/auth/token", response_model=TokenResponse)
async def login_for_access_token(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await authenticate_user(db, form_data.username, form_data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    token = create_access_token(subject=user["username"], role=user["role"])
    return TokenResponse(access_token=token)


@app.get("/auth/me", response_model=UserProfile)
async def auth_me(current_user: dict = Depends(get_current_user)) -> UserProfile:
    return UserProfile(**current_user)


@app.get("/.well-known/openid-configuration", response_model=dict)
async def openid_configuration() -> dict:
    return {
        "issuer": "groundwater-api",
        "token_endpoint": "/auth/token",
        "scopes_supported": ["viewer", "engineer", "admin"],
        "token_endpoint_auth_methods_supported": ["client_secret_post"],
    }


@app.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/get-village-status/{village_id}", response_model=VillageStatusResponse)
async def get_village_status(
    village_id: int,
    db: AsyncSession = Depends(get_db),
) -> VillageStatusResponse:
    cache_key = f"village_status:{village_id}"
    cached = await cache_get_json(cache_key)
    if cached:
        return VillageStatusResponse(**cached)

    payload = await fetch_village_status(db, village_id)
    if payload["current_depth"] is None and not payload["forecast_3_month"]:
        payload = {
            "village_id": village_id,
            "current_depth": None,
            "forecast_3_month": [],
            "anomaly_flags": [],
            "confidence_score": 0.0,
        }

    await cache_set_json(cache_key, payload, ttl_seconds=300)
    return VillageStatusResponse(**payload)


@app.get("/village/{village_id}/forecast", response_model=VillageForecastResponse)
async def village_forecast(
    village_id: int,
    db: AsyncSession = Depends(get_db),
) -> VillageForecastResponse:
    cache_key = f"village_lstm_forecast:{village_id}"
    cached = await cache_get_json(cache_key)
    if cached:
        return VillageForecastResponse(**cached)

    payload = await fetch_village_forecast_lstm(db, village_id)
    await cache_set_json(cache_key, payload, ttl_seconds=900)
    return VillageForecastResponse(**payload)


@app.get("/recharge-recommendations", response_model=RechargeRecommendationResponse)
async def recharge_recommendations(
    db: AsyncSession = Depends(get_db),
) -> RechargeRecommendationResponse:
    cache_key = "recharge_recommendations"
    cached = await cache_get_json(cache_key)
    if cached:
        return RechargeRecommendationResponse(**cached)

    payload = await fetch_recharge_recommendations(db)
    await cache_set_json(cache_key, payload, ttl_seconds=900)
    return RechargeRecommendationResponse(**payload)


@app.get("/planning/recharge-zones", response_model=dict)
async def planning_recharge_zones(
    minimum_permeability: float = Query(default=0.6, ge=0.0, le=1.0),
    minimum_depletion: float = Query(default=0.7, ge=0.0, le=1.0),
    output_format: str = Query(default="geojson", pattern="^(geojson|json)$"),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> dict:
    payload = await fetch_recharge_zones(
        db,
        minimum_permeability=minimum_permeability,
        minimum_depletion=minimum_depletion,
    )
    if output_format == "json":
        return {"items": payload.get("features", [])}
    return payload


@app.get("/alerts/anomalies", response_model=AnomalyAlertResponse | dict)
async def alerts_anomalies(
    limit: int = Query(default=500, ge=1, le=5000),
    output_format: str = Query(default="json", pattern="^(geojson|json)$"),
    db: AsyncSession = Depends(get_db),
) -> AnomalyAlertResponse | dict:
    payload = await fetch_anomaly_alerts(db, limit=limit, output_format=output_format)
    if output_format == "geojson":
        return payload
    return AnomalyAlertResponse(alerts=[AnomalyAlert(**row) for row in payload])


@app.get("/village/locate", response_model=dict)
async def village_locate(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await locate_village_by_point(db, lat=lat, lon=lon)
    if not row:
        raise HTTPException(status_code=404, detail="No nearby village found")
    return row


@app.get("/farmer-advisories", response_model=FarmerAdvisoryResponse)
async def farmer_advisories(
    village_id: int | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(get_current_user),
) -> FarmerAdvisoryResponse:
    advisories = await fetch_farmer_advisories(db, village_id=village_id, limit=limit)
    return FarmerAdvisoryResponse(advisories=[FarmerAdvisory(**a) for a in advisories])


@app.post("/farmer-advisories", response_model=dict)
async def create_farmer_advisory(
    advisory: FarmerAdvisoryCreate,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles({"engineer", "admin"})),
) -> dict:
    await insert_farmer_advisory(
        db,
        village_id=advisory.village_id,
        advisory_level=advisory.advisory_level,
        advisory_text=advisory.advisory_text,
        language_code=advisory.language_code,
        channel=advisory.channel,
    )
    return {"status": "created"}


@app.post("/admin/village-estimates", response_model=dict)
async def create_or_update_village_estimate(
    estimate: VillageEstimateUpsert,
    db: AsyncSession = Depends(get_db),
    _: dict = Depends(require_roles({"engineer", "admin"})),
) -> dict:
    await upsert_village_estimate(
        db,
        village_id=estimate.village_id,
        estimated_groundwater_depth=estimate.estimated_groundwater_depth,
        confidence_score=estimate.confidence_score,
        anomaly_flag=estimate.anomaly_flag,
        draft_index=estimate.draft_index,
    )
    return {"status": "upserted"}


@app.get("/export/village-report/{village_id}")
async def export_village_report(
    village_id: int,
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    data = await fetch_village_status(db, village_id)
    if data["current_depth"] is None and not data["forecast_3_month"]:
        raise HTTPException(status_code=404, detail="Village report data not found")

    report_dir = Path(REPORTS_DIR)
    report_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = report_dir / f"village_{village_id}_report.pdf"

    c = canvas.Canvas(str(pdf_path), pagesize=A4)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, 800, f"Village Groundwater Report: {village_id}")
    c.setFont("Helvetica", 11)
    c.drawString(50, 770, f"Current Depth: {data['current_depth']}")
    c.drawString(50, 750, f"Confidence Score: {data['confidence_score']}")
    c.drawString(50, 730, f"Anomaly Flags: {', '.join(data['anomaly_flags']) or 'None'}")

    y = 700
    c.setFont("Helvetica-Bold", 11)
    c.drawString(50, y, "3-Month Forecast")
    c.setFont("Helvetica", 10)
    y -= 20
    for row in data["forecast_3_month"]:
        c.drawString(
            50,
            y,
            f"{row.get('forecast_date')}: {row.get('predicted_groundwater_depth')} "
            f"({row.get('predicted_lower')} - {row.get('predicted_upper')})",
        )
        y -= 16

    c.showPage()
    c.save()

    return FileResponse(
        path=pdf_path,
        media_type="application/pdf",
        filename=pdf_path.name,
    )


@app.get("/map-data", response_model=dict)
async def map_data(
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await fetch_map_data(db)


@app.get("/predict", response_model=dict)
async def predict(
    village_id: int = Query(..., ge=1),
    mode: str = Query(default="batch", pattern="^(batch|stored|live)$"),
    as_of: date | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if mode == "live":
        live_payload = await fetch_predict_live(db, village_id=village_id, as_of_date=as_of)
        if live_payload:
            return live_payload
        fallback = await fetch_predict(db, village_id=village_id)
        if fallback:
            fallback["mode"] = "batch_fallback"
            fallback["note"] = "Live mode unavailable, returned stored prediction."
            return fallback
        return {
            "village_id": village_id,
            "predicted_groundwater_level": None,
            "confidence_score": 0.0,
            "risk_level": "Unavailable",
            "draft_index": 0.0,
            "forecast_3_month": [],
            "forecast_yearly": [],
            "mode": "live",
            "note": f"No live prediction available for village {village_id}",
        }

    payload = await fetch_predict(db, village_id=village_id)
    if not payload:
        return {
            "village_id": village_id,
            "predicted_groundwater_level": None,
            "confidence_score": 0.0,
            "risk_level": "Unavailable",
            "draft_index": 0.0,
            "forecast_3_month": [],
            "forecast_yearly": [],
            "note": f"No prediction found for village {village_id}",
        }
    payload["mode"] = "batch"
    return payload

@app.get("/api/predictions/st-gnn/village/{village_id}", response_model=dict)
async def st_gnn_predict(
    village_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _ = db
    prediction_data = gnn_service.predict_for_village(village_id, features=[])
    return prediction_data


@app.get("/api/groundwater/all", response_model=dict)
async def groundwater_all(
    district: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    anomalies_only: bool = Query(default=False),
    recharge_only: bool = Query(default=False),
    refresh_cache: bool = Query(default=False),
) -> dict:
    if refresh_cache:
        gnn_service.clear_cache()
    return gnn_service.get_all(
        district=district,
        min_confidence=min_confidence,
        anomalies_only=anomalies_only,
        recharge_only=recharge_only,
    )

@app.get("/api/groundwater/anomalies", response_model=dict)
async def groundwater_anomalies(
    district: str | None = Query(default=None),
) -> dict:
    return gnn_service.get_anomalies(district=district)


@app.get("/api/groundwater/recharge", response_model=dict)
async def groundwater_recharge(
    district: str | None = Query(default=None),
) -> dict:
    return gnn_service.get_recharge_zones(district=district)


@app.get("/api/groundwater/{village_id}", response_model=dict)
async def groundwater_village(village_id: int) -> dict:
    payload = gnn_service.get_by_village(village_id=village_id)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Village {village_id} not found")
    return payload


@app.post("/api/groundwater/simulate", response_model=dict)
async def groundwater_simulate(
    payload: dict = Body(default={}),
) -> dict:
    rainfall_delta_pct = float(payload.get("rainfall_delta_pct", 0.0))
    extraction_delta_pct = float(payload.get("extraction_delta_pct", 0.0))
    return gnn_service.simulate(
        rainfall_delta_pct=rainfall_delta_pct,
        extraction_delta_pct=extraction_delta_pct,
    )


@app.post("/api/groundwater/village/{village_id}/simulate", response_model=dict)
async def groundwater_village_simulate(
    village_id: int,
    payload: dict = Body(default={}),
) -> dict:
    """
    Scientific-Grade Village Scenario Simulation.
    Params: {rainfall_reduction_pct, extraction_increase_pct, new_recharge_structure_count}
    """
    return gnn_service.simulate_scenario(village_id=village_id, params=payload)


@app.get("/analytics/model-upgrades", response_model=dict)
async def analytics_model_upgrades() -> dict:
    return await fetch_model_upgrade_summary()

