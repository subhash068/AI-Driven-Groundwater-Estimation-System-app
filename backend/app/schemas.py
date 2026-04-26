from pydantic import BaseModel, Field


class VillageStatusResponse(BaseModel):
    village_id: int
    current_depth: float | None = Field(default=None)
    forecast_3_month: list[dict]
    anomaly_flags: list[str]
    confidence_score: float | None = None


class RechargeRecommendationResponse(BaseModel):
    type: str = "FeatureCollection"
    features: list[dict]


class HealthResponse(BaseModel):
    status: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserProfile(BaseModel):
    username: str
    full_name: str
    role: str
    is_active: bool


class FarmerAdvisory(BaseModel):
    village_id: int
    advisory_level: str
    advisory_text: str
    language_code: str
    channel: str
    generated_at: str


class FarmerAdvisoryResponse(BaseModel):
    advisories: list[FarmerAdvisory]


class FarmerAdvisoryCreate(BaseModel):
    village_id: int
    advisory_level: str
    advisory_text: str
    language_code: str = "en"
    channel: str = "sms"


class VillageEstimateUpsert(BaseModel):
    village_id: int
    estimated_groundwater_depth: float
    confidence_score: float
    anomaly_flag: bool = False
    draft_index: float = 0.5


class VillageForecastResponse(BaseModel):
    village_id: int
    model_name: str
    forecast_3_month: list[dict]


class AnomalyAlert(BaseModel):
    village_id: int
    anomaly_type: str
    anomaly_score: float | None = None
    detected_at: str


class AnomalyAlertResponse(BaseModel):
    alerts: list[AnomalyAlert]
