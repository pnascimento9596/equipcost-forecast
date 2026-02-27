from datetime import date

from equipcost_forecast.ingestion.contract_loader import (
    get_active_contracts,
    load_contracts,
    load_pm_schedules,
)
from equipcost_forecast.ingestion.equipment_loader import (
    get_equipment_by_class,
    get_equipment_by_facility,
    load_equipment,
)
from equipcost_forecast.ingestion.work_order_loader import (
    load_work_orders,
    load_work_orders_by_type,
    load_work_orders_in_range,
)


class TestEquipmentLoader:
    def test_load_all_equipment(self, session, sample_equipment, sample_new_equipment):
        results = load_equipment(session)
        assert len(results) >= 2

    def test_get_by_class(self, session, sample_equipment, sample_new_equipment):
        ct_scanners = get_equipment_by_class(session, "ct_scanner")
        assert len(ct_scanners) >= 1
        for eq in ct_scanners:
            assert eq.equipment_class == "ct_scanner"

    def test_get_by_class_empty(self, session, sample_equipment):
        results = get_equipment_by_class(session, "nonexistent_class")
        assert results == []

    def test_get_by_facility(self, session, sample_equipment, sample_new_equipment):
        fac_001 = get_equipment_by_facility(session, "FAC-001")
        assert len(fac_001) >= 1
        for eq in fac_001:
            assert eq.facility_id == "FAC-001"


class TestWorkOrderLoader:
    def test_load_all_work_orders(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        results = load_work_orders(session)
        assert len(results) > 0

    def test_load_by_equipment(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        results = load_work_orders(session, equipment_id=sample_equipment.id)
        assert len(results) > 0
        for wo in results:
            assert wo.equipment_id == sample_equipment.id

    def test_load_by_type(self, session, sample_equipment, work_orders_for_equipment):
        repairs = load_work_orders_by_type(session, "corrective_repair")
        assert len(repairs) > 0
        for wo in repairs:
            assert wo.wo_type == "corrective_repair"

    def test_load_by_type_and_equipment(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        repairs = load_work_orders_by_type(
            session, "corrective_repair", equipment_id=sample_equipment.id
        )
        assert len(repairs) > 0
        for wo in repairs:
            assert wo.wo_type == "corrective_repair"
            assert wo.equipment_id == sample_equipment.id

    def test_load_in_date_range(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        results = load_work_orders_in_range(
            session, date(2020, 1, 1), date(2020, 12, 31)
        )
        assert len(results) > 0
        for wo in results:
            assert date(2020, 1, 1) <= wo.opened_date <= date(2020, 12, 31)

    def test_load_in_range_with_equipment(
        self, session, sample_equipment, work_orders_for_equipment
    ):
        results = load_work_orders_in_range(
            session,
            date(2018, 1, 1),
            date(2026, 12, 31),
            equipment_id=sample_equipment.id,
        )
        assert len(results) > 0
        for wo in results:
            assert wo.equipment_id == sample_equipment.id


class TestContractLoader:
    def test_load_all_contracts(self, session, sample_equipment, sample_contract):
        results = load_contracts(session)
        assert len(results) >= 1

    def test_load_by_equipment(self, session, sample_equipment, sample_contract):
        results = load_contracts(session, equipment_id=sample_equipment.id)
        assert len(results) >= 1
        for c in results:
            assert c.equipment_id == sample_equipment.id

    def test_get_active_contracts(self, session, sample_equipment, sample_contract):
        results = get_active_contracts(session, sample_equipment.id)
        assert len(results) >= 1
        for c in results:
            assert c.end_date >= date.today()

    def test_load_pm_schedules_empty(self, session, sample_equipment):
        results = load_pm_schedules(session, equipment_id=sample_equipment.id)
        assert results == []

    def test_load_pm_schedules_all(self, session):
        results = load_pm_schedules(session)
        assert isinstance(results, list)
