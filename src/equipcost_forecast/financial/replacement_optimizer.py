from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from equipcost_forecast.financial.npv_analyzer import NPVAnalyzer
from equipcost_forecast.models.orm import EquipmentRegistry
from equipcost_forecast.models.schemas import (
    ReplacementPriority,
    ReplacementSchedule,
    ReplacementScheduleYear,
)


def _fiscal_year_for_date(d: date) -> int:
    return d.year + 1 if d.month >= 10 else d.year


class FleetReplacementOptimizer:
    """Budget-constrained fleet replacement optimizer."""

    def __init__(
        self,
        session: Session,
        annual_capital_budget: float,
        discount_rate: float = 0.08,
    ):
        self.session = session
        self.annual_capital_budget = annual_capital_budget
        self.analyzer = NPVAnalyzer(discount_rate)

    def rank_replacement_priorities(
        self, facility_id: str | None = None
    ) -> list[ReplacementPriority]:
        """Run repair-vs-replace for all active equipment, ranked by savings.

        Args:
            facility_id: Filter to a single facility. None for all.

        Returns:
            Ranked list of replacement priorities with budget flagging.
        """
        stmt = select(EquipmentRegistry).where(EquipmentRegistry.status == "active")
        if facility_id:
            stmt = stmt.where(EquipmentRegistry.facility_id == facility_id)

        equipment = list(self.session.scalars(stmt).all())

        priorities = []
        for eq in equipment:
            try:
                result = self.analyzer.repair_vs_replace(eq.id, self.session)
            except (ValueError, ZeroDivisionError):
                continue

            age_months = int((date.today() - eq.acquisition_date).days / 30.44)

            priorities.append(
                ReplacementPriority(
                    rank=0,
                    equipment_id=eq.id,
                    asset_tag=eq.asset_tag,
                    equipment_class=eq.equipment_class,
                    age_months=age_months,
                    npv_savings=result.npv_savings,
                    recommended_action=result.recommended_action,
                    replacement_cost=result.replacement_cost,
                    within_budget=False,
                )
            )

        # Sort by NPV savings descending, then by age descending
        priorities.sort(key=lambda p: (-p.npv_savings, -p.age_months))

        # Assign ranks and flag within budget
        cumulative = 0.0
        for i, p in enumerate(priorities):
            p.rank = i + 1
            if p.npv_savings > 0:
                cumulative += p.replacement_cost
                p.within_budget = cumulative <= self.annual_capital_budget

        return priorities

    def optimal_replacement_schedule(
        self, facility_id: str | None = None, horizon_years: int = 5
    ) -> ReplacementSchedule:
        """Build a multi-year replacement schedule using greedy allocation.

        Each year, replace highest-NPV-savings items that fit within budget.

        Args:
            facility_id: Filter to a single facility.
            horizon_years: Number of fiscal years to plan.
        """
        all_priorities = self.rank_replacement_priorities(facility_id)

        # Only consider items recommended for replacement
        candidates = [
            p
            for p in all_priorities
            if p.recommended_action in ("replace_immediately", "plan_replacement")
        ]

        scheduled_ids: set[int] = set()
        current_fy = _fiscal_year_for_date(date.today())
        yearly_schedule = []
        total_spend = 0.0
        total_savings = 0.0

        for year_offset in range(horizon_years):
            fy = current_fy + year_offset
            year_budget = self.annual_capital_budget
            year_replacements = []
            year_spend = 0.0
            year_savings = 0.0

            for candidate in candidates:
                if candidate.equipment_id in scheduled_ids:
                    continue
                if year_spend + candidate.replacement_cost <= year_budget:
                    year_spend += candidate.replacement_cost
                    year_savings += candidate.npv_savings
                    scheduled_ids.add(candidate.equipment_id)
                    year_replacements.append(candidate)

            yearly_schedule.append(
                ReplacementScheduleYear(
                    fiscal_year=fy,
                    replacements=year_replacements,
                    year_spend=round(year_spend, 2),
                    year_savings=round(year_savings, 2),
                )
            )
            total_spend += year_spend
            total_savings += year_savings

        return ReplacementSchedule(
            facility_id=facility_id,
            annual_budget=self.annual_capital_budget,
            horizon_years=horizon_years,
            schedule=yearly_schedule,
            total_spend=round(total_spend, 2),
            total_projected_savings=round(total_savings, 2),
        )
