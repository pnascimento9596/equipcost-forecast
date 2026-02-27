import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="equipcost-forecast CLI")
console = Console()


@app.command("init-db")
def init_db():
    """Initialize the database (create all tables)."""
    from equipcost_forecast.models.database import get_engine
    from equipcost_forecast.models.database import init_db as _init_db

    engine = get_engine()
    _init_db(engine)
    console.print("[green]Database initialized.[/green]")


@app.command("generate-data")
def generate_data():
    """Run the synthetic data generator."""
    import subprocess
    import sys

    subprocess.run([sys.executable, "scripts/generate_data.py"], check=True)


@app.command("load-data")
def load_data():
    """Initialize database and load synthetic data.

    Equivalent to running init-db followed by generate-data.
    """
    from equipcost_forecast.models.database import get_engine
    from equipcost_forecast.models.database import init_db as _init_db

    console.print("Initializing database...")
    engine = get_engine()
    _init_db(engine)
    console.print("[green]Database initialized.[/green]")

    console.print("Generating synthetic data...")
    import subprocess
    import sys

    subprocess.run([sys.executable, "scripts/generate_data.py"], check=True)
    console.print("[green]Data loaded successfully.[/green]")


@app.command()
def aggregate(
    equipment_id: int = typer.Option(
        None, "--equipment-id", "-e", help="Equipment ID (all if omitted)"
    ),
):
    """Compute monthly cost rollups from work orders and contracts."""
    from equipcost_forecast.forecasting.cost_aggregator import CostAggregator
    from equipcost_forecast.models.database import get_engine, get_session

    with get_session(get_engine()) as session:
        aggregator = CostAggregator(session)
        count = aggregator.compute_monthly_rollups(equipment_id)
        console.print(f"[green]Created {count} monthly rollup records.[/green]")


@app.command()
def forecast(
    equipment_id: int = typer.Option(
        None,
        "--equipment-id",
        "-e",
        help="Equipment ID (picks first CT scanner if omitted)",
    ),
    horizon: int = typer.Option(
        36, "--horizon", "-h", help="Forecast horizon in months"
    ),
    method: str = typer.Option(
        "auto",
        "--method",
        "-m",
        help="Forecast method: auto, arima, exponential_smoothing",
    ),
):
    """Run cost forecast for an equipment item."""
    from sqlalchemy import select

    from equipcost_forecast.forecasting.cost_aggregator import CostAggregator
    from equipcost_forecast.forecasting.time_series import CostForecaster
    from equipcost_forecast.models.database import get_engine, get_session
    from equipcost_forecast.models.orm import EquipmentRegistry, MonthlyCostRollup

    with get_session(get_engine()) as session:
        if equipment_id is None:
            eq = session.execute(
                select(EquipmentRegistry)
                .where(EquipmentRegistry.equipment_class == "ct_scanner")
                .limit(1)
            ).scalar_one_or_none()
            if eq is None:
                console.print("[red]No equipment found. Run load-data first.[/red]")
                raise typer.Exit(1)
            equipment_id = eq.id
            console.print(
                f"Auto-selected: [cyan]{eq.asset_tag}[/cyan] ({eq.manufacturer} {eq.model_name})"
            )

        # Ensure rollups exist
        rollup_count = session.execute(
            select(MonthlyCostRollup)
            .where(MonthlyCostRollup.equipment_id == equipment_id)
            .limit(1)
        ).scalar_one_or_none()
        if rollup_count is None:
            console.print("Computing cost rollups first...")
            aggregator = CostAggregator(session)
            aggregator.compute_monthly_rollups(equipment_id)

        forecaster = CostForecaster()
        result = forecaster.forecast_equipment(equipment_id, session, horizon, method)

        console.print(f"\n[green]Forecast complete: {result.method}[/green]")
        console.print(f"  Horizon: {result.horizon_months} months")
        console.print(
            f"  Metrics: MAE=${result.metrics.mae:,.2f}, "
            f"RMSE=${result.metrics.rmse:,.2f}, MAPE={result.metrics.mape:.1f}%"
        )

        table = Table(title=f"Monthly Forecast (first 12 of {horizon})")
        table.add_column("Month", style="cyan")
        table.add_column("Predicted", justify="right", style="green")
        table.add_column("Lower Bound", justify="right")
        table.add_column("Upper Bound", justify="right")

        for p in result.predictions[:12]:
            table.add_row(
                str(p.month),
                f"${float(p.predicted_cost):,.2f}",
                f"${float(p.lower_bound):,.2f}",
                f"${float(p.upper_bound):,.2f}",
            )
        console.print(table)


