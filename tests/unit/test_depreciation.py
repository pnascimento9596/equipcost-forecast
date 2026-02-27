from datetime import date

import pytest

from equipcost_forecast.financial.depreciation import (
    MACRS_5YR,
    MACRS_7YR,
    compute_book_value,
    macrs_schedule,
    straight_line_schedule,
)


class TestStraightLine:
    def test_100k_10yr_9k_per_year(self):
        """$100K, $10K salvage, 10yr -> $9K/year."""
        schedule = straight_line_schedule(100_000, 10_000, 10, date(2020, 1, 15))
        # Prorate first year: Jan-Sep = 9 months of FY2020
        # Full years in middle, partial at end
        expenses = [e.depreciation_expense for e in schedule]
        full_year_entries = [e for e in expenses if abs(e - 9_000) < 100]
        assert len(full_year_entries) >= 8

    def test_total_equals_depreciable_base(self):
        schedule = straight_line_schedule(1_000_000, 50_000, 10, date(2018, 3, 15))
        total = sum(e.depreciation_expense for e in schedule)
        assert abs(total - 950_000) < 1.0

    def test_ending_value_matches_salvage(self):
        schedule = straight_line_schedule(500_000, 25_000, 7, date(2019, 6, 1))
        last = schedule[-1]
        assert abs(last.ending_book_value - 25_000) < 1.0

    def test_beginning_value_equals_acquisition(self):
        schedule = straight_line_schedule(800_000, 40_000, 8, date(2020, 11, 1))
        assert schedule[0].beginning_book_value == 800_000

    def test_fiscal_year_alignment(self):
        """Acquisition in March -> first FY is same calendar year."""
        schedule = straight_line_schedule(120_000, 12_000, 10, date(2020, 3, 1))
        assert schedule[0].fiscal_year == 2020

    def test_october_acquisition_starts_next_fy(self):
        """Acquisition in October -> first FY is next calendar year."""
        schedule = straight_line_schedule(120_000, 12_000, 10, date(2020, 10, 15))
        assert schedule[0].fiscal_year == 2021


class TestMACRS:
    def test_5yr_percentages_sum_to_100(self):
        assert abs(sum(MACRS_5YR) - 1.0) < 0.001

    def test_7yr_percentages_sum_to_100(self):
        assert abs(sum(MACRS_7YR) - 1.0) < 0.001

    def test_macrs_7yr_total_equals_cost(self):
        cost = 1_000_000.0
        schedule = macrs_schedule(cost, 7, date(2020, 1, 1))
        total = sum(e.depreciation_expense for e in schedule)
        assert abs(total - cost) < 1.0

    def test_macrs_5yr_total_equals_cost(self):
        cost = 500_000.0
        schedule = macrs_schedule(cost, 5, date(2020, 1, 1))
        total = sum(e.depreciation_expense for e in schedule)
        assert abs(total - cost) < 1.0

    def test_macrs_7yr_has_8_entries(self):
        schedule = macrs_schedule(100_000, 7, date(2020, 1, 1))
        assert len(schedule) == 8

    def test_macrs_5yr_has_6_entries(self):
        schedule = macrs_schedule(100_000, 5, date(2020, 1, 1))
        assert len(schedule) == 6

    def test_macrs_year_by_year_values(self):
        """Verify specific year-by-year depreciation for 7-year MACRS."""
        cost = 1_000_000.0
        schedule = macrs_schedule(cost, 7, date(2020, 1, 1))

        expected = [pct * cost for pct in MACRS_7YR]
        for entry, exp in zip(schedule, expected):
            assert abs(entry.depreciation_expense - exp) < 1.0

    def test_macrs_ending_book_near_zero(self):
        schedule = macrs_schedule(750_000, 7, date(2020, 1, 1))
        assert schedule[-1].ending_book_value < 1.0

    def test_invalid_recovery_period_raises(self):
        with pytest.raises(ValueError, match="Unsupported"):
            macrs_schedule(100_000, 3, date(2020, 1, 1))


class TestComputeBookValue:
    def test_book_value_decreases_over_time(self, session, sample_equipment):
        bv = compute_book_value(sample_equipment.id, session, "straight_line")
        assert bv < float(sample_equipment.acquisition_cost)
        assert bv >= 0

    def test_macrs_book_value(self, session, sample_equipment):
        bv = compute_book_value(sample_equipment.id, session, "macrs")
        assert bv < float(sample_equipment.acquisition_cost)

    def test_new_equipment_high_book_value(self, session, sample_new_equipment):
        bv = compute_book_value(sample_new_equipment.id, session, "straight_line")
        # 1 year old, should still have most of its value
        assert bv > float(sample_new_equipment.acquisition_cost) * 0.7
