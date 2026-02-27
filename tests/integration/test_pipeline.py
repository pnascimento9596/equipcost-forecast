from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from equipcost_forecast.forecasting.cost_aggregator import CostAggregator
from equipcost_forecast.forecasting.time_series import CostForecaster
from equipcost_forecast.models.orm import (
    EquipmentRegistry,
    ReplacementAnalysis,
    WorkOrder,
)


class TestFullPipeline:
    def test_load_aggregate_forecast(
        self, session, sample_equipment, work_orders_for_equipment, sample_contract
    ):
        """Full pipeline: load -> aggregate -> forecast."""
        aggregator = CostAggregator(session)
        count = aggregator.compute_monthly_rollups(sample_equipment.id)
        assert count > 0

        df = aggregator.get_cost_history(sample_equipment.id)
        assert not df.empty
        assert len(df) >= 24

        forecaster = CostForecaster(min_history_months=12)
        result = forecaster.forecast_equipment(
            sample_equipment.id, session, horizon=12, method="auto"
        )

        assert len(result.predictions) == 12
        assert result.metrics.mae >= 0
        assert result.metrics.rmse >= 0

    def test_aging_equipment_escalating_costs(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        """Aging CT scanner should show escalating costs over time."""
        aggregator = CostAggregator(session)
        aggregator.compute_monthly_rollups(sample_equipment.id)
        df = aggregator.get_cost_history(sample_equipment.id)

        mid = len(df) // 2
        first_half_avg = df.iloc[:mid]["total_cost"].mean()
        second_half_avg = df.iloc[mid:]["total_cost"].mean()
        assert second_half_avg > first_half_avg

    def test_new_equipment_flat_costs(
        self, session, sample_new_equipment, flat_cost_work_orders
    ):
        """New equipment should have relatively flat costs."""
        aggregator = CostAggregator(session)
        aggregator.compute_monthly_rollups(sample_new_equipment.id)
        df = aggregator.get_cost_history(sample_new_equipment.id)

        if len(df) >= 4:
            import numpy as np

            costs = df["total_cost"].values
            cv = np.std(costs) / max(np.mean(costs), 1)
            assert cv < 1.0

    def test_full_pipeline_to_replacement(
        self, session, sample_equipment, work_orders_for_equipment, sample_contract
    ):
        """Full: load -> aggregate -> forecast -> TCO -> repair-vs-replace."""
        from equipcost_forecast.financial.npv_analyzer import NPVAnalyzer
        from equipcost_forecast.financial.tco_calculator import TCOCalculator

        # Aggregate
        aggregator = CostAggregator(session)
        aggregator.compute_monthly_rollups(sample_equipment.id)

        # Forecast
        forecaster = CostForecaster(min_history_months=12)
        forecaster.forecast_equipment(sample_equipment.id, session, 12)

        # TCO
        tco_calc = TCOCalculator(session)
        report = tco_calc.calculate_tco(sample_equipment.id)
        assert report.total_tco > 0

        # Repair-vs-replace
        analyzer = NPVAnalyzer(discount_rate=0.08)
        result = analyzer.repair_vs_replace(sample_equipment.id, session)
        assert result.recommended_action in (
            "replace_immediately",
            "plan_replacement",
            "continue_operating",
        )

        # Verify DB persistence
        db_record = session.execute(
            select(ReplacementAnalysis).where(
                ReplacementAnalysis.equipment_id == sample_equipment.id
            )
        ).scalar_one()
        assert db_record is not None


class TestFleetReplacementDetection:
    def test_past_optimal_items_flagged(self, session):
        """Create 15 clearly past-optimal items and verify they're flagged."""
        import uuid

        from equipcost_forecast.financial.npv_analyzer import NPVAnalyzer
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        run_id = uuid.uuid4().hex[:6]

        # Create 15 aging, high-cost equipment items
        flagged_ids = []
        for i in range(15):
            eq = EquipmentRegistry(
                asset_tag=f"EQ-OLD-{run_id}-{i:04d}",
                serial_number=f"SN-OLD-{run_id}-{i:04d}",
                equipment_class="ct_scanner",
                manufacturer="GE Healthcare",
                model_name="Old Scanner",
                facility_id="FAC-001",
                department="Radiology",
                acquisition_date=date(2011, 1, 1),
                acquisition_cost=Decimal("1000000.00"),
                expected_useful_life_months=120,
                status="active",
            )
            session.add(eq)
            session.flush()
            flagged_ids.append(eq.id)

            # Generate expensive repair history (>40% of replacement annually)
            wo_counter = 0
            for month in range(120):
                if month % 2 == 0:
                    wo_date = date(2016, 1, 1) + timedelta(days=30 * month)
                    if wo_date > date(2026, 2, 26):
                        break
                    wo_counter += 1
                    wo = WorkOrder(
                        equipment_id=eq.id,
                        work_order_number=f"WO-{run_id}-{i:03d}-{wo_counter:04d}",
                        wo_type="corrective_repair",
                        priority="routine",
                        opened_date=wo_date,
                        completed_date=wo_date + timedelta(days=2),
                        description="Expensive corrective",
                        labor_hours=Decimal("16.00"),
                        labor_cost=Decimal("8000.00"),
                        parts_cost=Decimal("15000.00"),
                        vendor_service_cost=Decimal("5000.00"),
                        total_cost=Decimal("28000.00"),
                        downtime_hours=Decimal("48.00"),
                        technician_type="oem",
                    )
                    session.add(wo)
            session.flush()

        # Aggregate costs
        aggregator = CostAggregator(session)
        for eid in flagged_ids:
            aggregator.compute_monthly_rollups(eid)

        # Run repair-vs-replace on all
        analyzer = NPVAnalyzer(discount_rate=0.08)
        replace_count = 0
        for eid in flagged_ids:
            try:
                result = analyzer.repair_vs_replace(eid, session)
                if result.recommended_action in (
                    "replace_immediately",
                    "plan_replacement",
                ):
                    replace_count += 1
            except ValueError:
                pass

        # At least 10 of 15 should be flagged
        assert (
            replace_count >= 10
        ), f"Expected >=10 flagged for replacement, got {replace_count}"
