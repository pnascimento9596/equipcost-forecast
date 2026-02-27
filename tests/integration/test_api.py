from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from equipcost_forecast.api.dependencies import get_db
from equipcost_forecast.api.main import app
from equipcost_forecast.forecasting.cost_aggregator import CostAggregator
from equipcost_forecast.models.orm import (
    Base,
    EquipmentRegistry,
    ServiceContract,
    WorkOrder,
)

_test_engine = create_engine(
    "sqlite:///:memory:",
    echo=False,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
Base.metadata.create_all(_test_engine)
_TestSessionLocal = sessionmaker(bind=_test_engine, expire_on_commit=False)


def _seed():
    session = _TestSessionLocal()

    eq1 = EquipmentRegistry(
        asset_tag="EQ-API-0001",
        serial_number="SN-API-001",
        equipment_class="ct_scanner",
        manufacturer="GE Healthcare",
        model_name="Revolution CT",
        facility_id="FAC-001",
        department="Radiology",
        acquisition_date=date(2018, 3, 15),
        acquisition_cost=Decimal("1500000.00"),
        installation_date=date(2018, 4, 1),
        warranty_expiration=date(2021, 3, 15),
        expected_useful_life_months=120,
        status="active",
    )
    eq2 = EquipmentRegistry(
        asset_tag="EQ-API-0002",
        serial_number="SN-API-002",
        equipment_class="infusion_pump",
        manufacturer="Mindray",
        model_name="BeneFusion SP5",
        facility_id="FAC-002",
        department="ICU",
        acquisition_date=date(2025, 1, 1),
        acquisition_cost=Decimal("5000.00"),
        expected_useful_life_months=84,
        status="active",
    )
    session.add_all([eq1, eq2])
    session.flush()

    for i in range(48):
        wo_date = date(2018, 6, 1) + timedelta(days=30 * i)
        if wo_date > date(2026, 2, 26):
            break
        session.add(
            WorkOrder(
                equipment_id=eq1.id,
                work_order_number=f"WO-API-{i:05d}",
                wo_type="corrective_repair" if i % 3 == 0 else "preventive_maintenance",
                priority="routine",
                opened_date=wo_date,
                completed_date=wo_date + timedelta(days=1),
                description="Test work order",
                labor_hours=Decimal("4.00"),
                labor_cost=Decimal("400.00"),
                parts_cost=Decimal("200.00"),
                vendor_service_cost=Decimal("0.00"),
                total_cost=Decimal("1200.00") if i % 3 != 0 else Decimal("5000.00"),
                downtime_hours=Decimal("4.00"),
                technician_type="in_house",
            )
        )

    session.add(
        ServiceContract(
            equipment_id=eq1.id,
            contract_type="full_service",
            provider="GE Healthcare",
            annual_cost=Decimal("120000.00"),
            start_date=date(2021, 4, 1),
            end_date=date(2026, 3, 31),
            includes_parts=True,
            includes_labor=True,
            includes_pm=True,
            response_time_hours=4,
        )
    )
    session.flush()

    agg = CostAggregator(session)
    agg.compute_monthly_rollups(eq1.id)

    session.commit()
    session.close()


_seed()


def _override_get_db():
    session = _TestSessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


app.dependency_overrides[get_db] = _override_get_db


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


class TestEquipmentRoutes:
    def test_list_equipment(self, client):
        resp = client.get("/api/v1/equipment/")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 2
        assert len(data["items"]) >= 2
        assert "pages" in data

    def test_list_with_filters(self, client):
        resp = client.get("/api/v1/equipment/?facility_id=FAC-001")
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["facility_id"] == "FAC-001"

    def test_list_pagination(self, client):
        resp = client.get("/api/v1/equipment/?page=1&page_size=1")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["page"] == 1

    def test_get_equipment_detail(self, client):
        resp = client.get("/api/v1/equipment/EQ-API-0001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_tag"] == "EQ-API-0001"
        assert data["manufacturer"] == "GE Healthcare"
        assert "active_contracts" in data
        assert "cost_summary" in data
        assert data["age_years"] > 0

    def test_get_nonexistent_equipment(self, client):
        resp = client.get("/api/v1/equipment/DOES-NOT-EXIST")
        assert resp.status_code == 404

    def test_get_work_orders(self, client):
        resp = client.get("/api/v1/equipment/EQ-API-0001/work-orders")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] > 0
        assert len(data["items"]) > 0

    def test_work_orders_pagination(self, client):
        resp = client.get(
            "/api/v1/equipment/EQ-API-0001/work-orders?page=1&page_size=5"
        )
        data = resp.json()
        assert len(data["items"]) <= 5

    def test_get_cost_history(self, client):
        resp = client.get("/api/v1/equipment/EQ-API-0001/cost-history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_tag"] == "EQ-API-0001"
        assert len(data["months"]) > 0
        assert "total_cost" in data["months"][0]

    def test_cost_history_nonexistent(self, client):
        resp = client.get("/api/v1/equipment/NOPE/cost-history")
        assert resp.status_code == 404


class TestForecastRoutes:
    def test_generate_forecast(self, client):
        resp = client.post(
            "/api/v1/forecasts/generate",
            json={"asset_tag": "EQ-API-0001", "horizon": 12, "method": "auto"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["forecasted"] >= 1

    def test_get_forecast(self, client):
        client.post(
            "/api/v1/forecasts/generate",
            json={"asset_tag": "EQ-API-0001"},
        )
        resp = client.get("/api/v1/forecasts/EQ-API-0001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_tag"] == "EQ-API-0001"
        assert "monthly_forecasts" in data
        assert "model_metrics" in data

    def test_get_forecast_nonexistent(self, client):
        resp = client.get("/api/v1/forecasts/NOPE")
        assert resp.status_code == 404


class TestFinancialRoutes:
    def test_get_tco(self, client):
        resp = client.get("/api/v1/tco/EQ-API-0001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["asset_tag"] == "EQ-API-0001"
        assert data["total_tco"] > 0
        assert data["estimated_downtime_cost"] > 0

    def test_tco_nonexistent(self, client):
        resp = client.get("/api/v1/tco/NOPE")
        assert resp.status_code == 404

    def test_repair_vs_replace(self, client):
        resp = client.post(
            "/api/v1/repair-vs-replace/EQ-API-0001",
            json={"discount_rate": 0.08, "horizon_years": 5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommended_action"] in (
            "replace_immediately",
            "plan_replacement",
            "continue_operating",
        )
        assert "npv_continue" in data
        assert "npv_replace" in data

    def test_depreciation_straight_line(self, client):
        resp = client.get("/api/v1/depreciation/EQ-API-0001?method=straight_line")
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "straight_line"
        assert len(data["schedule"]) > 0
        assert data["current_book_value"] < data["acquisition_cost"]

    def test_depreciation_macrs(self, client):
        resp = client.get("/api/v1/depreciation/EQ-API-0001?method=macrs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["method"] == "macrs"
        assert len(data["schedule"]) == 8


class TestFleetRoutes:
    def test_health_check(self, client):
        resp = client.get("/api/v1/fleet/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["total_assets"] >= 2

    def test_age_analysis(self, client):
        resp = client.get("/api/v1/fleet/age-analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert "cohorts" in data
        total_in_cohorts = sum(c["count"] for c in data["cohorts"])
        assert total_in_cohorts >= 2

    def test_age_analysis_with_facility(self, client):
        resp = client.get("/api/v1/fleet/age-analysis?facility_id=FAC-001")
        assert resp.status_code == 200
        data = resp.json()
        assert data["facility_id"] == "FAC-001"
