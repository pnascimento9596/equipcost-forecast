from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from equipcost_forecast.financial.depreciation import compute_book_value
from equipcost_forecast.models.orm import (
    EquipmentRegistry,
    MonthlyCostRollup,
    ReplacementAnalysis,
)
from equipcost_forecast.models.schemas import NPVResult, RepairReplaceAnalysis


def compute_npv(
    cash_flows: list[float], discount_rate: float, initial_investment: float = 0.0
) -> float:
    """Compute Net Present Value of a series of cash flows.

    Args:
        cash_flows: List of annual cash flows (positive = cost/outflow).
        discount_rate: Annual discount rate (e.g. 0.08 for 8%).
        initial_investment: Upfront cost at time zero.

    Returns:
        NPV as a float (negative = net cost).
    """
    npv = -initial_investment
    for t, cf in enumerate(cash_flows, start=1):
        npv -= cf / (1 + discount_rate) ** t
    return round(npv, 2)


def compute_irr(
    cash_flows: list[float], initial_investment: float, tol: float = 1e-6
) -> float | None:
    """Compute Internal Rate of Return using bisection method.

    Args:
        cash_flows: List of annual net benefits (savings - costs).
        initial_investment: Upfront investment (positive).
        tol: Convergence tolerance.

    Returns:
        IRR as a float, or None if no solution found.
    """
    full_flows = [-initial_investment] + cash_flows

    low, high = -0.5, 2.0
    for _ in range(1000):
        mid = (low + high) / 2
        npv = sum(cf / (1 + mid) ** t for t, cf in enumerate(full_flows))
        if abs(npv) < tol:
            return round(mid, 6)
        if npv > 0:
            low = mid
        else:
            high = mid

    return None


