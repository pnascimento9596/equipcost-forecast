"""Synthetic data generator for equipcost-forecast.

Generates a realistic hospital equipment fleet across 3 facilities (500 total assets)
with 10 years of work order history, service contracts, and PM schedules.
"""

import random
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

# Ensure src is importable when running as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from sqlalchemy.orm import Session

from equipcost_forecast.models.database import get_engine, init_db
from equipcost_forecast.models.orm import (
    Base,
    EquipmentRegistry,
    PMSchedule,
    ServiceContract,
    WorkOrder,
)

SEED = 42
random.seed(SEED)

FACILITIES = ["FAC-001", "FAC-002", "FAC-003"]

DEPARTMENTS = [
    "Radiology",
    "ICU",
    "Emergency",
    "Surgery",
    "Cardiology",
    "Neonatal",
    "Pulmonology",
    "General Medicine",
    "Orthopedics",
    "Anesthesiology",
]

MANUFACTURERS = [
    "GE Healthcare",
    "Siemens Healthineers",
    "Philips Healthcare",
    "Canon Medical",
    "Mindray",
    "Draeger",
    "Masimo",
    "Stryker",
]

# (class, count, cost_min, cost_max, useful_life_months, pm_freq_months, manufacturers, models)
EQUIPMENT_SPECS = [
    (
        "ct_scanner",
        15,
        800_000,
        2_500_000,
        120,
        3,
        ["GE Healthcare", "Siemens Healthineers", "Philips Healthcare", "Canon Medical"],
        ["Revolution CT", "SOMATOM Force", "IQon Spectral CT", "Aquilion ONE"],
    ),
    (
        "mri",
        10,
        1_500_000,
        3_000_000,
        132,
        3,
        ["GE Healthcare", "Siemens Healthineers", "Philips Healthcare", "Canon Medical"],
        ["SIGNA Premier", "MAGNETOM Vida", "Ingenia Ambition", "Vantage Orian"],
    ),
    (
        "ultrasound",
        40,
        50_000,
        250_000,
        84,
        6,
        ["GE Healthcare", "Siemens Healthineers", "Philips Healthcare", "Mindray"],
        ["LOGIQ E10", "ACUSON Sequoia", "EPIQ Elite", "Resona I9"],
    ),
    (
        "ventilator",
        80,
        25_000,
        50_000,
        96,
        6,
        ["Draeger", "GE Healthcare", "Philips Healthcare", "Mindray"],
        ["Evita V800", "CARESCAPE R860", "Trilogy Evo", "SV800"],
    ),
    (
        "infusion_pump",
        120,
        3_000,
        8_000,
        84,
        6,
        ["GE Healthcare", "Mindray"],
        ["Alaris System", "BeneFusion SP5"],
    ),
    (
        "patient_monitor",
        100,
        8_000,
        25_000,
        72,
        6,
        ["GE Healthcare", "Philips Healthcare", "Mindray", "Masimo"],
        ["CARESCAPE B650", "IntelliVue MX800", "BeneVision N22", "Root"],
    ),
    (
        "surgical_light",
        30,
        15_000,
        60_000,
        120,
        12,
        ["Stryker", "GE Healthcare", "Draeger"],
        ["Visum II", "HeraLux LED", "Polaris 600"],
    ),
    (
        "defibrillator",
        40,
        15_000,
        35_000,
        96,
        6,
        ["Philips Healthcare", "Stryker", "GE Healthcare", "Mindray"],
        ["HeartStart MRx", "LIFEPAK 15", "MAC VU360", "BeneHeart D6"],
    ),
    (
        "anesthesia_machine",
        35,
        40_000,
        100_000,
        120,
        3,
        ["Draeger", "GE Healthcare", "Mindray"],
        ["Perseus A500", "Aisys CS2", "WATO EX-65"],
    ),
    (
        "c_arm",
        30,
        100_000,
        300_000,
        96,
        3,
        ["GE Healthcare", "Siemens Healthineers", "Philips Healthcare"],
        ["OEC 3D", "Cios Alpha", "Zenition 50"],
    ),
]

# Base corrective repair costs by equipment class
BASE_REPAIR_COSTS = {
    "ct_scanner": (2000, 15000),
    "mri": (3000, 20000),
    "ultrasound": (500, 3000),
    "ventilator": (300, 2000),
    "infusion_pump": (100, 500),
    "patient_monitor": (200, 1000),
    "surgical_light": (200, 1500),
    "defibrillator": (300, 2000),
    "anesthesia_machine": (500, 4000),
    "c_arm": (1000, 8000),
}