@app.command()
def analyze(
    facility: str = typer.Option(None, "--facility", "-f", help="Facility ID filter"),
    budget: float = typer.Option(
        2_000_000, "--budget", "-b", help="Annual capital budget"
    ),
):
    """Run repair-vs-replace analysis and rank replacement priorities."""
    from sqlalchemy import func, select

    from equipcost_forecast.financial.replacement_optimizer import (
        FleetReplacementOptimizer,
    )
    from equipcost_forecast.forecasting.cost_aggregator import CostAggregator
    from equipcost_forecast.models.database import get_engine, get_session
    from equipcost_forecast.models.orm import MonthlyCostRollup

    with get_session(get_engine()) as session:
        # Ensure rollups exist
        has_rollups = (
            session.execute(select(func.count(MonthlyCostRollup.id))).scalar() or 0
        )
        if has_rollups == 0:
            console.print("Computing cost rollups first...")
            CostAggregator(session).compute_monthly_rollups()

        console.print(
            f"Running repair-vs-replace analysis{f' for {facility}' if facility else ''}..."
        )

        optimizer = FleetReplacementOptimizer(session, annual_capital_budget=budget)
        priorities = optimizer.rank_replacement_priorities(facility)

        replace_now = [
            p for p in priorities if p.recommended_action == "replace_immediately"
        ]
        plan_replace = [
            p for p in priorities if p.recommended_action == "plan_replacement"
        ]
        keep = [p for p in priorities if p.recommended_action == "continue_operating"]

        console.print("\n[bold]Analysis Summary[/bold]")
        console.print(f"  Total evaluated: {len(priorities)}")
        console.print(f"  [red]Replace immediately: {len(replace_now)}[/red]")
        console.print(f"  [yellow]Plan replacement: {len(plan_replace)}[/yellow]")
        console.print(f"  [green]Continue operating: {len(keep)}[/green]")

        if replace_now or plan_replace:
            table = Table(title="Top Replacement Priorities")
            table.add_column("Rank", style="bold")
            table.add_column("Asset Tag", style="cyan")
            table.add_column("Class")
            table.add_column("Age (yr)", justify="right")
            table.add_column("NPV Savings", justify="right", style="green")
            table.add_column("Repl. Cost", justify="right")
            table.add_column("Action", style="bold")

            for p in (replace_now + plan_replace)[:20]:
                action_style = (
                    "red" if p.recommended_action == "replace_immediately" else "yellow"
                )
                table.add_row(
                    str(p.rank),
                    p.asset_tag,
                    p.equipment_class,
                    f"{p.age_months / 12:.1f}",
                    f"${p.npv_savings:,.0f}",
                    f"${p.replacement_cost:,.0f}",
                    f"[{action_style}]{p.recommended_action}[/{action_style}]",
                )
            console.print(table)


@app.command()
def report(
    facility: str = typer.Option(None, "--facility", "-f", help="Facility ID filter"),
):
    """Generate a fleet cost summary report."""
    from datetime import date

    from sqlalchemy import func, select

    from equipcost_forecast.models.database import get_engine, get_session
    from equipcost_forecast.models.orm import (
        EquipmentRegistry,
        MonthlyCostRollup,
    )

    with get_session(get_engine()) as session:
        eq_stmt = select(EquipmentRegistry)
        if facility:
            eq_stmt = eq_stmt.where(EquipmentRegistry.facility_id == facility)
        equipment = list(session.scalars(eq_stmt).all())

        if not equipment:
            console.print("[red]No equipment found.[/red]")
            raise typer.Exit(1)

        eq_ids = [e.id for e in equipment]
        today = date.today()

        # Fleet summary
        total = len(equipment)
        ages = [(today - e.acquisition_date).days / 365.25 for e in equipment]
        avg_age = sum(ages) / len(ages) if ages else 0
        past_useful = sum(
            1
            for e in equipment
            if e.expected_useful_life_months
            and (today - e.acquisition_date).days / 30.44
            > e.expected_useful_life_months
        )

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

        total_acq = sum(float(e.acquisition_cost) for e in equipment)

        console.print(
            f"\n[bold]Fleet Cost Report{f' — {facility}' if facility else ''}[/bold]"
        )
        console.print(f"  Date: {today}")
        console.print(f"  Total assets: {total}")
        console.print(f"  Average age: {avg_age:.1f} years")
        console.print(f"  Past useful life: {past_useful}")
        console.print(f"  Total acquisition value: ${total_acq:,.0f}")
        console.print(f"  Annual maintenance cost: ${annual_cost:,.0f}")
        console.print(
            f"  Maintenance/acquisition ratio: {annual_cost / total_acq * 100:.1f}%"
        )

        # By class
        console.print("\n[bold]Cost by Equipment Class[/bold]")
        table = Table()
        table.add_column("Class")
        table.add_column("Count", justify="right")
        table.add_column("Avg Age", justify="right")
        table.add_column("Annual Cost", justify="right", style="green")
        table.add_column("Avg Cost/Asset", justify="right")

        class_groups: dict[str, list] = {}
        for e in equipment:
            class_groups.setdefault(e.equipment_class, []).append(e)

        for cls, items in sorted(class_groups.items()):
            cls_ids = [e.id for e in items]
            cls_ages = [(today - e.acquisition_date).days / 365.25 for e in items]
            cls_cost = float(
                session.execute(
                    select(func.sum(MonthlyCostRollup.total_cost)).where(
                        MonthlyCostRollup.equipment_id.in_(cls_ids),
                        MonthlyCostRollup.month >= twelve_months_ago,
                    )
                ).scalar()
                or 0
            )
            table.add_row(
                cls,
                str(len(items)),
                f"{sum(cls_ages) / len(cls_ages):.1f}",
                f"${cls_cost:,.0f}",
                f"${cls_cost / len(items):,.0f}",
            )

        console.print(table)


@app.command()
def serve(host: str = "0.0.0.0", port: int = 8000):
    """Start the FastAPI server."""
    import uvicorn

    uvicorn.run("equipcost_forecast.api.main:app", host=host, port=port, reload=True)


@app.command()
def dashboard(port: int = typer.Option(8501, "--port", "-p", help="Streamlit port")):
    """Start the Streamlit dashboard."""
    import subprocess
    import sys
    from pathlib import Path

    dashboard_path = Path(__file__).parent / "dashboard" / "app.py"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            str(dashboard_path),
            f"--server.port={port}",
            "--server.headless=true",
        ],
        check=True,
    )


if __name__ == "__main__":
    app()
