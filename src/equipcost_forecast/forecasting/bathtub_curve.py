from datetime import date

import numpy as np
from scipy.optimize import curve_fit
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import EquipmentRegistry, WorkOrder
from equipcost_forecast.models.schemas import BathtubCurveParams, RemainingLifeEstimate


def _weibull_rate(t: np.ndarray, shape: float, scale: float) -> np.ndarray:
    """Weibull failure rate: (shape/scale) * (t/scale)^(shape-1)."""
    t = np.maximum(t, 0.01)
    return (shape / scale) * (t / scale) ** (shape - 1)


def _bathtub_model(
    t: np.ndarray,
    shape_early: float,
    scale_early: float,
    rate_useful: float,
    shape_wear: float,
    scale_wear: float,
    t_early: float,
    t_wear: float,
) -> np.ndarray:
    """Piecewise bathtub curve: early Weibull + constant + wear-out Weibull."""
    result = np.zeros_like(t, dtype=float)
    early_mask = t < t_early
    useful_mask = (t >= t_early) & (t < t_wear)
    wear_mask = t >= t_wear

    result[early_mask] = _weibull_rate(t[early_mask], shape_early, scale_early)
    result[useful_mask] = rate_useful
    result[wear_mask] = _weibull_rate(t[wear_mask] - t_wear + 1, shape_wear, scale_wear)
    return result


class FailureRateModeler:
    """Fits bathtub curve failure rate models to equipment work order data."""

    def fit_bathtub_curve(
        self,
        equipment_class: str,
        work_order_data: list[dict],
    ) -> BathtubCurveParams:
        """Fit a piecewise bathtub curve to corrective repair data.

        Args:
            equipment_class: Equipment type to model.
            work_order_data: List of dicts with 'age_months' and 'annual_repair_count'.

        Returns:
            BathtubCurveParams with fitted model parameters.
        """
        if not work_order_data:
            raise ValueError("No work order data provided for curve fitting")

        ages = np.array([d["age_months"] for d in work_order_data], dtype=float)
        rates = np.array(
            [d["annual_repair_count"] for d in work_order_data], dtype=float
        )

        # Initial parameter guesses
        p0 = [
            0.5,  # shape_early (<1 = decreasing)
            12.0,  # scale_early
            0.5,  # rate_useful
            2.5,  # shape_wear (>1 = increasing)
            24.0,  # scale_wear
            12.0,  # t_early (months)
            84.0,  # t_wear (months)
        ]

        bounds_lower = [0.1, 1.0, 0.01, 1.1, 1.0, 3.0, 36.0]
        bounds_upper = [0.99, 60.0, 5.0, 10.0, 120.0, 36.0, 180.0]

        try:
            popt, _ = curve_fit(
                _bathtub_model,
                ages,
                rates,
                p0=p0,
                bounds=(bounds_lower, bounds_upper),
                maxfev=10000,
            )
        except (RuntimeError, ValueError):
            # Fall back to defaults if fitting fails
            popt = p0

        return BathtubCurveParams(
            equipment_class=equipment_class,
            early_life_shape=round(float(popt[0]), 4),
            early_life_scale=round(float(popt[1]), 4),
            useful_life_rate=round(float(popt[2]), 4),
            wearout_shape=round(float(popt[3]), 4),
            wearout_scale=round(float(popt[4]), 4),
            transition_month_early=int(popt[5]),
            transition_month_wearout=int(popt[6]),
        )

    def predict_annual_repairs(
        self, age_months: int, params: BathtubCurveParams
    ) -> float:
        """Predict annual repair count at a given age."""
        t = np.array([float(age_months)])
        rate = _bathtub_model(
            t,
            params.early_life_shape,
            params.early_life_scale,
            params.useful_life_rate,
            params.wearout_shape,
            params.wearout_scale,
            float(params.transition_month_early),
            float(params.transition_month_wearout),
        )
        return float(rate[0])

    def estimate_remaining_useful_life(
        self, equipment_id: int, session: Session
    ) -> RemainingLifeEstimate:
        """Estimate remaining useful life based on failure rate trend."""
        eq = session.get(EquipmentRegistry, equipment_id)
        if not eq:
            raise ValueError(f"Equipment {equipment_id} not found")

        current_age_months = int((date.today() - eq.acquisition_date).days / 30.44)

        # Get corrective repair data for this equipment class
        wo_data = self._get_class_repair_data(eq.equipment_class, session)

        if len(wo_data) < 5:
            # Not enough data; use useful life estimate
            remaining = max(
                0, (eq.expected_useful_life_months or 120) - current_age_months
            )
            return RemainingLifeEstimate(
                equipment_id=equipment_id,
                current_age_months=current_age_months,
                estimated_remaining_months=remaining,
                confidence=0.3,
                method="useful_life_default",
            )

        params = self.fit_bathtub_curve(eq.equipment_class, wo_data)

        # Find when failure rate exceeds threshold (3x useful-life rate)
        threshold = params.useful_life_rate * 3
        for future_month in range(current_age_months, current_age_months + 240):
            rate = self.predict_annual_repairs(future_month, params)
            if rate > threshold:
                remaining = future_month - current_age_months
                return RemainingLifeEstimate(
                    equipment_id=equipment_id,
                    current_age_months=current_age_months,
                    estimated_remaining_months=max(0, remaining),
                    confidence=0.6,
                    method="bathtub_curve",
                )

        return RemainingLifeEstimate(
            equipment_id=equipment_id,
            current_age_months=current_age_months,
            estimated_remaining_months=120,
            confidence=0.4,
            method="bathtub_curve_no_threshold",
        )

    def _get_class_repair_data(
        self, equipment_class: str, session: Session
    ) -> list[dict]:
        """Gather annual repair counts by age for an equipment class."""
        # Get all corrective repairs for this class, grouped by equipment age at repair time
        rows = session.execute(
            select(
                EquipmentRegistry.id,
                EquipmentRegistry.acquisition_date,
                func.count(WorkOrder.id).label("repair_count"),
                func.strftime("%Y", WorkOrder.opened_date).label("year"),
            )
            .join(WorkOrder, WorkOrder.equipment_id == EquipmentRegistry.id)
            .where(
                EquipmentRegistry.equipment_class == equipment_class,
                WorkOrder.wo_type == "corrective_repair",
            )
            .group_by(EquipmentRegistry.id, "year")
        ).all()

        data = []
        for row in rows:
            year = int(row.year)
            mid_year = date(year, 7, 1)
            age_months = int((mid_year - row.acquisition_date).days / 30.44)
            if age_months > 0:
                data.append(
                    {
                        "age_months": age_months,
                        "annual_repair_count": float(row.repair_count),
                    }
                )
        return data
