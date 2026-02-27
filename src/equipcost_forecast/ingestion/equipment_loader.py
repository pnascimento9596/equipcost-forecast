from sqlalchemy import select
from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import EquipmentRegistry


def load_equipment(session: Session) -> list[EquipmentRegistry]:
    """Load all equipment records from the database."""
    stmt = select(EquipmentRegistry).order_by(EquipmentRegistry.id)
    return list(session.scalars(stmt).all())


def get_equipment_by_class(
    session: Session, equipment_class: str
) -> list[EquipmentRegistry]:
    """Load equipment filtered by class."""
    stmt = (
        select(EquipmentRegistry)
        .where(EquipmentRegistry.equipment_class == equipment_class)
        .order_by(EquipmentRegistry.id)
    )
    return list(session.scalars(stmt).all())


def get_equipment_by_facility(
    session: Session, facility_id: str
) -> list[EquipmentRegistry]:
    """Load equipment filtered by facility."""
    stmt = (
        select(EquipmentRegistry)
        .where(EquipmentRegistry.facility_id == facility_id)
        .order_by(EquipmentRegistry.id)
    )
    return list(session.scalars(stmt).all())
