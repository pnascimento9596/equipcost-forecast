from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from equipcost_forecast.api.dependencies import get_db
from equipcost_forecast.models.orm import EquipmentRegistry

router = APIRouter(tags=["financial"])


def _resolve_equipment(asset_tag: str, session: Session) -> EquipmentRegistry:
    eq = session.execute(
        select(EquipmentRegistry).where(EquipmentRegistry.asset_tag == asset_tag)
    ).scalar_one_or_none()
    if not eq:
        raise HTTPException(404, f"Equipment '{asset_tag}' not found")
    return eq


@router.get("/tco/{asset_tag}")
def get_tco(
    asset_tag: str,
    downtime_rate: float = Query(500.0, description="Hourly downtime cost"),
    session: Session = Depends(get_db),
):
    """Get full TCO report for an equipment item."""
    from equipcost_forecast.financial.tco_calculator import TCOCalculator

    eq = _resolve_equipment(asset_tag, session)
    calculator = TCOCalculator(session, downtime_hourly_rate=downtime_rate)
    try:
        report = calculator.calculate_tco(eq.id)
        return report.model_dump()
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/tco/compare")
def compare_tco(
    asset_tags: str = Query(..., description="Comma-separated asset tags"),
    downtime_rate: float = Query(500.0),
    session: Session = Depends(get_db),
):
    """Side-by-side TCO comparison for multiple assets."""
    from equipcost_forecast.financial.tco_calculator import TCOCalculator

    tags = [t.strip() for t in asset_tags.split(",")]
    if len(tags) < 2:
        raise HTTPException(400, "Need at least 2 asset tags for comparison")

    eq_ids = []
    for tag in tags:
        eq = _resolve_equipment(tag, session)
        eq_ids.append(eq.id)

    calculator = TCOCalculator(session, downtime_hourly_rate=downtime_rate)
    comparison = calculator.compare_tco(eq_ids)
    return comparison.model_dump()


class RepairReplaceRequest(BaseModel):
    replacement_cost: float | None = None
    discount_rate: float = 0.08
    horizon_years: int = 5


@router.post("/repair-vs-replace/{asset_tag}")
def repair_vs_replace(
    asset_tag: str,
    body: RepairReplaceRequest = RepairReplaceRequest(),
    session: Session = Depends(get_db),
):
    """Run repair-vs-replace NPV analysis."""
    from equipcost_forecast.financial.npv_analyzer import NPVAnalyzer

    eq = _resolve_equipment(asset_tag, session)
    analyzer = NPVAnalyzer(discount_rate=body.discount_rate)
    try:
        result = analyzer.repair_vs_replace(
            eq.id,
            session,
            replacement_cost=body.replacement_cost,
            horizon_years=body.horizon_years,
        )
        return result.model_dump()
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/depreciation/{asset_tag}")
def get_depreciation(
    asset_tag: str,
    method: str = Query("straight_line", description="straight_line or macrs"),
    session: Session = Depends(get_db),
):
    """Get depreciation schedule for an equipment item."""
    from equipcost_forecast.financial.depreciation import (
        compute_book_value,
        macrs_schedule,
        straight_line_schedule,
    )

    eq = _resolve_equipment(asset_tag, session)
    cost = float(eq.acquisition_cost)
    useful_months = eq.expected_useful_life_months or 120

    if method == "macrs":
        schedule = macrs_schedule(cost, 7, eq.acquisition_date)
    else:
        salvage = cost * 0.05
        schedule = straight_line_schedule(
            cost, salvage, useful_months // 12, eq.acquisition_date
        )

    book_value = compute_book_value(eq.id, session, method)

    return {
        "asset_tag": asset_tag,
        "method": method,
        "acquisition_cost": cost,
        "current_book_value": round(book_value, 2),
        "schedule": [entry.model_dump() for entry in schedule],
    }
