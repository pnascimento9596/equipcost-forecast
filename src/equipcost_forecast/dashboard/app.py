"""Streamlit dashboard for equipcost-forecast."""

from datetime import date

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import func, select

from equipcost_forecast.models.database import get_engine, get_session_factory, init_db
from equipcost_forecast.models.orm import (
    CostForecast,
    EquipmentRegistry,
    MonthlyCostRollup,
)


@st.cache_resource
def get_db_factory():
    engine = get_engine()
    init_db(engine)
    return get_session_factory(engine)


def get_session():
    factory = get_db_factory()
    return factory()


# ── Page config ──────────────────────────────────────────────────────
st.set_page_config(page_title="Equipment Cost Forecast", layout="wide")

# ── Sidebar ──────────────────────────────────────────────────────────
st.sidebar.title("Equipment Cost Forecast")
page = st.sidebar.radio("Navigation", ["Fleet Overview", "Equipment Detail"])

session = get_session()

# Global filters
facilities = [
    r[0]
    for r in session.execute(select(EquipmentRegistry.facility_id).distinct()).all()
]
facility_filter = st.sidebar.selectbox("Facility", ["All"] + sorted(facilities))
facility_id = None if facility_filter == "All" else facility_filter

today = date.today()

# ═══════════════════════════════════════════════════════════════════════
# PAGE 1: Fleet Overview
# ═══════════════════════════════════════════════════════════════════════
if page == "Fleet Overview":
    st.title("Fleet Overview")

    # ── Equipment query ──
    eq_stmt = select(EquipmentRegistry)
    if facility_id:
        eq_stmt = eq_stmt.where(EquipmentRegistry.facility_id == facility_id)
    equipment = list(session.scalars(eq_stmt).all())
    eq_ids = [e.id for e in equipment]

    if not equipment:
        st.warning(
            "No equipment found. Run `python -m equipcost_forecast load-data` and `aggregate` first."
        )
        session.close()
        st.stop()

    # ── KPI Cards ──
    total_assets = len(equipment)
    ages = [(today - e.acquisition_date).days / 365.25 for e in equipment]
    avg_age = sum(ages) / len(ages) if ages else 0

    twelve_months_ago = date(today.year - 1, today.month, 1)
    annual_cost = float(
        session.execute(
            select(func.sum(MonthlyCostRollup.total_cost)).where(
                MonthlyCostRollup.equipment_id.in_(eq_ids),
                MonthlyCostRollup.month >= twelve_months_ago,
            )
        ).scalar()
        or 0
    )

    past_useful = sum(
        1
        for e in equipment
        if e.expected_useful_life_months
        and (today - e.acquisition_date).days / 30.44 > e.expected_useful_life_months
    )

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Total Assets", f"{total_assets:,}")
    col2.metric("Avg Age", f"{avg_age:.1f} years")
    col3.metric("Annual Maint. Cost", f"${annual_cost:,.0f}")
    col4.metric("Past Useful Life", f"{past_useful}")

    # ── Equipment class distribution ──
    st.subheader("Equipment Class Distribution")
    class_counts: dict[str, int] = {}
    for e in equipment:
        class_counts[e.equipment_class] = class_counts.get(e.equipment_class, 0) + 1

    fig_class = px.bar(
        x=list(class_counts.keys()),
        y=list(class_counts.values()),
        labels={"x": "Equipment Class", "y": "Count"},
        color=list(class_counts.keys()),
    )
    fig_class.update_layout(showlegend=False, height=350)
    st.plotly_chart(fig_class, width="stretch")

    # ── Fleet age distribution ──
    st.subheader("Fleet Age Distribution")
    age_data = pd.DataFrame(
        {
            "age_years": [
                (today - e.acquisition_date).days / 365.25 for e in equipment
            ],
            "equipment_class": [e.equipment_class for e in equipment],
        }
    )
    fig_age = px.histogram(
        age_data,
        x="age_years",
        color="equipment_class",
        nbins=30,
        labels={"age_years": "Age (Years)", "equipment_class": "Class"},
    )
    fig_age.update_layout(height=350)
    st.plotly_chart(fig_age, width="stretch")

    # ── Facility comparison ──
    st.subheader("Facility Comparison")
    fac_data = []
    for fac in facilities:
        fac_eq = (
            [e for e in equipment if e.facility_id == fac]
            if not facility_id
            else equipment
        )
        if facility_id and fac != facility_id:
            continue
        fac_ids = [e.id for e in fac_eq if e.facility_id == fac]
        if not fac_ids:
            continue
        fac_cost = float(
            session.execute(
                select(func.sum(MonthlyCostRollup.total_cost)).where(
                    MonthlyCostRollup.equipment_id.in_(fac_ids),
                    MonthlyCostRollup.month >= twelve_months_ago,
                )
            ).scalar()
            or 0
        )
        fac_data.append(
            {
                "Facility": fac,
                "Assets": len(fac_ids),
                "Annual Cost": f"${fac_cost:,.0f}",
                "Avg Cost/Asset": (
                    f"${fac_cost / len(fac_ids):,.0f}" if fac_ids else "$0"
                ),
            }
        )

    if fac_data:
        st.dataframe(pd.DataFrame(fac_data), width="stretch", hide_index=True)

