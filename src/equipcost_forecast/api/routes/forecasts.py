import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from equipcost_forecast.api.dependencies import get_db
from equipcost_forecast.forecasting.cost_aggregator import CostAggregator
from equipcost_forecast.forecasting.time_series import CostForecaster
from equipcost_forecast.models.orm import (
    CostForecast,
    EquipmentRegistry,
    MonthlyCostRollup,
)

router = APIRouter(prefix="/forecasts", tags=["forecasts"])


class ForecastRequest(BaseModel):
    asset_tag: str | None = None
    horizon: int = 36
    method: str = "auto"


def _resolve_equipment(asset_tag: str, session: Session) -> EquipmentRegistry:
    eq = session.execute(
        select(EquipmentRegistry).where(EquipmentRegistry.asset_tag == asset_tag)
    ).scalar_one_or_none()
    if not eq:
        raise HTTPException(404, f"Equipment '{asset_tag}' not found")
    return eq


@router.post("/generate")
def generate_forecast(body: ForecastRequest, session: Session = Depends(get_db)):
    """Generate forecasts for one or all assets."""
    if body.asset_tag:
        eq = _resolve_equipment(body.asset_tag, session)
        eq_ids = [eq.id]
    else:
        eq_ids = [r[0] for r in session.execute(select(EquipmentRegistry.id)).all()]

    aggregator = CostAggregator(session)
    forecaster = CostForecaster(min_history_months=12)

    results = []
    errors = []
    for eid in eq_ids:
        # Ensure rollups exist
        existing = session.execute(
            select(MonthlyCostRollup.id)
            .where(MonthlyCostRollup.equipment_id == eid)
            .limit(1)
        ).scalar_one_or_none()
        if existing is None:
            aggregator.compute_monthly_rollups(eid)

        try:
            forecaster.forecast_equipment(eid, session, body.horizon, body.method)
            results.append(eid)
        except ValueError as e:
            errors.append({"equipment_id": eid, "error": str(e)})

    return {
        "forecasted": len(results),
        "errors": len(errors),
        "error_details": errors[:10],
    }


@router.get("/{asset_tag}")
def get_forecast(asset_tag: str, session: Session = Depends(get_db)):
    """Get latest forecast for an equipment item."""
    eq = _resolve_equipment(asset_tag, session)

    forecast = session.execute(
        select(CostForecast)
        .where(CostForecast.equipment_id == eq.id)
        .order_by(CostForecast.forecast_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not forecast:
        raise HTTPException(404, f"No forecast found for '{asset_tag}'")

    monthly = (
        json.loads(forecast.monthly_forecasts) if forecast.monthly_forecasts else []
    )
    metrics = json.loads(forecast.model_metrics) if forecast.model_metrics else {}

    return {
        "asset_tag": asset_tag,
        "forecast_date": (
            forecast.forecast_date.isoformat() if forecast.forecast_date else None
        ),
        "forecast_method": forecast.forecast_method,
        "horizon_months": forecast.forecast_horizon_months,
        "annual_tco_current_year": float(forecast.annual_tco_current_year or 0),
        "annual_tco_next_year": float(forecast.annual_tco_next_year or 0),
        "cumulative_tco_to_date": float(forecast.cumulative_tco_to_date or 0),
        "monthly_forecasts": monthly,
        "model_metrics": metrics,
    }


@router.get("/fleet-summary")
def fleet_forecast_summary(
    facility_id: str | None = None, session: Session = Depends(get_db)
):
    """Aggregate forecast summary by equipment class and facility."""
    from sqlalchemy import func

    stmt = (
        select(
            EquipmentRegistry.equipment_class,
            EquipmentRegistry.facility_id,
            func.count(CostForecast.id).label("forecast_count"),
            func.avg(CostForecast.annual_tco_next_year).label("avg_next_year"),
            func.sum(CostForecast.annual_tco_next_year).label("total_next_year"),
        )
        .join(CostForecast, CostForecast.equipment_id == EquipmentRegistry.id)
        .group_by(EquipmentRegistry.equipment_class, EquipmentRegistry.facility_id)
    )
    if facility_id:
        stmt = stmt.where(EquipmentRegistry.facility_id == facility_id)

    rows = session.execute(stmt).all()

    return {
        "summary": [
            {
                "equipment_class": row.equipment_class,
                "facility_id": row.facility_id,
                "forecast_count": row.forecast_count,
                "avg_annual_tco_next_year": round(float(row.avg_next_year or 0), 2),
                "total_annual_tco_next_year": round(float(row.total_next_year or 0), 2),
            }
            for row in rows
        ]
    }
