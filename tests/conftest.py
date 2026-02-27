from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import (
    Base,
    EquipmentRegistry,
    ServiceContract,
    WorkOrder,
)


@pytest.fixture(scope="session")
def engine():
    eng = create_engine("sqlite:///:memory:", echo=False)
    Base.metadata.create_all(eng)
    return eng


@pytest.fixture
def session(engine):
    connection = engine.connect()
    transaction = connection.begin()
    sess = Session(bind=connection)
    yield sess
    sess.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def sample_equipment(session):
    """Create a CT scanner with 8 years of history."""
    eq = EquipmentRegistry(
        asset_tag="EQ-TEST-0001",
        serial_number="SN-TEST-001",
        equipment_class="ct_scanner",
        manufacturer="GE Healthcare",
        model_name="Revolution CT",
        facility_id="FAC-001",
        department="Radiology",
        acquisition_date=date(2018, 3, 15),
        acquisition_cost=Decimal("1500000.00"),
        installation_date=date(2018, 4, 1),
        warranty_expiration=date(2021, 3, 15),
        expected_useful_life_months=120,
        status="active",
    )
    session.add(eq)
    session.flush()
    return eq


@pytest.fixture
def sample_new_equipment(session):
    """Create a new infusion pump (1 year old)."""
    eq = EquipmentRegistry(
        asset_tag="EQ-TEST-0002",
        serial_number="SN-TEST-002",
        equipment_class="infusion_pump",
        manufacturer="Mindray",
        model_name="BeneFusion SP5",
        facility_id="FAC-001",
        department="ICU",
        acquisition_date=date(2025, 2, 1),
        acquisition_cost=Decimal("5000.00"),
        installation_date=date(2025, 2, 15),
        warranty_expiration=date(2027, 2, 1),
        expected_useful_life_months=84,
        status="active",
    )
    session.add(eq)
    session.flush()
    return eq


@pytest.fixture
def work_orders_for_equipment(session, sample_equipment):
    """Generate work orders spanning multiple years for the sample CT scanner."""
    eq = sample_equipment
    wo_list = []
    wo_num = 0
    base_date = date(2018, 6, 1)

    # PM work orders: quarterly for ~7 years
    for i in range(28):
        wo_num += 1
        wo_date = base_date + timedelta(days=90 * i)
        if wo_date > date(2026, 2, 26):
            break
        wo = WorkOrder(
            equipment_id=eq.id,
            work_order_number=f"WO-TEST-{wo_num:04d}",
            wo_type="preventive_maintenance",
            priority="scheduled",
            opened_date=wo_date,
            completed_date=wo_date + timedelta(days=1),
            description="Quarterly PM",
            labor_hours=Decimal("4.00"),
            labor_cost=Decimal("400.00"),
            parts_cost=Decimal("200.00"),
            vendor_service_cost=Decimal("0.00"),
            total_cost=Decimal("1200.00"),
            downtime_hours=Decimal("6.00"),
            technician_type="in_house",
        )
        session.add(wo)
        wo_list.append(wo)

    # Corrective repairs: escalating over time (bathtub curve)
    repair_dates_costs = [
        # Early life: few repairs
        (date(2018, 9, 10), Decimal("2500.00")),
        (date(2019, 4, 20), Decimal("3200.00")),
        # Useful life: low rate
        (date(2020, 2, 15), Decimal("2800.00")),
        (date(2020, 11, 5), Decimal("3500.00")),
        (date(2021, 8, 22), Decimal("4100.00")),
        (date(2022, 5, 10), Decimal("3900.00")),
        (date(2023, 1, 18), Decimal("4500.00")),
        # Wear-out phase: escalating
        (date(2023, 7, 5), Decimal("5200.00")),
        (date(2023, 11, 20), Decimal("6800.00")),
        (date(2024, 3, 8), Decimal("7500.00")),
        (date(2024, 7, 15), Decimal("8200.00")),
        (date(2024, 10, 1), Decimal("9100.00")),
        (date(2025, 1, 12), Decimal("10500.00")),
        (date(2025, 5, 20), Decimal("11200.00")),
        (date(2025, 9, 10), Decimal("12800.00")),
        (date(2025, 12, 1), Decimal("14000.00")),
    ]

    for repair_date, cost in repair_dates_costs:
        wo_num += 1
        parts = Decimal(str(round(float(cost) * 0.4, 2)))
        labor = Decimal(str(round(float(cost) * 0.35, 2)))
        vendor = Decimal(str(round(float(cost) * 0.25, 2)))
        wo = WorkOrder(
            equipment_id=eq.id,
            work_order_number=f"WO-TEST-{wo_num:04d}",
            wo_type="corrective_repair",
            priority="routine",
            opened_date=repair_date,
            completed_date=repair_date + timedelta(days=3),
            description="Corrective repair",
            root_cause="Component fatigue",
            labor_hours=Decimal("8.00"),
            labor_cost=labor,
            parts_cost=parts,
            vendor_service_cost=vendor,
            total_cost=cost,
            downtime_hours=Decimal("24.00"),
            technician_type="oem",
        )
        session.add(wo)
        wo_list.append(wo)

    session.flush()
    return wo_list


@pytest.fixture
def flat_cost_work_orders(session, sample_new_equipment):
    """Generate flat-cost work orders for new equipment."""
    eq = sample_new_equipment
    wo_list = []
    wo_num = 100

    # 12 months of consistent low-cost PMs
    for i in range(12):
        wo_num += 1
        wo_date = date(2025, 2, 1) + timedelta(days=30 * i)
        if wo_date > date(2026, 2, 26):
            break
        wo = WorkOrder(
            equipment_id=eq.id,
            work_order_number=f"WO-FLAT-{wo_num:04d}",
            wo_type="preventive_maintenance",
            priority="scheduled",
            opened_date=wo_date,
            completed_date=wo_date + timedelta(days=1),
            description="Monthly PM for infusion pump",
            labor_hours=Decimal("1.00"),
            labor_cost=Decimal("75.00"),
            parts_cost=Decimal("25.00"),
            vendor_service_cost=Decimal("0.00"),
            total_cost=Decimal("100.00"),
            downtime_hours=Decimal("1.00"),
            technician_type="in_house",
        )
        session.add(wo)
        wo_list.append(wo)

    session.flush()
    return wo_list


@pytest.fixture
def sample_contract(session, sample_equipment):
    """Create a service contract for the sample CT scanner."""
    contract = ServiceContract(
        equipment_id=sample_equipment.id,
        contract_type="full_service",
        provider="GE Healthcare",
        annual_cost=Decimal("150000.00"),
        start_date=date(2021, 4, 1),
        end_date=date(2026, 3, 31),
        includes_parts=True,
        includes_labor=True,
        includes_pm=True,
        response_time_hours=4,
        uptime_guarantee_pct=Decimal("98.00"),
    )
    session.add(contract)
    session.flush()
    return contract