# ═══════════════════════════════════════════════════════════════════════
# PAGE 2: Equipment Detail
# ═══════════════════════════════════════════════════════════════════════
elif page == "Equipment Detail":
    st.title("Equipment Detail")

    # ── Equipment selector ──
    eq_stmt = select(EquipmentRegistry).order_by(EquipmentRegistry.asset_tag)
    if facility_id:
        eq_stmt = eq_stmt.where(EquipmentRegistry.facility_id == facility_id)
    all_eq = list(session.scalars(eq_stmt).all())

    if not all_eq:
        st.warning("No equipment found.")
        session.close()
        st.stop()

    options = {f"{e.asset_tag} — {e.manufacturer} {e.model_name}": e for e in all_eq}
    selected_label = st.selectbox("Select Equipment", list(options.keys()))
    eq = options[selected_label]

    # ── Equipment info card ──
    age_years = round((today - eq.acquisition_date).days / 365.25, 1)
    col1, col2, col3 = st.columns(3)
    col1.markdown(
        f"**{eq.asset_tag}**  \n"
        f"{eq.manufacturer} {eq.model_name}  \n"
        f"Class: `{eq.equipment_class}`"
    )
    col2.markdown(
        f"**Facility:** {eq.facility_id}  \n"
        f"**Department:** {eq.department}  \n"
        f"**Status:** {eq.status}"
    )
    col3.metric("Age", f"{age_years} years")
    col3.metric("Acquisition Cost", f"${float(eq.acquisition_cost):,.0f}")

    # ── Cost history chart ──
    st.subheader("Cost History")
    rollups = list(
        session.scalars(
            select(MonthlyCostRollup)
            .where(MonthlyCostRollup.equipment_id == eq.id)
            .order_by(MonthlyCostRollup.month)
        ).all()
    )

    if rollups:
        cost_df = pd.DataFrame(
            [
                {
                    "month": r.month,
                    "PM Cost": float(r.pm_cost or 0),
                    "Corrective Cost": float(r.corrective_cost or 0),
                    "Contract Cost": float(r.contract_cost_allocated or 0),
                }
                for r in rollups
            ]
        )
        cost_df["month"] = pd.to_datetime(cost_df["month"])

        fig_cost = go.Figure()
        for col_name in ["PM Cost", "Corrective Cost", "Contract Cost"]:
            fig_cost.add_trace(
                go.Scatter(
                    x=cost_df["month"],
                    y=cost_df[col_name],
                    name=col_name,
                    stackgroup="one",
                )
            )
        fig_cost.update_layout(
            height=400,
            xaxis_title="Month",
            yaxis_title="Cost ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_cost, width="stretch")
    else:
        st.info("No cost history. Run aggregation first.")

    # ── Forecast fan chart ──
    st.subheader("Cost Forecast")
    forecast = session.execute(
        select(CostForecast)
        .where(CostForecast.equipment_id == eq.id)
        .order_by(CostForecast.forecast_date.desc())
        .limit(1)
    ).scalar_one_or_none()

    if forecast and forecast.monthly_forecasts:
        import json

        monthly = json.loads(forecast.monthly_forecasts)
        metrics = json.loads(forecast.model_metrics) if forecast.model_metrics else {}

        fc_df = pd.DataFrame(monthly)
        fc_df["month"] = pd.to_datetime(fc_df["month"])

        fig_fc = go.Figure()

        # Confidence band
        fig_fc.add_trace(
            go.Scatter(
                x=fc_df["month"],
                y=fc_df["upper_bound"],
                mode="lines",
                line=dict(width=0),
                showlegend=False,
            )
        )
        fig_fc.add_trace(
            go.Scatter(
                x=fc_df["month"],
                y=fc_df["lower_bound"],
                mode="lines",
                line=dict(width=0),
                fill="tonexty",
                fillcolor="rgba(68, 68, 255, 0.15)",
                name="Confidence Interval",
            )
        )

        # Prediction line
        fig_fc.add_trace(
            go.Scatter(
                x=fc_df["month"],
                y=fc_df["predicted_cost"],
                mode="lines",
                name="Predicted Cost",
                line=dict(color="blue", width=2),
            )
        )

        # Historical overlay
        if rollups:
            hist_months = [r.month for r in rollups]
            hist_costs = [float(r.total_cost or 0) for r in rollups]
            fig_fc.add_trace(
                go.Scatter(
                    x=hist_months,
                    y=hist_costs,
                    mode="lines",
                    name="Historical",
                    line=dict(color="gray", dash="dot"),
                )
            )

        fig_fc.update_layout(
            height=400,
            xaxis_title="Month",
            yaxis_title="Cost ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig_fc, width="stretch")

        if metrics:
            mc1, mc2, mc3 = st.columns(3)
            mc1.metric("MAE", f"${metrics.get('mae', 0):,.2f}")
            mc2.metric("RMSE", f"${metrics.get('rmse', 0):,.2f}")
            mc3.metric("MAPE", f"{metrics.get('mape', 0):.1f}%")
    else:
        st.info("No forecast available. Generate one via CLI or API.")

    # ── Repair-vs-Replace card ──
    st.subheader("Repair vs. Replace Analysis")
    try:
        from equipcost_forecast.financial.npv_analyzer import NPVAnalyzer
        from equipcost_forecast.forecasting.cost_aggregator import CostAggregator

        # Ensure rollups exist
        if not rollups:
            agg = CostAggregator(session)
            agg.compute_monthly_rollups(eq.id)

        analyzer = NPVAnalyzer()
        result = analyzer.repair_vs_replace(eq.id, session)

        rc1, rc2, rc3 = st.columns(3)
        rc1.metric("NPV Continue", f"${result.npv_continue:,.0f}")
        rc2.metric("NPV Replace", f"${result.npv_replace:,.0f}")
        rc3.metric("NPV Savings", f"${result.npv_savings:,.0f}")

        action = result.recommended_action
        if action == "replace_immediately":
            st.error("Recommendation: **REPLACE IMMEDIATELY**")
        elif action == "plan_replacement":
            st.warning("Recommendation: **PLAN REPLACEMENT**")
        else:
            st.success("Recommendation: **CONTINUE OPERATING**")

    except Exception as e:
        st.info(f"Repair-vs-replace analysis unavailable: {e}")

session.close()