# Base PM costs by equipment class
BASE_PM_COSTS = {
    "ct_scanner": (800, 3000),
    "mri": (1000, 4000),
    "ultrasound": (200, 800),
    "ventilator": (150, 500),
    "infusion_pump": (50, 200),
    "patient_monitor": (100, 400),
    "surgical_light": (100, 500),
    "defibrillator": (150, 600),
    "anesthesia_machine": (300, 1200),
    "c_arm": (500, 2000),
}

# Contract cost as fraction of acquisition cost
CONTRACT_COST_FRACTIONS = {
    "full_service": (0.08, 0.12),
    "preventive_only": (0.03, 0.05),
    "parts_only": (0.02, 0.04),
    "time_and_materials": (0.01, 0.02),
    "per_call": (0.005, 0.015),
}

WO_TYPES_CORRECTIVE = ["corrective_repair"]
WO_TYPES_PM = [
    "preventive_maintenance",
    "safety_inspection",
    "calibration",
]

PRIORITIES = ["emergency", "urgent", "routine", "scheduled"]
PRIORITY_WEIGHTS = [0.05, 0.15, 0.50, 0.30]

TECHNICIAN_TYPES = ["in_house", "oem", "third_party_iso"]

ROOT_CAUSES = [
    "Normal wear",
    "Component fatigue",
    "Electrical fault",
    "Software error",
    "Calibration drift",
    "User error",
    "Power surge",
    "Fluid leak",
    "Mechanical failure",
    "Sensor degradation",
    None,
]

TODAY = date(2026, 2, 26)
HISTORY_START = date(2016, 1, 1)


def _random_date(start: date, end: date) -> date:
    delta = (end - start).days
    if delta <= 0:
        return start
    return start + timedelta(days=random.randint(0, delta))


def _bathtub_repair_rate(age_years: float) -> float:
    """Annual corrective repair rate following bathtub curve."""
    if age_years < 1:
        return random.uniform(0.5, 1.5)
    elif age_years < 7:
        return random.uniform(0.3, 0.8)
    else:
        base = 1.0
        escalation = 0.3 * (age_years - 7)
        return min(base + escalation, 4.0)


def _escalated_cost(base_min: int, base_max: int, age_years: float) -> Decimal:
    """Repair cost with age-based escalation."""
    base = random.uniform(base_min, base_max)
    factor = (1 + 0.08 * age_years) ** 1.5
    return Decimal(str(round(base * factor, 2)))


def _escalated_parts_cost(base_cost: float, age_years: float) -> Decimal:
    """Parts cost escalates faster than labor."""
    factor = (1 + 0.12 * age_years) ** 1.3
    return Decimal(str(round(base_cost * factor, 2)))


def generate_equipment(session: Session) -> list[EquipmentRegistry]:
    """Generate 500 equipment assets across 3 facilities."""
    equipment_list = []
    asset_counter = 0

    for spec in EQUIPMENT_SPECS:
        (
            eq_class,
            count,
            cost_min,
            cost_max,
            useful_life,
            _pm_freq,
            mfrs,
            models,
        ) = spec

        for _ in range(count):
            asset_counter += 1
            age_years = random.uniform(0, 15)
            acq_date = TODAY - timedelta(days=int(age_years * 365.25))
            if acq_date < HISTORY_START:
                acq_date = _random_date(
                    HISTORY_START, HISTORY_START + timedelta(days=365)
                )

            acq_cost = Decimal(str(round(random.uniform(cost_min, cost_max), 2)))
            manufacturer = random.choice(mfrs)
            model_name = random.choice(models)
            facility = random.choice(FACILITIES)
            dept = random.choice(DEPARTMENTS)

            install_date = acq_date + timedelta(days=random.randint(7, 90))
            warranty_exp = acq_date + timedelta(days=365 * random.choice([1, 2, 3]))

            age_months = int(age_years * 12)
            if age_months > useful_life + 36:
                status = random.choice(
                    ["active", "active", "inactive", "pending_replacement"]
                )
            elif age_months > useful_life:
                status = random.choice(["active", "active", "pending_replacement"])
            else:
                status = "active"

            eq = EquipmentRegistry(
                asset_tag=f"EQ-{acq_date.year}-{asset_counter:04d}",
                serial_number=f"SN-{manufacturer[:2].upper()}{random.randint(100000, 999999)}",
                equipment_class=eq_class,
                manufacturer=manufacturer,
                model_name=model_name,
                facility_id=facility,
                department=dept,
                acquisition_date=acq_date,
                acquisition_cost=acq_cost,
                installation_date=install_date,
                warranty_expiration=warranty_exp,
                expected_useful_life_months=useful_life,
                status=status,
            )
            session.add(eq)
            equipment_list.append(eq)

    session.flush()
    return equipment_list


