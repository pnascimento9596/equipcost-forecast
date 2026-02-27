from equipcost_forecast.financial.replacement_optimizer import FleetReplacementOptimizer
from equipcost_forecast.forecasting.cost_aggregator import CostAggregator
from equipcost_forecast.models.orm import EquipmentRegistry


class TestReplacementOptimizer:
    def test_rank_replacement_priorities(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        optimizer = FleetReplacementOptimizer(session, annual_capital_budget=2_000_000)
        priorities = optimizer.rank_replacement_priorities()

        assert len(priorities) >= 1
        assert priorities[0].rank == 1
        assert priorities[0].asset_tag == sample_equipment.asset_tag
        assert priorities[0].equipment_class == "ct_scanner"
        assert priorities[0].age_months > 0

    def test_priorities_sorted_by_savings(
        self,
        session,
        sample_equipment,
        sample_new_equipment,
        work_orders_for_equipment,
        flat_cost_work_orders,
    ):
        agg = CostAggregator(session)
        agg.compute_monthly_rollups(sample_equipment.id)
        agg.compute_monthly_rollups(sample_new_equipment.id)

        optimizer = FleetReplacementOptimizer(session, annual_capital_budget=2_000_000)
        priorities = optimizer.rank_replacement_priorities()

        assert len(priorities) >= 2
        for i in range(len(priorities) - 1):
            assert priorities[i].npv_savings >= priorities[i + 1].npv_savings

    def test_budget_flagging(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        optimizer = FleetReplacementOptimizer(
            session, annual_capital_budget=100  # Very small budget
        )
        priorities = optimizer.rank_replacement_priorities()

        has_over_budget = any(
            p for p in priorities if p.npv_savings > 0 and not p.within_budget
        )
        # With $100 budget, most replacements won't fit
        if any(p.npv_savings > 0 for p in priorities):
            assert has_over_budget

    def test_facility_filter(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        optimizer = FleetReplacementOptimizer(session, annual_capital_budget=2_000_000)
        priorities = optimizer.rank_replacement_priorities(facility_id="FAC-001")

        for p in priorities:
            eq = session.get(EquipmentRegistry, p.equipment_id)
            assert eq.facility_id == "FAC-001"

    def test_optimal_replacement_schedule(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        optimizer = FleetReplacementOptimizer(session, annual_capital_budget=2_000_000)
        schedule = optimizer.optimal_replacement_schedule(horizon_years=3)

        assert schedule.horizon_years == 3
        assert schedule.annual_budget == 2_000_000
        assert len(schedule.schedule) == 3
        assert schedule.total_spend >= 0
        assert schedule.total_projected_savings >= 0

    def test_schedule_respects_budget(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        optimizer = FleetReplacementOptimizer(session, annual_capital_budget=500)
        schedule = optimizer.optimal_replacement_schedule(horizon_years=2)

        for year in schedule.schedule:
            assert year.year_spend <= 500

    def test_empty_fleet_returns_empty(self, session):
        optimizer = FleetReplacementOptimizer(session, annual_capital_budget=2_000_000)
        priorities = optimizer.rank_replacement_priorities(facility_id="NONEXISTENT")
        assert priorities == []
