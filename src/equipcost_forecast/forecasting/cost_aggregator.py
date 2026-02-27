from datetime import date
from decimal import Decimal

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import (
    EquipmentRegistry,
    MonthlyCostRollup,
    ServiceContract,
    WorkOrder,
)
from equipcost_forecast.models.schemas import FleetCostSummary


class CostAggregator:
    """Aggregates work order and contract costs into monthly rollups."""

    def __init__(self, session: Session):
        self.session = session

    def compute_monthly_rollups(self, equipment_id: int | None = None) -> int:
        """Compute monthly cost rollups from work orders and contracts.

        Args:
            equipment_id: If provided, compute for a single asset. Otherwise all.

        Returns:
            Number of rollup records created/updated.
        """
        if equipment_id is not None:
            eq_ids = [equipment_id]
        else:
            eq_ids = [
                r[0] for r in self.session.execute(select(EquipmentRegistry.id)).all()
            ]

        record_count = 0

        for eid in eq_ids:
            # Get work orders grouped by month
            wo_rows = self.session.execute(
                select(
                    func.strftime("%Y-%m-01", WorkOrder.opened_date).label("month"),
                    WorkOrder.wo_type,
                    func.sum(WorkOrder.labor_cost).label("labor"),
                    func.sum(WorkOrder.parts_cost).label("parts"),
                    func.sum(WorkOrder.vendor_service_cost).label("vendor"),
                    func.sum(WorkOrder.total_cost).label("total"),
                    func.sum(WorkOrder.downtime_hours).label("downtime"),
                    func.count(WorkOrder.id).label("wo_count"),
                )
                .where(WorkOrder.equipment_id == eid)
                .group_by("month", WorkOrder.wo_type)
            ).all()

            # Organize by month
            monthly: dict[str, dict] = {}
            for row in wo_rows:
                month_str = row.month
                if month_str not in monthly:
                    monthly[month_str] = {
                        "pm_cost": Decimal("0"),
                        "corrective_cost": Decimal("0"),
                        "parts_cost": Decimal("0"),
                        "downtime_hours": Decimal("0"),
                        "work_order_count": 0,
                    }
                m = monthly[month_str]
                cost = Decimal(str(row.total or 0))
                parts = Decimal(str(row.parts or 0))
                downtime = Decimal(str(row.downtime or 0))
                count = row.wo_count or 0

                if row.wo_type == "corrective_repair":
                    m["corrective_cost"] += cost
                else:
                    m["pm_cost"] += cost
                m["parts_cost"] += parts
                m["downtime_hours"] += downtime
                m["work_order_count"] += count

            # Get contract cost allocation per month
            contracts = self.session.scalars(
                select(ServiceContract).where(ServiceContract.equipment_id == eid)
            ).all()

            contract_monthly: dict[str, Decimal] = {}
            for c in contracts:
                if not c.annual_cost or not c.start_date or not c.end_date:
                    continue
                monthly_alloc = Decimal(str(c.annual_cost)) / 12
                current = date(c.start_date.year, c.start_date.month, 1)
                end = c.end_date
                while current <= end:
                    key = current.strftime("%Y-%m-01")
                    contract_monthly[key] = (
                        contract_monthly.get(key, Decimal("0")) + monthly_alloc
                    )
                    # Advance month
                    if current.month == 12:
                        current = date(current.year + 1, 1, 1)
                    else:
                        current = date(current.year, current.month + 1, 1)

            # Merge all months
            all_months = set(monthly.keys()) | set(contract_monthly.keys())

            # Delete existing rollups for this equipment
            self.session.execute(
                delete(MonthlyCostRollup).where(MonthlyCostRollup.equipment_id == eid)
            )

            for month_str in sorted(all_months):
                m = monthly.get(
                    month_str,
                    {
                        "pm_cost": Decimal("0"),
                        "corrective_cost": Decimal("0"),
                        "parts_cost": Decimal("0"),
                        "downtime_hours": Decimal("0"),
                        "work_order_count": 0,
                    },
                )
                contract_alloc = contract_monthly.get(month_str, Decimal("0"))
                total = m["pm_cost"] + m["corrective_cost"] + contract_alloc

                month_date = date.fromisoformat(month_str)
                rollup = MonthlyCostRollup(
                    equipment_id=eid,
                    month=month_date,
                    pm_cost=m["pm_cost"],
                    corrective_cost=m["corrective_cost"],
                    parts_cost=m["parts_cost"],
                    contract_cost_allocated=contract_alloc,
                    downtime_hours=m["downtime_hours"],
                    work_order_count=m["work_order_count"],
                    total_cost=total,
                )
                self.session.add(rollup)
                record_count += 1

        self.session.flush()
        return record_count

    def get_cost_history(self, equipment_id: int) -> pd.DataFrame:
        """Return time-indexed DataFrame of monthly costs for an equipment item."""
        rows = (
            self.session.execute(
                select(MonthlyCostRollup)
                .where(MonthlyCostRollup.equipment_id == equipment_id)
                .order_by(MonthlyCostRollup.month)
            )
            .scalars()
            .all()
        )

        if not rows:
            return pd.DataFrame()

        data = []
        for r in rows:
            data.append(
                {
                    "month": r.month,
                    "pm_cost": float(r.pm_cost or 0),
                    "corrective_cost": float(r.corrective_cost or 0),
                    "parts_cost": float(r.parts_cost or 0),
                    "contract_cost": float(r.contract_cost_allocated or 0),
                    "downtime_hours": float(r.downtime_hours or 0),
                    "work_order_count": r.work_order_count or 0,
                    "total_cost": float(r.total_cost or 0),
                }
            )

        df = pd.DataFrame(data)
        df["month"] = pd.to_datetime(df["month"])
        df = df.set_index("month")
        return df

    def get_fleet_cost_summary(
        self, facility_id: str | None = None
    ) -> FleetCostSummary:
        """Compute fleet-level cost summary, optionally filtered by facility."""
        eq_query = select(EquipmentRegistry)
        if facility_id:
            eq_query = eq_query.where(EquipmentRegistry.facility_id == facility_id)
        equipment = list(self.session.scalars(eq_query).all())
        eq_ids = [e.id for e in equipment]

        if not eq_ids:
            return FleetCostSummary(
                facility_id=facility_id,
                total_equipment=0,
                total_annual_cost=Decimal("0"),
                avg_cost_per_asset=Decimal("0"),
                top_cost_classes=[],
                aging_assets_count=0,
            )

        # Annual cost from last 12 months of rollups
        twelve_months_ago = date(date.today().year - 1, date.today().month, 1)
        annual_cost_row = (
            self.session.execute(
                select(func.sum(MonthlyCostRollup.total_cost)).where(
                    MonthlyCostRollup.equipment_id.in_(eq_ids),
                    MonthlyCostRollup.month >= twelve_months_ago,
                )
            ).scalar()
            or 0
        )

        total_annual = Decimal(str(annual_cost_row))
        avg_cost = total_annual / len(eq_ids) if eq_ids else Decimal("0")

        # Top cost classes
        class_costs = self.session.execute(
            select(
                EquipmentRegistry.equipment_class,
                func.sum(MonthlyCostRollup.total_cost).label("cost"),
            )
            .join(
                MonthlyCostRollup,
                MonthlyCostRollup.equipment_id == EquipmentRegistry.id,
            )
            .where(
                EquipmentRegistry.id.in_(eq_ids),
                MonthlyCostRollup.month >= twelve_months_ago,
            )
            .group_by(EquipmentRegistry.equipment_class)
            .order_by(func.sum(MonthlyCostRollup.total_cost).desc())
            .limit(5)
        ).all()
        top_classes = [
            {"class": row[0], "annual_cost": float(row[1])} for row in class_costs
        ]

        # Aging assets (past useful life)
        aging = 0
        for e in equipment:
            if e.expected_useful_life_months:
                age_months = (date.today() - e.acquisition_date).days / 30.44
                if age_months > e.expected_useful_life_months:
                    aging += 1

        return FleetCostSummary(
            facility_id=facility_id,
            total_equipment=len(eq_ids),
            total_annual_cost=total_annual,
            avg_cost_per_asset=avg_cost,
            top_cost_classes=top_classes,
            aging_assets_count=aging,
        )
