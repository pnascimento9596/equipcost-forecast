from sqlalchemy import select
from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import PMSchedule, ServiceContract


def load_contracts(
    session: Session, equipment_id: int | None = None
) -> list[ServiceContract]:
    """Load service contracts, optionally filtered by equipment."""
    stmt = select(ServiceContract).order_by(ServiceContract.start_date)
    if equipment_id is not None:
        stmt = stmt.where(ServiceContract.equipment_id == equipment_id)
    return list(session.scalars(stmt).all())


def load_pm_schedules(
    session: Session, equipment_id: int | None = None
) -> list[PMSchedule]:
    """Load PM schedules, optionally filtered by equipment."""
    stmt = select(PMSchedule).order_by(PMSchedule.next_due)
    if equipment_id is not None:
        stmt = stmt.where(PMSchedule.equipment_id == equipment_id)
    return list(session.scalars(stmt).all())


def get_active_contracts(session: Session, equipment_id: int) -> list[ServiceContract]:
    """Load active (non-expired) contracts for an equipment item."""
    from datetime import date

    today = date.today()
    stmt = (
        select(ServiceContract)
        .where(
            ServiceContract.equipment_id == equipment_id,
            ServiceContract.end_date >= today,
        )
        .order_by(ServiceContract.start_date)
    )
    return list(session.scalars(stmt).all())
