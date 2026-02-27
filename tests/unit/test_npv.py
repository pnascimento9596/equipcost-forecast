from sqlalchemy import select

from equipcost_forecast.financial.npv_analyzer import (
    NPVAnalyzer,
    compute_irr,
    compute_npv,
)
from equipcost_forecast.models.orm import ReplacementAnalysis


class TestComputeNPV:
    def test_npv_zero_discount(self):
        result = compute_npv([1000, 1000, 1000], discount_rate=0.0)
        assert result == -3000.0

    def test_npv_with_discount(self):
        result = compute_npv([1000, 1000, 1000], discount_rate=0.10)
        # PV: 909.09 + 826.45 + 751.31 = 2486.85
        assert -2490 < result < -2480

    def test_npv_with_initial_investment(self):
        result = compute_npv([1000, 1000], discount_rate=0.05, initial_investment=5000)
        assert -6870 < result < -6850

    def test_npv_empty_flows(self):
        result = compute_npv([], discount_rate=0.08)
        assert result == 0.0

    def test_higher_discount_rate_less_negative(self):
        flows = [10000, 10000, 10000, 10000, 10000]
        npv_low = compute_npv(flows, discount_rate=0.05)
        npv_high = compute_npv(flows, discount_rate=0.15)
        assert npv_high > npv_low

    def test_known_manual_calc(self):
        """$5000/yr for 3 years at 8%: PV = 5000/1.08 + 5000/1.1664 + 5000/1.2597."""
        result = compute_npv([5000, 5000, 5000], discount_rate=0.08)
        expected = -(5000 / 1.08 + 5000 / 1.08**2 + 5000 / 1.08**3)
        assert abs(result - expected) < 1.0


class TestIRR:
    def test_irr_simple_case(self):
        irr = compute_irr([600, 600], initial_investment=1000)
        assert irr is not None
        assert 0.10 < irr < 0.15

    def test_irr_break_even(self):
        irr = compute_irr([1000], initial_investment=1000)
        assert irr is not None
        assert abs(irr) < 0.01


class TestNPVAnalyzer:
    def test_continue_operating_projects_escalation(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        analyzer = NPVAnalyzer(discount_rate=0.08)
        result = analyzer.npv_continue_operating(sample_equipment.id, session, 5)

        assert result.scenario == "continue_operating"
        assert result.npv < 0  # Cost is negative NPV
        assert len(result.annual_cash_flows) == 5
        # Maintenance should escalate year-over-year
        for i in range(1, len(result.annual_cash_flows)):
            assert result.annual_cash_flows[i] > result.annual_cash_flows[i - 1]

    def test_replace_now_includes_investment(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        analyzer = NPVAnalyzer(discount_rate=0.08)
        result = analyzer.npv_replace_now(
            sample_equipment.id, session, replacement_cost=1_500_000, horizon_years=5
        )

        assert result.scenario == "replace_now"
        assert result.npv < 0
        # New equipment costs should be lower than old
        assert result.annual_cash_flows[0] < 100_000

    def test_repair_vs_replace_old_high_cost_recommends_replace(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        """8-year-old CT scanner with escalating costs should recommend replacement
        when replacement cost is moderate (e.g. refurbished unit).
        """
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        analyzer = NPVAnalyzer(discount_rate=0.08)
        result = analyzer.repair_vs_replace(
            sample_equipment.id, session, replacement_cost=300_000
        )

        assert result.recommended_action in (
            "replace_immediately",
            "plan_replacement",
        )
        assert result.npv_savings > 0

    def test_repair_vs_replace_new_low_cost_continues(
        self, session, sample_new_equipment, flat_cost_work_orders
    ):
        """1-year-old pump with low costs should continue operating
        when replacement cost is significant relative to maintenance savings.
        """
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        CostAggregator(session).compute_monthly_rollups(sample_new_equipment.id)

        analyzer = NPVAnalyzer(discount_rate=0.08)
        result = analyzer.repair_vs_replace(
            sample_new_equipment.id, session, replacement_cost=50_000
        )

        assert result.recommended_action == "continue_operating"

    def test_repair_vs_replace_persists_to_db(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        analyzer = NPVAnalyzer()
        analyzer.repair_vs_replace(sample_equipment.id, session)

        record = session.execute(
            select(ReplacementAnalysis).where(
                ReplacementAnalysis.equipment_id == sample_equipment.id
            )
        ).scalar_one()
        assert record is not None
        assert record.recommended_action in (
            "replace_immediately",
            "plan_replacement",
            "continue_operating",
        )
