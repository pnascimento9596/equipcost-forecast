from equipcost_forecast.forecasting.cost_aggregator import CostAggregator


class TestCostAggregator:
    def test_compute_monthly_rollups_single_equipment(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        aggregator = CostAggregator(session)
        count = aggregator.compute_monthly_rollups(sample_equipment.id)

        assert count > 0

    def test_rollup_sums_match_work_orders(
        self, session, sample_equipment, work_orders_for_equipment, sample_contract
    ):
        aggregator = CostAggregator(session)
        aggregator.compute_monthly_rollups(sample_equipment.id)
        df = aggregator.get_cost_history(sample_equipment.id)

        assert not df.empty
        # Total cost should include PM + corrective + contract
        assert df["total_cost"].sum() > 0
        # PM and corrective should both be present
        assert df["pm_cost"].sum() > 0
        assert df["corrective_cost"].sum() > 0

    def test_cost_history_returns_dataframe(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        aggregator = CostAggregator(session)
        aggregator.compute_monthly_rollups(sample_equipment.id)
        df = aggregator.get_cost_history(sample_equipment.id)

        assert "total_cost" in df.columns
        assert "pm_cost" in df.columns
        assert "corrective_cost" in df.columns
        assert df.index.name == "month"

    def test_empty_equipment_returns_empty_df(self, session, sample_equipment):
        aggregator = CostAggregator(session)
        df = aggregator.get_cost_history(sample_equipment.id)

        assert df.empty

    def test_contract_allocation(
        self, session, sample_equipment, work_orders_for_equipment, sample_contract
    ):
        aggregator = CostAggregator(session)
        aggregator.compute_monthly_rollups(sample_equipment.id)
        df = aggregator.get_cost_history(sample_equipment.id)

        # Contract months should have allocated cost
        contract_months = df[df["contract_cost"] > 0]
        assert len(contract_months) > 0
        # Each month should get ~150000/12 = 12500
        avg_contract = contract_months["contract_cost"].mean()
        assert 10000 < avg_contract < 15000

    def test_compute_all_equipment(
        self,
        session,
        sample_equipment,
        sample_new_equipment,
        work_orders_for_equipment,
        flat_cost_work_orders,
    ):
        aggregator = CostAggregator(session)
        count = aggregator.compute_monthly_rollups()  # No equipment_id = all
        assert count > 0

    def test_get_fleet_cost_summary(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        aggregator = CostAggregator(session)
        aggregator.compute_monthly_rollups(sample_equipment.id)
        summary = aggregator.get_fleet_cost_summary()

        assert summary.total_equipment >= 1
        assert summary.total_annual_cost >= 0
        assert isinstance(summary.top_cost_classes, list)

    def test_get_fleet_cost_summary_with_facility(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        aggregator = CostAggregator(session)
        aggregator.compute_monthly_rollups(sample_equipment.id)
        summary = aggregator.get_fleet_cost_summary(facility_id="FAC-001")

        assert summary.facility_id == "FAC-001"
        assert summary.total_equipment >= 1

    def test_get_fleet_cost_summary_empty_facility(self, session):
        aggregator = CostAggregator(session)
        summary = aggregator.get_fleet_cost_summary(facility_id="NONEXISTENT")

        assert summary.total_equipment == 0
