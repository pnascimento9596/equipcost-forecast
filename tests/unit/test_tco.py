import pytest

from equipcost_forecast.forecasting.bathtub_curve import FailureRateModeler
from equipcost_forecast.forecasting.maintenance_predictor import predict_next_failure


class TestBathtubCurve:
    def test_fit_bathtub_returns_params(self):
        modeler = FailureRateModeler()

        data = []
        for m in range(1, 13):
            data.append({"age_months": m, "annual_repair_count": 1.5 - 0.08 * m})
        for m in range(13, 85):
            data.append({"age_months": m, "annual_repair_count": 0.5 + 0.01 * (m - 13)})
        for m in range(85, 181):
            data.append({"age_months": m, "annual_repair_count": 1.0 + 0.02 * (m - 85)})

        params = modeler.fit_bathtub_curve("ct_scanner", data)

        assert params.equipment_class == "ct_scanner"
        assert params.early_life_shape < 1.0
        assert params.wearout_shape > 1.0

    def test_predict_annual_repairs(self):
        modeler = FailureRateModeler()
        data = []
        for m in range(1, 13):
            data.append({"age_months": m, "annual_repair_count": 1.2})
        for m in range(13, 85):
            data.append({"age_months": m, "annual_repair_count": 0.5})
        for m in range(85, 150):
            data.append({"age_months": m, "annual_repair_count": 1.0 + 0.03 * (m - 85)})

        params = modeler.fit_bathtub_curve("ventilator", data)

        rate_young = modeler.predict_annual_repairs(36, params)
        rate_old = modeler.predict_annual_repairs(120, params)
        assert rate_old > rate_young

    def test_empty_data_raises(self):
        modeler = FailureRateModeler()
        with pytest.raises(ValueError):
            modeler.fit_bathtub_curve("mri", [])


class TestRemainingLife:
    def test_estimate_with_data(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        modeler = FailureRateModeler()
        estimate = modeler.estimate_remaining_useful_life(sample_equipment.id, session)

        assert estimate.equipment_id == sample_equipment.id
        assert estimate.current_age_months > 0
        assert estimate.estimated_remaining_months >= 0
        assert 0 < estimate.confidence <= 1.0
        assert estimate.method in (
            "bathtub_curve",
            "bathtub_curve_no_threshold",
            "useful_life_default",
        )

    def test_estimate_not_found_raises(self, session):
        modeler = FailureRateModeler()
        with pytest.raises(ValueError, match="not found"):
            modeler.estimate_remaining_useful_life(99999, session)

    def test_estimate_sparse_data_uses_default(self, session, sample_new_equipment):
        modeler = FailureRateModeler()
        estimate = modeler.estimate_remaining_useful_life(
            sample_new_equipment.id, session
        )

        assert estimate.method == "useful_life_default"
        assert estimate.confidence == 0.3


class TestMTBF:
    def test_mtbf_prediction(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        prediction = predict_next_failure(sample_equipment.id, session)

        assert prediction.equipment_id == sample_equipment.id
        assert prediction.mtbf_days > 0
        assert 0 <= prediction.probability_within_90_days <= 1.0
        assert float(prediction.estimated_repair_cost) > 0

    def test_insufficient_repairs_raises(self, session, sample_new_equipment):
        with pytest.raises(ValueError, match="insufficient"):
            predict_next_failure(sample_new_equipment.id, session)


class TestTCOCalculator:
    def test_tco_includes_downtime_cost(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        from equipcost_forecast.financial.tco_calculator import TCOCalculator
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        CostAggregator(session).compute_monthly_rollups(sample_equipment.id)

        calc = TCOCalculator(session, downtime_hourly_rate=500)
        report = calc.calculate_tco(sample_equipment.id)

        assert report.estimated_downtime_cost > 0
        assert report.total_tco > report.acquisition_cost
        assert report.annualized_tco > 0
        assert report.maintenance_to_acquisition_ratio > 0

    def test_tco_compare(
        self,
        session,
        sample_equipment,
        sample_new_equipment,
        work_orders_for_equipment,
        flat_cost_work_orders,
    ):
        from equipcost_forecast.financial.tco_calculator import TCOCalculator
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        agg = CostAggregator(session)
        agg.compute_monthly_rollups(sample_equipment.id)
        agg.compute_monthly_rollups(sample_new_equipment.id)

        calc = TCOCalculator(session)
        comparison = calc.compare_tco([sample_equipment.id, sample_new_equipment.id])

        assert len(comparison.reports) == 2
        assert comparison.best_performer in (
            sample_equipment.asset_tag,
            sample_new_equipment.asset_tag,
        )
        assert comparison.fleet_avg_annualized_tco > 0
