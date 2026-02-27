from datetime import date
from typing import TypedDict

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from equipcost_forecast.api.dependencies import get_db
from equipcost_forecast.models.orm import (
    CostForecast,
    EquipmentRegistry,
    MonthlyCostRollup,
)

router = APIRouter(prefix="/fleet", tags=["fleet"])


@router.get("/replacement-priorities")
def replacement_priorities(
    facility_id: str | None = None,
    budget: float = Query(2_000_000, description="Annual capital budget"),
    session: Session = Depends(get_db),
):
    """Get ranked replacement priority list with budget filtering."""
    from equipcost_forecast.financial.replacement_optimizer import (
        FleetReplacementOptimizer,
    )

    optimizer = FleetReplacementOptimizer(session, annual_capital_budget=budget)
    priorities = optimizer.rank_replacement_priorities(facility_id)

    return {
        "total_evaluated": len(priorities),
        "recommended_replacements": sum(
            1
            for p in priorities
            if p.recommended_action in ("replace_immediately", "plan_replacement")
        ),
        "items": [p.model_dump() for p in priorities[:50]],
    }


@router.get("/replacement-schedule")
def replacement_schedule(
    facility_id: str | None = None,
    budget: float = Query(2_000_000),
    horizon_years: int = Query(5, ge=1, le=10),
    session: Session = Depends(get_db),
):
    """Get multi-year replacement schedule."""
    from equipcost_forecast.financial.replacement_optimizer import (
        FleetReplacementOptimizer,
    )

    optimizer = FleetReplacementOptimizer(session, annual_capital_budget=budget)
    schedule = optimizer.optimal_replacement_schedule(facility_id, horizon_years)
    return schedule.model_dump()


@router.get("/age-analysis")
def age_analysis(facility_id: str | None = None, session: Session = Depends(get_db)):
    """Fleet age distribution with cost-per-cohort analysis."""
    stmt = select(EquipmentRegistry).where(EquipmentRegistry.status == "active")
    if facility_id:
        stmt = stmt.where(EquipmentRegistry.facility_id == facility_id)

    equipment = list(session.scalars(stmt).all())
    today = date.today()

    class _Cohort(TypedDict):
        min: int
        max: int
        count: int
        classes: dict[str, int]
        total_cost: float

    # Build age cohorts: 0-2, 3-5, 6-8, 9-11, 12+
    cohorts: dict[str, _Cohort] = {
        "0-2 years": {"min": 0, "max": 2, "count": 0, "classes": {}, "total_cost": 0.0},
        "3-5 years": {"min": 3, "max": 5, "count": 0, "classes": {}, "total_cost": 0.0},
        "6-8 years": {"min": 6, "max": 8, "count": 0, "classes": {}, "total_cost": 0.0},
        "9-11 years": {
            "min": 9,
            "max": 11,
            "count": 0,
            "classes": {},
            "total_cost": 0.0,
        },
        "12+ years": {
            "min": 12,
            "max": 999,
            "count": 0,
            "classes": {},
            "total_cost": 0.0,
        },
    }

    eq_ids_by_cohort: dict[str, list[int]] = {k: [] for k in cohorts}

    for eq in equipment:
        age_years = (today - eq.acquisition_date).days / 365.25
        for label, cohort in cohorts.items():
            if cohort["min"] <= age_years < cohort["max"] + 1 or (
                cohort["max"] == 999 and age_years >= cohort["min"]
            ):
                cohort["count"] += 1
                cohort["classes"][eq.equipment_class] = (
                    cohort["classes"].get(eq.equipment_class, 0) + 1
                )
                eq_ids_by_cohort[label].append(eq.id)
                break

    # Get annual costs per cohort from last 12 months
    twelve_months_ago = date(today.year - 1, today.month, 1)
    for label, ids in eq_ids_by_cohort.items():
        if ids:
            total = session.execute(
                select(func.sum(MonthlyCostRollup.total_cost)).where(
                    MonthlyCostRollup.equipment_id.in_(ids),
                    MonthlyCostRollup.month >= twelve_months_ago,
                )
            ).scalar()
            cohorts[label]["total_cost"] = round(float(total or 0), 2)

    result = []
    for label, cohort in cohorts.items():
        avg_cost = cohort["total_cost"] / cohort["count"] if cohort["count"] > 0 else 0
        result.append(
            {
                "cohort": label,
                "count": cohort["count"],
                "equipment_classes": cohort["classes"],
                "total_annual_cost": cohort["total_cost"],
                "avg_annual_cost_per_asset": round(avg_cost, 2),
            }
        )

    return {"facility_id": facility_id, "cohorts": result}


@router.get("/health")
def health_check(session: Session = Depends(get_db)):
    """API health check with DB stats."""
    asset_count = (
        session.execute(select(func.count(EquipmentRegistry.id))).scalar() or 0
    )

    latest_forecast = session.execute(
        select(func.max(CostForecast.forecast_date))
    ).scalar()

    return {
        "status": "ok",
        "database": "connected",
        "total_assets": asset_count,
        "latest_forecast_date": (
            latest_forecast.isoformat() if latest_forecast else None
        ),
    }
