from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from equipcost_forecast.api.dependencies import get_db
from equipcost_forecast.models.orm import (
    EquipmentRegistry,
    MonthlyCostRollup,
    ServiceContract,
    WorkOrder,
)

router = APIRouter(prefix="/equipment", tags=["equipment"])


@router.get("/")
def list_equipment(
    facility_id: str | None = None,
    equipment_class: str | None = None,
    status: str | None = None,
    manufacturer: str | None = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
):
    """List equipment with pagination and filters."""
    stmt = select(EquipmentRegistry)
    count_stmt = select(func.count(EquipmentRegistry.id))

    if facility_id:
        stmt = stmt.where(EquipmentRegistry.facility_id == facility_id)
        count_stmt = count_stmt.where(EquipmentRegistry.facility_id == facility_id)
    if equipment_class:
        stmt = stmt.where(EquipmentRegistry.equipment_class == equipment_class)
        count_stmt = count_stmt.where(
            EquipmentRegistry.equipment_class == equipment_class
        )
    if status:
        stmt = stmt.where(EquipmentRegistry.status == status)
        count_stmt = count_stmt.where(EquipmentRegistry.status == status)
    if manufacturer:
        stmt = stmt.where(EquipmentRegistry.manufacturer == manufacturer)
        count_stmt = count_stmt.where(EquipmentRegistry.manufacturer == manufacturer)

    total = session.execute(count_stmt).scalar() or 0
    offset = (page - 1) * page_size
    items = list(
        session.scalars(
            stmt.order_by(EquipmentRegistry.id).offset(offset).limit(page_size)
        ).all()
    )

    return {
        "items": [
            {
                "id": e.id,
                "asset_tag": e.asset_tag,
                "equipment_class": e.equipment_class,
                "manufacturer": e.manufacturer,
                "model_name": e.model_name,
                "facility_id": e.facility_id,
                "department": e.department,
                "acquisition_date": e.acquisition_date.isoformat(),
                "acquisition_cost": float(e.acquisition_cost),
                "status": e.status,
                "expected_useful_life_months": e.expected_useful_life_months,
            }
            for e in items
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/{asset_tag}")
def get_equipment_detail(asset_tag: str, session: Session = Depends(get_db)):
    """Get full equipment detail including active contracts and cost summary."""
    eq = session.execute(
        select(EquipmentRegistry).where(EquipmentRegistry.asset_tag == asset_tag)
    ).scalar_one_or_none()

    if not eq:
        raise HTTPException(404, f"Equipment '{asset_tag}' not found")

    # Active contracts
    today = date.today()
    contracts = list(
        session.scalars(
            select(ServiceContract).where(
                ServiceContract.equipment_id == eq.id,
                ServiceContract.end_date >= today,
            )
        ).all()
    )

    # Cost summary from rollups
    cost_row = session.execute(
        select(
            func.sum(MonthlyCostRollup.total_cost).label("total"),
            func.sum(MonthlyCostRollup.downtime_hours).label("downtime"),
            func.count(MonthlyCostRollup.id).label("months"),
        ).where(MonthlyCostRollup.equipment_id == eq.id)
    ).one()

    age_years = round((today - eq.acquisition_date).days / 365.25, 1)

    return {
        "id": eq.id,
        "asset_tag": eq.asset_tag,
        "serial_number": eq.serial_number,
        "equipment_class": eq.equipment_class,
        "manufacturer": eq.manufacturer,
        "model_name": eq.model_name,
        "facility_id": eq.facility_id,
        "department": eq.department,
        "acquisition_date": eq.acquisition_date.isoformat(),
        "acquisition_cost": float(eq.acquisition_cost),
        "installation_date": (
            eq.installation_date.isoformat() if eq.installation_date else None
        ),
        "warranty_expiration": (
            eq.warranty_expiration.isoformat() if eq.warranty_expiration else None
        ),
        "expected_useful_life_months": eq.expected_useful_life_months,
        "status": eq.status,
        "age_years": age_years,
        "active_contracts": [
            {
                "id": c.id,
                "contract_type": c.contract_type,
                "provider": c.provider,
                "annual_cost": float(c.annual_cost) if c.annual_cost else None,
                "end_date": c.end_date.isoformat() if c.end_date else None,
            }
            for c in contracts
        ],
        "cost_summary": {
            "total_maintenance_cost": float(cost_row.total or 0),
            "total_downtime_hours": float(cost_row.downtime or 0),
            "months_tracked": cost_row.months or 0,
        },
    }


@router.get("/{asset_tag}/work-orders")
def get_work_orders(
    asset_tag: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    session: Session = Depends(get_db),
):
    """Get paginated work order history for an equipment item."""
    eq = session.execute(
        select(EquipmentRegistry).where(EquipmentRegistry.asset_tag == asset_tag)
    ).scalar_one_or_none()

    if not eq:
        raise HTTPException(404, f"Equipment '{asset_tag}' not found")

    total = (
        session.execute(
            select(func.count(WorkOrder.id)).where(WorkOrder.equipment_id == eq.id)
        ).scalar()
        or 0
    )

    offset = (page - 1) * page_size
    orders = list(
        session.scalars(
            select(WorkOrder)
            .where(WorkOrder.equipment_id == eq.id)
            .order_by(WorkOrder.opened_date.desc())
            .offset(offset)
            .limit(page_size)
        ).all()
    )

    return {
        "items": [
            {
                "id": wo.id,
                "work_order_number": wo.work_order_number,
                "wo_type": wo.wo_type,
                "priority": wo.priority,
                "opened_date": wo.opened_date.isoformat(),
                "completed_date": (
                    wo.completed_date.isoformat() if wo.completed_date else None
                ),
                "total_cost": float(wo.total_cost) if wo.total_cost else None,
                "downtime_hours": (
                    float(wo.downtime_hours) if wo.downtime_hours else None
                ),
                "technician_type": wo.technician_type,
            }
            for wo in orders
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/{asset_tag}/cost-history")
def get_cost_history(asset_tag: str, session: Session = Depends(get_db)):
    """Get monthly cost rollup time series for an equipment item."""
    eq = session.execute(
        select(EquipmentRegistry).where(EquipmentRegistry.asset_tag == asset_tag)
    ).scalar_one_or_none()

    if not eq:
        raise HTTPException(404, f"Equipment '{asset_tag}' not found")

    rollups = list(
        session.scalars(
            select(MonthlyCostRollup)
            .where(MonthlyCostRollup.equipment_id == eq.id)
            .order_by(MonthlyCostRollup.month)
        ).all()
    )

    return {
        "asset_tag": asset_tag,
        "months": [
            {
                "month": r.month.isoformat(),
                "pm_cost": float(r.pm_cost or 0),
                "corrective_cost": float(r.corrective_cost or 0),
                "parts_cost": float(r.parts_cost or 0),
                "contract_cost": float(r.contract_cost_allocated or 0),
                "downtime_hours": float(r.downtime_hours or 0),
                "work_order_count": r.work_order_count or 0,
                "total_cost": float(r.total_cost or 0),
            }
            for r in rollups
        ],
    }
