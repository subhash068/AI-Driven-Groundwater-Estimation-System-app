from pydantic import BaseModel, Field


class VillageStatusResponse(BaseModel):
    village_id: int
    current_depth: float | None = Field(default=None)
    predicted_groundwater_level: float | None = Field(default=None)
    nearest_distance_km: float | None = Field(default=None)
    forecast_3_month: list[dict]
    forecast_yearly: list[dict] = Field(default_factory=list)
    anomaly_flags: list[str]
    confidence_score: float | None = None
    risk_level: str | None = None
    alert_status: str | None = None
    trend_direction: str | None = None
    recommended_actions: list[str] = Field(default_factory=list)
    dist_nearest_tank_km: float | None = Field(default=None)
    recharge_score: float | None = Field(default=None)
    nearest_piezo_id: str | None = Field(default=None)


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
    village_name: str | None = None
    confidence_score: float | None = None
    risk_level: str | None = None
    alert_status: str | None = None
    trend_direction: str | None = None
    observed_series: list[dict] = Field(default_factory=list)
    forecast_3_month: list[dict]
    forecast_yearly: list[dict] = Field(default_factory=list)
    recommended_actions: list[str] = Field(default_factory=list)


class AnomalyAlert(BaseModel):
    village_id: int
    anomaly_type: str
    anomaly_score: float | None = None
    detected_at: str
    alert_level: str | None = None
    recommendation: str | None = None


class AnomalyAlertResponse(BaseModel):
    alerts: list[AnomalyAlert]


class ShapFactor(BaseModel):
    label: str
    value: float

class V2PredictResponse(BaseModel):
    village_id: int
    village_name: str
    mandal: str | None = None
    district: str | None = None
    groundwater_level: float | None
    confidence: float
    risk_level: str
    trend: str
    monthly_predicted_gw: list[float] = Field(default_factory=list)
    monthly_dates: list[str] = Field(default_factory=list)
    water_pct: float | None = None
    trees_pct: float | None = None
    crops_pct: float | None = None
    built_area_pct: float | None = None
    dist_to_sensor_km: float | None = Field(default=None)
    dist_nearest_tank_km: float | None = Field(default=None)
    recharge_score: float | None = Field(default=None)
    nearest_piezo_id: str | None = Field(default=None)
    top_factors: list[ShapFactor] = Field(default_factory=list)


class V2LulcTrendsResponse(BaseModel):
    village_id: int
    built_area_change_pct: float | None
    lulc_start_year: int | None
    lulc_end_year: int | None
    lulc_start_dominant: str | None
    lulc_end_dominant: str | None