def generate_work_orders(
    session: Session, equipment_list: list[EquipmentRegistry]
) -> int:
    """Generate 10 years of work order history."""
    wo_counter = 0

    for eq in equipment_list:
        spec = next(s for s in EQUIPMENT_SPECS if s[0] == eq.equipment_class)
        pm_freq_months = spec[5]
        repair_range = BASE_REPAIR_COSTS[eq.equipment_class]
        pm_range = BASE_PM_COSTS[eq.equipment_class]

        start = max(eq.installation_date or eq.acquisition_date, HISTORY_START)

        # Generate PM work orders
        pm_date = start + timedelta(days=pm_freq_months * 30)
        while pm_date <= TODAY:
            wo_counter += 1
            age_years = (pm_date - eq.acquisition_date).days / 365.25
            pm_cost = Decimal(
                str(round(random.uniform(pm_range[0], pm_range[1]), 2))
            )
            parts = Decimal(str(round(float(pm_cost) * random.uniform(0.1, 0.4), 2)))
            labor_hrs = Decimal(str(round(random.uniform(1.0, 8.0), 2)))
            labor_cost = Decimal(str(round(float(labor_hrs) * random.uniform(75, 150), 2)))
            total = labor_cost + parts + pm_cost

            wo = WorkOrder(
                equipment_id=eq.id,
                work_order_number=f"WO-{wo_counter:07d}",
                wo_type=random.choice(WO_TYPES_PM),
                priority="scheduled",
                opened_date=pm_date,
                completed_date=pm_date + timedelta(days=random.randint(0, 2)),
                description=f"Scheduled {eq.equipment_class} maintenance",
                labor_hours=labor_hrs,
                labor_cost=labor_cost,
                parts_cost=parts,
                vendor_service_cost=Decimal("0.00"),
                total_cost=total,
                downtime_hours=Decimal(str(round(random.uniform(1, 8), 2))),
                technician_type=random.choice(TECHNICIAN_TYPES),
            )
            session.add(wo)
            pm_date += timedelta(days=pm_freq_months * 30)

        # Generate corrective repair work orders following bathtub curve
        current_date = start
        while current_date <= TODAY:
            age_years = (current_date - eq.acquisition_date).days / 365.25
            annual_rate = _bathtub_repair_rate(age_years)
            days_to_next = int(365.25 / max(annual_rate, 0.1))
            days_to_next = max(30, days_to_next + random.randint(-60, 60))
            current_date += timedelta(days=days_to_next)

            if current_date > TODAY:
                break

            wo_counter += 1
            age_at_repair = (current_date - eq.acquisition_date).days / 365.25

            labor_cost_val = _escalated_cost(
                repair_range[0] // 3, repair_range[1] // 3, age_at_repair
            )
            parts_cost_val = _escalated_parts_cost(
                random.uniform(repair_range[0] * 0.3, repair_range[1] * 0.5),
                age_at_repair,
            )
            vendor_cost = Decimal("0.00")
            if random.random() < 0.3:
                vendor_cost = Decimal(
                    str(round(random.uniform(500, float(repair_range[1])), 2))
                )

            total = labor_cost_val + parts_cost_val + vendor_cost
            labor_hrs = Decimal(str(round(random.uniform(2, 24), 2)))
            priority = random.choices(PRIORITIES, PRIORITY_WEIGHTS)[0]
            downtime = Decimal(str(round(random.uniform(2, 72), 2)))
            if priority == "emergency":
                downtime = Decimal(str(round(random.uniform(4, 168), 2)))

            wo = WorkOrder(
                equipment_id=eq.id,
                work_order_number=f"WO-{wo_counter:07d}",
                wo_type="corrective_repair",
                priority=priority,
                opened_date=current_date,
                completed_date=current_date
                + timedelta(days=random.randint(0, 14)),
                description=f"Corrective repair for {eq.equipment_class}",
                root_cause=random.choice(ROOT_CAUSES),
                labor_hours=labor_hrs,
                labor_cost=labor_cost_val,
                parts_cost=parts_cost_val,
                vendor_service_cost=vendor_cost,
                total_cost=total,
                downtime_hours=downtime,
                technician_type=random.choice(TECHNICIAN_TYPES),
            )
            session.add(wo)

    session.flush()
    return wo_counter


