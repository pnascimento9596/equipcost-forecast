from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import (
    EquipmentRegistry,
    MonthlyCostRollup,
)
from equipcost_forecast.models.schemas import TCOComparison, TCOReport


class TCOCalculator:
    """Total Cost of Ownership calculator with downtime costing."""

    def __init__(self, session: Session, downtime_hourly_rate: float = 500.0):
        self.session = session
        self.downtime_hourly_rate = downtime_hourly_rate

    def calculate_tco(
        self, equipment_id: int, as_of_date: date | None = None
    ) -> TCOReport:
        """Calculate full TCO including acquisition, maintenance, contracts, and downtime.

        Args:
            equipment_id: Equipment to analyze.
            as_of_date: Calculate TCO as of this date. Defaults to today.
        """
        if as_of_date is None:
            as_of_date = date.today()

        eq = self.session.get(EquipmentRegistry, equipment_id)
        if not eq:
            raise ValueError(f"Equipment {equipment_id} not found")

        rollup_filter = [MonthlyCostRollup.equipment_id == equipment_id]
        if as_of_date != date.today():
            rollup_filter.append(MonthlyCostRollup.month <= as_of_date)

        totals = self.session.execute(
            select(
                func.sum(MonthlyCostRollup.pm_cost).label("pm"),
                func.sum(MonthlyCostRollup.corrective_cost).label("corrective"),
                func.sum(MonthlyCostRollup.parts_cost).label("parts"),
                func.sum(MonthlyCostRollup.contract_cost_allocated).label("contract"),
                func.sum(MonthlyCostRollup.total_cost).label("total_maint"),
                func.sum(MonthlyCostRollup.downtime_hours).label("downtime"),
            ).where(*rollup_filter)
        ).one()

        cumulative_maint = float(totals.total_maint or 0)
        cumulative_contracts = float(totals.contract or 0)
        total_downtime_hours = float(totals.downtime or 0)
        downtime_cost = total_downtime_hours * self.downtime_hourly_rate

        acquisition = float(eq.acquisition_cost)
        total_tco = acquisition + cumulative_maint + downtime_cost

        age_years = (as_of_date - eq.acquisition_date).days / 365.25
        annualized = total_tco / max(age_years, 0.5)

        maint_ratio = cumulative_maint / acquisition if acquisition > 0 else 0.0

        return TCOReport(
            equipment_id=equipment_id,
            asset_tag=eq.asset_tag,
            equipment_class=eq.equipment_class,
            acquisition_cost=round(acquisition, 2),
            cumulative_maintenance=round(cumulative_maint, 2),
            cumulative_contracts=round(cumulative_contracts, 2),
            estimated_downtime_cost=round(downtime_cost, 2),
            total_tco=round(total_tco, 2),
            age_years=round(age_years, 1),
            annualized_tco=round(annualized, 2),
            maintenance_to_acquisition_ratio=round(maint_ratio, 4),
        )

    def compare_tco(self, equipment_ids: list[int]) -> TCOComparison:
        """Compare TCO across multiple equipment items, normalized by age."""
        if len(equipment_ids) < 2:
            raise ValueError("Need at least 2 equipment IDs for comparison")

        reports = [self.calculate_tco(eid) for eid in equipment_ids]
        avg_annualized = sum(r.annualized_tco for r in reports) / len(reports)

        best = min(reports, key=lambda r: r.annualized_tco)
        worst = max(reports, key=lambda r: r.annualized_tco)

        return TCOComparison(
            reports=reports,
            best_performer=best.asset_tag,
            worst_performer=worst.asset_tag,
            fleet_avg_annualized_tco=round(avg_annualized, 2),
        )
