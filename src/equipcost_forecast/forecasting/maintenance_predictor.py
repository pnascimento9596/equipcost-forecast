from datetime import date, timedelta
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from equipcost_forecast.models.orm import WorkOrder
from equipcost_forecast.models.schemas import FailurePrediction


def predict_next_failure(equipment_id: int, session: Session) -> FailurePrediction:
    """Predict next failure based on MTBF from corrective work order history.

    Args:
        equipment_id: Equipment to analyze.
        session: Database session.

    Returns:
        FailurePrediction with MTBF, predicted date, probability, and cost.
    """
    # Get corrective repair dates ordered chronologically
    repairs = session.execute(
        select(WorkOrder.opened_date, WorkOrder.total_cost)
        .where(
            WorkOrder.equipment_id == equipment_id,
            WorkOrder.wo_type == "corrective_repair",
        )
        .order_by(WorkOrder.opened_date)
    ).all()

    if len(repairs) < 2:
        raise ValueError(
            f"Equipment {equipment_id} has insufficient repair history "
            f"({len(repairs)} repairs, need at least 2)"
        )

    dates = [r.opened_date for r in repairs]
    costs = [float(r.total_cost or 0) for r in repairs]

    # Compute time between failures (in days)
    tbf = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    tbf = [t for t in tbf if t > 0]

    if not tbf:
        raise ValueError(f"Equipment {equipment_id}: no valid time-between-failures")

    mtbf_days = float(np.mean(tbf))
    std_tbf = float(np.std(tbf)) if len(tbf) > 1 else mtbf_days * 0.3

    # Predicted next failure: last repair date + MTBF
    last_repair = dates[-1]
    predicted_date = last_repair + timedelta(days=int(mtbf_days))

    # Probability of failure within 90 days from today
    today = date.today()
    days_since_last = (today - last_repair).days
    if std_tbf > 0:
        # Simple normal CDF approximation
        z_90 = (days_since_last + 90 - mtbf_days) / std_tbf
        prob_90 = float(_norm_cdf(z_90))
    else:
        prob_90 = 1.0 if days_since_last + 90 >= mtbf_days else 0.0

    # Estimated repair cost: recent average with slight escalation
    recent_costs = costs[-5:]
    avg_cost = np.mean(recent_costs) * 1.05

    return FailurePrediction(
        equipment_id=equipment_id,
        mtbf_days=round(mtbf_days, 1),
        predicted_next_failure=predicted_date,
        probability_within_90_days=round(min(prob_90, 1.0), 4),
        estimated_repair_cost=Decimal(str(round(avg_cost, 2))),
    )


def _norm_cdf(z: float) -> float:
    """Approximate standard normal CDF using the error function."""
    import math

    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
