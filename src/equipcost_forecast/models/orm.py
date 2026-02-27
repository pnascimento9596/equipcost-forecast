from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class EquipmentRegistry(Base):
    __tablename__ = "equipment_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_tag: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    serial_number: Mapped[str | None] = mapped_column(String(50))
    equipment_class: Mapped[str] = mapped_column(String(50), nullable=False)
    manufacturer: Mapped[str | None] = mapped_column(String(100))
    model_name: Mapped[str | None] = mapped_column(String(100))
    facility_id: Mapped[str] = mapped_column(String(20), nullable=False)
    department: Mapped[str | None] = mapped_column(String(100))
    acquisition_date: Mapped[date] = mapped_column(Date, nullable=False)
    acquisition_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    installation_date: Mapped[date | None] = mapped_column(Date)
    warranty_expiration: Mapped[date | None] = mapped_column(Date)
    expected_useful_life_months: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str | None] = mapped_column(String(20))
    disposition_date: Mapped[date | None] = mapped_column(Date)
    disposition_method: Mapped[str | None] = mapped_column(String(30))

    work_orders: Mapped[list["WorkOrder"]] = relationship(back_populates="equipment")
    service_contracts: Mapped[list["ServiceContract"]] = relationship(
        back_populates="equipment"
    )
    pm_schedules: Mapped[list["PMSchedule"]] = relationship(back_populates="equipment")
    cost_forecasts: Mapped[list["CostForecast"]] = relationship(
        back_populates="equipment"
    )
    replacement_analyses: Mapped[list["ReplacementAnalysis"]] = relationship(
        back_populates="equipment"
    )
    depreciation_schedules: Mapped[list["DepreciationSchedule"]] = relationship(
        back_populates="equipment"
    )
    monthly_cost_rollups: Mapped[list["MonthlyCostRollup"]] = relationship(
        back_populates="equipment"
    )


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_registry.id"), nullable=False
    )
    work_order_number: Mapped[str] = mapped_column(
        String(30), unique=True, nullable=False
    )
    wo_type: Mapped[str | None] = mapped_column(String(30))
    priority: Mapped[str | None] = mapped_column(String(20))
    opened_date: Mapped[date] = mapped_column(Date, nullable=False)
    completed_date: Mapped[date | None] = mapped_column(Date)
    description: Mapped[str | None] = mapped_column(String(500))
    root_cause: Mapped[str | None] = mapped_column(String(200))
    labor_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    labor_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    parts_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    vendor_service_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    downtime_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    technician_type: Mapped[str | None] = mapped_column(String(30))

    equipment: Mapped["EquipmentRegistry"] = relationship(back_populates="work_orders")


class ServiceContract(Base):
    __tablename__ = "service_contracts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_registry.id"), nullable=False
    )
    contract_type: Mapped[str | None] = mapped_column(String(30))
    provider: Mapped[str | None] = mapped_column(String(100))
    annual_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    includes_parts: Mapped[bool | None] = mapped_column(Boolean)
    includes_labor: Mapped[bool | None] = mapped_column(Boolean)
    includes_pm: Mapped[bool | None] = mapped_column(Boolean)
    response_time_hours: Mapped[int | None] = mapped_column(Integer)
    uptime_guarantee_pct: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))

    equipment: Mapped["EquipmentRegistry"] = relationship(
        back_populates="service_contracts"
    )


class PMSchedule(Base):
    __tablename__ = "pm_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_registry.id"), nullable=False
    )
    pm_type: Mapped[str | None] = mapped_column(String(50))
    frequency_months: Mapped[int | None] = mapped_column(Integer)
    estimated_duration_hours: Mapped[Decimal | None] = mapped_column(Numeric(4, 1))
    estimated_cost: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    last_completed: Mapped[date | None] = mapped_column(Date)
    next_due: Mapped[date | None] = mapped_column(Date)

    equipment: Mapped["EquipmentRegistry"] = relationship(back_populates="pm_schedules")


class CostForecast(Base):
    __tablename__ = "cost_forecasts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_registry.id"), nullable=False
    )
    forecast_date: Mapped[date | None] = mapped_column(Date)
    forecast_horizon_months: Mapped[int | None] = mapped_column(Integer)
    forecast_method: Mapped[str | None] = mapped_column(String(30))
    monthly_forecasts: Mapped[str | None] = mapped_column(Text)
    annual_tco_current_year: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    annual_tco_next_year: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cumulative_tco_to_date: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    projected_remaining_life_months: Mapped[int | None] = mapped_column(Integer)
    model_metrics: Mapped[str | None] = mapped_column(Text)

    equipment: Mapped["EquipmentRegistry"] = relationship(
        back_populates="cost_forecasts"
    )


class ReplacementAnalysis(Base):
    __tablename__ = "replacement_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_registry.id"), nullable=False
    )
    analysis_date: Mapped[date | None] = mapped_column(Date)
    current_age_months: Mapped[int | None] = mapped_column(Integer)
    remaining_book_value: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    annual_maintenance_cost_current: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2)
    )
    annual_maintenance_cost_projected: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2)
    )
    replacement_cost_estimate: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    npv_continue_operating: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    npv_replace_now: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    npv_savings_if_replaced: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    recommended_action: Mapped[str | None] = mapped_column(String(30))
    optimal_replacement_date: Mapped[date | None] = mapped_column(Date)
    discount_rate: Mapped[Decimal | None] = mapped_column(Numeric(5, 4))

    equipment: Mapped["EquipmentRegistry"] = relationship(
        back_populates="replacement_analyses"
    )


class DepreciationSchedule(Base):
    __tablename__ = "depreciation_schedules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_registry.id"), nullable=False
    )
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    method: Mapped[str | None] = mapped_column(String(20))
    beginning_book_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    depreciation_expense: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))
    ending_book_value: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    accumulated_depreciation: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    equipment: Mapped["EquipmentRegistry"] = relationship(
        back_populates="depreciation_schedules"
    )


class MonthlyCostRollup(Base):
    __tablename__ = "monthly_cost_rollups"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    equipment_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("equipment_registry.id"), nullable=False
    )
    month: Mapped[date | None] = mapped_column(Date)
    pm_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    corrective_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    parts_cost: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    contract_cost_allocated: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    downtime_hours: Mapped[Decimal | None] = mapped_column(Numeric(6, 2))
    work_order_count: Mapped[int | None] = mapped_column(Integer)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 2))

    equipment: Mapped["EquipmentRegistry"] = relationship(
        back_populates="monthly_cost_rollups"
    )
