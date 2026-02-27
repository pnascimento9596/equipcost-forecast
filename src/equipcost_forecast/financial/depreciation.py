from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import DepreciationSchedule, EquipmentRegistry
from equipcost_forecast.models.schemas import DepreciationYear

# MACRS recovery percentages
MACRS_5YR = [0.20, 0.32, 0.192, 0.1152, 0.1152, 0.0576]
MACRS_7YR = [0.1429, 0.2449, 0.1749, 0.1249, 0.0893, 0.0892, 0.0893, 0.0446]


def _fiscal_year_for_date(d: date) -> int:
    """Return the fiscal year (Oct 1-Sep 30) for a given date."""
    return d.year + 1 if d.month >= 10 else d.year


def straight_line_schedule(
    acquisition_cost: float,
    salvage_value: float,
    useful_life_years: int,
    acquisition_date: date,
) -> list[DepreciationYear]:
    """Compute straight-line depreciation aligned to fiscal year (Oct-Sep).

    Args:
        acquisition_cost: Original purchase price.
        salvage_value: Estimated salvage value at end of useful life.
        useful_life_years: Useful life in full years.
        acquisition_date: Date of acquisition for fiscal year alignment.
    """
    depreciable = acquisition_cost - salvage_value
    annual_expense = depreciable / useful_life_years

    start_fy = _fiscal_year_for_date(acquisition_date)

    # First partial year: prorate based on months remaining in fiscal year
    fy_end_month = 9  # September
    if acquisition_date.month >= 10:
        months_first_year = 12 - (acquisition_date.month - 10)
    else:
        months_first_year = fy_end_month - acquisition_date.month + 1

    prorate_first = months_first_year / 12

    schedule = []
    book_value = acquisition_cost
    accumulated = 0.0
    remaining_depreciable = depreciable

    for i in range(useful_life_years + 1):
        if remaining_depreciable <= 0.01:
            break

        fy = start_fy + i

        if i == 0:
            expense = annual_expense * prorate_first
        elif remaining_depreciable < annual_expense:
            expense = remaining_depreciable
        else:
            expense = annual_expense

        expense = min(expense, remaining_depreciable)
        beginning = book_value
        accumulated += expense
        book_value -= expense
        remaining_depreciable -= expense

        schedule.append(
            DepreciationYear(
                fiscal_year=fy,
                beginning_book_value=round(beginning, 2),
                depreciation_expense=round(expense, 2),
                ending_book_value=round(book_value, 2),
                accumulated_depreciation=round(accumulated, 2),
            )
        )

    return schedule


def macrs_schedule(
    acquisition_cost: float,
    recovery_period: int,
    acquisition_date: date,
) -> list[DepreciationYear]:
    """Compute MACRS depreciation schedule.

    Args:
        acquisition_cost: Original purchase price.
        recovery_period: 5 or 7 year recovery period.
        acquisition_date: Date of acquisition for fiscal year alignment.
    """
    if recovery_period == 5:
        percentages = MACRS_5YR
    elif recovery_period == 7:
        percentages = MACRS_7YR
    else:
        raise ValueError(f"Unsupported MACRS recovery period: {recovery_period}")

    start_fy = _fiscal_year_for_date(acquisition_date)

    schedule = []
    book_value = acquisition_cost
    accumulated = 0.0

    for i, pct in enumerate(percentages):
        expense = acquisition_cost * pct
        beginning = book_value
        accumulated += expense
        book_value -= expense

        schedule.append(
            DepreciationYear(
                fiscal_year=start_fy + i,
                beginning_book_value=round(beginning, 2),
                depreciation_expense=round(expense, 2),
                ending_book_value=round(max(0, book_value), 2),
                accumulated_depreciation=round(accumulated, 2),
            )
        )

    return schedule


def compute_book_value(
    equipment_id: int, session: Session, method: str = "straight_line"
) -> float:
    """Compute current book value and persist depreciation schedule.

    Args:
        equipment_id: Equipment to depreciate.
        session: Database session.
        method: "straight_line" or "macrs".

    Returns:
        Current book value as of today.
    """
    eq = session.get(EquipmentRegistry, equipment_id)
    if not eq:
        raise ValueError(f"Equipment {equipment_id} not found")

    cost = float(eq.acquisition_cost)
    useful_months = eq.expected_useful_life_months or 120
    useful_years = useful_months // 12

    if method == "macrs":
        entries = macrs_schedule(cost, 7, eq.acquisition_date)
    else:
        salvage = cost * 0.05
        entries = straight_line_schedule(
            cost, salvage, useful_years, eq.acquisition_date
        )

    # Delete existing schedules for this equipment+method
    session.execute(
        DepreciationSchedule.__table__.delete().where(
            DepreciationSchedule.equipment_id == equipment_id,
            DepreciationSchedule.method == method,
        )
    )

    current_fy = _fiscal_year_for_date(date.today())
    book_value = cost

    for entry in entries:
        record = DepreciationSchedule(
            equipment_id=equipment_id,
            fiscal_year=entry.fiscal_year,
            method=method,
            beginning_book_value=Decimal(str(entry.beginning_book_value)),
            depreciation_expense=Decimal(str(entry.depreciation_expense)),
            ending_book_value=Decimal(str(entry.ending_book_value)),
            accumulated_depreciation=Decimal(str(entry.accumulated_depreciation)),
        )
        session.add(record)

        if entry.fiscal_year <= current_fy:
            book_value = entry.ending_book_value

    session.flush()
    return book_value