class NPVAnalyzer:
    """NPV-based repair-vs-replace decision engine."""

    def __init__(self, discount_rate: float = 0.08):
        self.discount_rate = discount_rate

    def _get_annual_maintenance(self, equipment_id: int, session: Session) -> float:
        """Get average annual maintenance cost from last 24 months of rollups."""
        from datetime import timedelta

        cutoff = date.today() - timedelta(days=730)
        total = session.execute(
            select(func.sum(MonthlyCostRollup.total_cost)).where(
                MonthlyCostRollup.equipment_id == equipment_id,
                MonthlyCostRollup.month >= cutoff,
            )
        ).scalar()

        if not total:
            return 0.0

        month_count = (
            session.execute(
                select(func.count(MonthlyCostRollup.id)).where(
                    MonthlyCostRollup.equipment_id == equipment_id,
                    MonthlyCostRollup.month >= cutoff,
                )
            ).scalar()
            or 1
        )

        months = min(month_count, 24)
        return float(total) / months * 12

    def _get_class_avg_acquisition(
        self, equipment_class: str, session: Session
    ) -> float:
        """Get average acquisition cost for an equipment class."""
        avg = session.execute(
            select(func.avg(EquipmentRegistry.acquisition_cost)).where(
                EquipmentRegistry.equipment_class == equipment_class
            )
        ).scalar()
        return float(avg or 0)

    def npv_continue_operating(
        self, equipment_id: int, session: Session, horizon_years: int = 5
    ) -> NPVResult:
        """Project NPV of continuing to operate current equipment.

        Maintenance escalates at 8% annually from current level.
        """
        current_annual = self._get_annual_maintenance(equipment_id, session)

        cash_flows = [current_annual * (1.08**yr) for yr in range(horizon_years)]

        npv = compute_npv(cash_flows, self.discount_rate)

        return NPVResult(
            scenario="continue_operating",
            npv=npv,
            annual_cash_flows=[round(cf, 2) for cf in cash_flows],
            discount_rate=self.discount_rate,
            horizon_years=horizon_years,
        )

    def npv_replace_now(
        self,
        equipment_id: int,
        session: Session,
        replacement_cost: float,
        horizon_years: int = 5,
    ) -> NPVResult:
        """Project NPV of replacing equipment now.

        New equipment maintenance starts at 3% of replacement cost, escalating 2%/yr.
        Offset by salvage value of current equipment (remaining book value).
        """
        book_value = compute_book_value(equipment_id, session, method="straight_line")
        net_investment = replacement_cost - max(book_value, 0)

        new_annual = replacement_cost * 0.03
        cash_flows = [new_annual * (1.02**yr) for yr in range(horizon_years)]

        npv = compute_npv(
            cash_flows, self.discount_rate, initial_investment=net_investment
        )

        return NPVResult(
            scenario="replace_now",
            npv=npv,
            annual_cash_flows=[round(cf, 2) for cf in cash_flows],
            discount_rate=self.discount_rate,
            horizon_years=horizon_years,
        )

    def repair_vs_replace(
        self,
        equipment_id: int,
        session: Session,
        replacement_cost: float | None = None,
        horizon_years: int = 5,
    ) -> RepairReplaceAnalysis:
        """Run full repair-vs-replace analysis and persist to DB.

        Args:
            equipment_id: Equipment to analyze.
            session: Database session.
            replacement_cost: Cost of new equipment. Uses class average if None.
            horizon_years: NPV projection horizon.
        """
        eq = session.get(EquipmentRegistry, equipment_id)
        if not eq:
            raise ValueError(f"Equipment {equipment_id} not found")

        if replacement_cost is None:
            replacement_cost = self._get_class_avg_acquisition(
                eq.equipment_class, session
            )

        continue_result = self.npv_continue_operating(
            equipment_id, session, horizon_years
        )
        replace_result = self.npv_replace_now(
            equipment_id, session, replacement_cost, horizon_years
        )

        # Both NPVs are negative (costs). Less negative = cheaper.
        # Savings > 0 when replacing is cheaper than continuing.
        savings = replace_result.npv - continue_result.npv

        current_annual = (
            continue_result.annual_cash_flows[0]
            if continue_result.annual_cash_flows
            else 0.0
        )
        projected_annual = (
            continue_result.annual_cash_flows[-1]
            if continue_result.annual_cash_flows
            else 0.0
        )

        age_months = int((date.today() - eq.acquisition_date).days / 30.44)
        book_value = compute_book_value(equipment_id, session)

        if savings > replacement_cost * 0.10:
            action = "replace_immediately"
        elif savings > 0:
            action = "plan_replacement"
        else:
            action = "continue_operating"

        # Persist to replacement_analyses
        analysis_record = ReplacementAnalysis(
            equipment_id=equipment_id,
            analysis_date=date.today(),
            current_age_months=age_months,
            remaining_book_value=Decimal(str(round(book_value, 2))),
            annual_maintenance_cost_current=Decimal(str(round(current_annual, 2))),
            annual_maintenance_cost_projected=Decimal(str(round(projected_annual, 2))),
            replacement_cost_estimate=Decimal(str(round(replacement_cost, 2))),
            npv_continue_operating=Decimal(str(round(continue_result.npv, 2))),
            npv_replace_now=Decimal(str(round(replace_result.npv, 2))),
            npv_savings_if_replaced=Decimal(str(round(savings, 2))),
            recommended_action=action,
            discount_rate=Decimal(str(self.discount_rate)),
        )
        session.add(analysis_record)
        session.flush()

        return RepairReplaceAnalysis(
            equipment_id=equipment_id,
            asset_tag=eq.asset_tag,
            current_age_months=age_months,
            remaining_book_value=round(book_value, 2),
            annual_maintenance_current=round(current_annual, 2),
            annual_maintenance_projected=round(projected_annual, 2),
            replacement_cost=round(replacement_cost, 2),
            npv_continue=round(continue_result.npv, 2),
            npv_replace=round(replace_result.npv, 2),
            npv_savings=round(savings, 2),
            recommended_action=action,
            optimal_replacement_date=None,
        )