def generate_service_contracts(
    session: Session, equipment_list: list[EquipmentRegistry]
) -> int:
    """Generate service contracts with age-appropriate types."""
    contract_count = 0

    for eq in equipment_list:
        age_years = (TODAY - eq.acquisition_date).days / 365.25
        acq_cost = float(eq.acquisition_cost)

        if age_years <= 3:
            # OEM warranty then full-service
            contract_types = ["full_service"]
            providers = [eq.manufacturer]
        elif age_years <= 7:
            # Mix of OEM and ISO
            if random.random() < 0.6:
                contract_types = ["full_service", "preventive_only"]
                providers = [
                    eq.manufacturer,
                    random.choice(
                        ["Aramark", "TRIMEDX", "Sodexo HTM", "Agiliti"]
                    ),
                ]
            else:
                contract_types = ["parts_only"]
                providers = [
                    random.choice(
                        ["Aramark", "TRIMEDX", "Sodexo HTM", "Agiliti"]
                    )
                ]
        else:
            # Older: T&M, per-call, or no contract
            if random.random() < 0.3:
                continue  # no contract, in-house only
            contract_types = random.choice(
                [["time_and_materials"], ["per_call"]]
            )
            providers = [
                random.choice(["TRIMEDX", "Sodexo HTM", "Agiliti", "local_iso"])
            ]

        for ct, prov in zip(contract_types, providers):
            frac_range = CONTRACT_COST_FRACTIONS[ct]
            annual_cost = Decimal(
                str(
                    round(
                        acq_cost * random.uniform(frac_range[0], frac_range[1]), 2
                    )
                )
            )
            start = eq.warranty_expiration or (
                eq.acquisition_date + timedelta(days=365)
            )
            end = start + timedelta(days=365 * random.choice([1, 2, 3]))

            contract = ServiceContract(
                equipment_id=eq.id,
                contract_type=ct,
                provider=prov,
                annual_cost=annual_cost,
                start_date=start,
                end_date=end,
                includes_parts=ct in ("full_service", "parts_only"),
                includes_labor=ct in ("full_service",),
                includes_pm=ct in ("full_service", "preventive_only"),
                response_time_hours=random.choice([2, 4, 8, 24]),
                uptime_guarantee_pct=(
                    Decimal(str(round(random.uniform(95.0, 99.5), 2)))
                    if ct == "full_service"
                    else None
                ),
            )
            session.add(contract)
            contract_count += 1

    session.flush()
    return contract_count


def generate_pm_schedules(
    session: Session, equipment_list: list[EquipmentRegistry]
) -> int:
    """Generate PM schedules based on equipment class."""
    pm_count = 0
    pm_types = {
        1: "monthly_inspection",
        3: "quarterly_calibration",
        6: "semi_annual_pm",
        12: "annual_pm",
    }

    for eq in equipment_list:
        spec = next(s for s in EQUIPMENT_SPECS if s[0] == eq.equipment_class)
        base_freq = spec[5]
        pm_range = BASE_PM_COSTS[eq.equipment_class]

        # Each asset gets its base PM plus an annual PM
        frequencies = [base_freq]
        if base_freq != 12:
            frequencies.append(12)

        for freq in frequencies:
            pm_type = pm_types.get(freq, f"every_{freq}_months")
            last_done = TODAY - timedelta(days=random.randint(1, freq * 30))
            next_due = last_done + timedelta(days=freq * 30)

            schedule = PMSchedule(
                equipment_id=eq.id,
                pm_type=pm_type,
                frequency_months=freq,
                estimated_duration_hours=Decimal(
                    str(round(random.uniform(1.0, 8.0), 1))
                ),
                estimated_cost=Decimal(
                    str(round(random.uniform(pm_range[0], pm_range[1]), 2))
                ),
                last_completed=last_done,
                next_due=next_due,
            )
            session.add(schedule)
            pm_count += 1

    session.flush()
    return pm_count


def main() -> None:
    """Run the full data generation pipeline."""
    print("Initializing database...")
    engine = get_engine()
    Base.metadata.drop_all(engine)
    init_db(engine)

    from sqlalchemy.orm import sessionmaker

    SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    session = SessionLocal()

    try:
        print("Generating equipment fleet (500 assets)...")
        equipment = generate_equipment(session)
        print(f"  Created {len(equipment)} equipment records")

        print("Generating work orders (10 years of history)...")
        wo_count = generate_work_orders(session, equipment)
        print(f"  Created {wo_count} work orders")

        print("Generating service contracts...")
        contract_count = generate_service_contracts(session, equipment)
        print(f"  Created {contract_count} contracts")

        print("Generating PM schedules...")
        pm_count = generate_pm_schedules(session, equipment)
        print(f"  Created {pm_count} PM schedules")

        session.commit()
        print("\nData generation complete!")

        # Summary stats
        from sqlalchemy import func

        total_eq = session.query(func.count(EquipmentRegistry.id)).scalar()
        total_wo = session.query(func.count(WorkOrder.id)).scalar()
        total_sc = session.query(func.count(ServiceContract.id)).scalar()
        total_pm = session.query(func.count(PMSchedule.id)).scalar()

        print(f"\nDatabase summary:")
        print(f"  Equipment:         {total_eq}")
        print(f"  Work orders:       {total_wo}")
        print(f"  Service contracts: {total_sc}")
        print(f"  PM schedules:      {total_pm}")

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == "__main__":
    main()
