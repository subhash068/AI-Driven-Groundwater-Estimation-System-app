from fastapi import APIRouter, Query, HTTPException, BackgroundTasks
from ..services.v2_service import v2_service
from ..schemas import V2PredictResponse, V2LulcTrendsResponse

router = APIRouter(prefix="/v2", tags=["v2"])

@router.get("/predict", response_model=V2PredictResponse)
async def predict_v2(village_id: int = Query(..., ge=1)):
    payload = await v2_service.get_prediction(village_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f"No v2 prediction found for village {village_id}")
    return payload

@router.get("/map-data")
async def map_data_v2():
    return await v2_service.get_map_data()

@router.get("/lulc-trends", response_model=V2LulcTrendsResponse)
async def lulc_trends_v2(village_id: int = Query(..., ge=1)):
    payload = await v2_service.get_lulc_trends(village_id)
    if not payload:
        raise HTTPException(status_code=404, detail=f"No lulc trends found for village {village_id}")
    return payload

@router.post("/retrain")
async def retrain_v2(background_tasks: BackgroundTasks):
    background_tasks.add_task(v2_service.retrain)
    return {"status": "Retraining started in background"}
