from datetime import date
from decimal import Decimal

from pydantic import BaseModel

# --- Forecasting schemas ---


class MonthlyForecastPoint(BaseModel):
    month: date
    predicted_cost: Decimal
    lower_bound: Decimal
    upper_bound: Decimal


class ModelMetrics(BaseModel):
    mae: float
    rmse: float
    mape: float


class ForecastResult(BaseModel):
    """Output from a single time-series forecast method."""

    method: str
    horizon_months: int
    predictions: list[MonthlyForecastPoint]
    metrics: ModelMetrics


class BathtubCurveParams(BaseModel):
    equipment_class: str
    early_life_shape: float
    early_life_scale: float
    useful_life_rate: float
    wearout_shape: float
    wearout_scale: float
    transition_month_early: int
    transition_month_wearout: int


class RemainingLifeEstimate(BaseModel):
    equipment_id: int
    current_age_months: int
    estimated_remaining_months: int
    confidence: float
    method: str


class FailurePrediction(BaseModel):
    equipment_id: int
    mtbf_days: float
    predicted_next_failure: date
    probability_within_90_days: float
    estimated_repair_cost: Decimal


class FleetCostSummary(BaseModel):
    facility_id: str | None
    total_equipment: int
    total_annual_cost: Decimal
    avg_cost_per_asset: Decimal
    top_cost_classes: list[dict]
    aging_assets_count: int


class CostForecastSchema(BaseModel):
    equipment_id: int
    forecast_date: date
    forecast_horizon_months: int
    forecast_method: str
    monthly_forecasts: list[MonthlyForecastPoint]
    annual_tco_current_year: Decimal
    annual_tco_next_year: Decimal
    cumulative_tco_to_date: Decimal
    projected_remaining_life_months: int | None
    model_metrics: ModelMetrics


# --- Financial schemas ---


class DepreciationYear(BaseModel):
    fiscal_year: int
    beginning_book_value: float
    depreciation_expense: float
    ending_book_value: float
    accumulated_depreciation: float


class TCOReport(BaseModel):
    equipment_id: int
    asset_tag: str
    equipment_class: str
    acquisition_cost: float
    cumulative_maintenance: float
    cumulative_contracts: float
    estimated_downtime_cost: float
    total_tco: float
    age_years: float
    annualized_tco: float
    maintenance_to_acquisition_ratio: float


class TCOComparison(BaseModel):
    reports: list[TCOReport]
    best_performer: str
    worst_performer: str
    fleet_avg_annualized_tco: float


class NPVResult(BaseModel):
    scenario: str
    npv: float
    annual_cash_flows: list[float]
    discount_rate: float
    horizon_years: int


class RepairReplaceAnalysis(BaseModel):
    equipment_id: int
    asset_tag: str
    current_age_months: int
    remaining_book_value: float
    annual_maintenance_current: float
    annual_maintenance_projected: float
    replacement_cost: float
    npv_continue: float
    npv_replace: float
    npv_savings: float
    recommended_action: str
    optimal_replacement_date: date | None


class ReplacementPriority(BaseModel):
    rank: int
    equipment_id: int
    asset_tag: str
    equipment_class: str
    age_months: int
    npv_savings: float
    recommended_action: str
    replacement_cost: float
    within_budget: bool


class ReplacementScheduleYear(BaseModel):
    fiscal_year: int
    replacements: list[ReplacementPriority]
    year_spend: float
    year_savings: float


class ReplacementSchedule(BaseModel):
    facility_id: str | None
    annual_budget: float
    horizon_years: int
    schedule: list[ReplacementScheduleYear]
    total_spend: float
    total_projected_savings: float
