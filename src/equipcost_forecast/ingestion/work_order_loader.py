from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import WorkOrder


def load_work_orders(
    session: Session, equipment_id: int | None = None
) -> list[WorkOrder]:
    """Load work orders, optionally filtered by equipment."""
    stmt = select(WorkOrder).order_by(WorkOrder.opened_date)
    if equipment_id is not None:
        stmt = stmt.where(WorkOrder.equipment_id == equipment_id)
    return list(session.scalars(stmt).all())


def load_work_orders_by_type(
    session: Session, wo_type: str, equipment_id: int | None = None
) -> list[WorkOrder]:
    """Load work orders filtered by type."""
    stmt = (
        select(WorkOrder)
        .where(WorkOrder.wo_type == wo_type)
        .order_by(WorkOrder.opened_date)
    )
    if equipment_id is not None:
        stmt = stmt.where(WorkOrder.equipment_id == equipment_id)
    return list(session.scalars(stmt).all())


def load_work_orders_in_range(
    session: Session,
    start_date: date,
    end_date: date,
    equipment_id: int | None = None,
) -> list[WorkOrder]:
    """Load work orders within a date range."""
    stmt = (
        select(WorkOrder)
        .where(WorkOrder.opened_date >= start_date, WorkOrder.opened_date <= end_date)
        .order_by(WorkOrder.opened_date)
    )
    if equipment_id is not None:
        stmt = stmt.where(WorkOrder.equipment_id == equipment_id)
    return list(session.scalars(stmt).all())
