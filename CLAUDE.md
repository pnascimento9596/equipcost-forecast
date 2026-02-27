# CLAUDE.md — equipcost-forecast

## Project
Biomedical equipment TCO forecasting platform with lifecycle cost modeling, maintenance prediction, and capital replacement analytics.

## Tech Stack
Python 3.11+ | SQLAlchemy 2.0 + SQLite | FastAPI | Streamlit | pandas | numpy | scipy | statsmodels | Pydantic v2 | pytest

## Architecture
src/equipcost_forecast/
├── models/         # SQLAlchemy ORM models + Pydantic schemas
├── ingestion/      # Equipment registry, work order, contract data loading
├── forecasting/    # Time-series cost forecasting, bathtub curve, maintenance prediction
├── financial/      # NPV, IRR, repair-vs-replace analysis, depreciation
├── api/            # FastAPI routes, middleware, error handlers
├── dashboard/      # Streamlit app for interactive visualization
├── config/         # Settings via pydantic-settings
└── cli.py          # CLI entry point (Typer)

## Code Standards
- Black formatter, isort, ruff linter
- Type hints on all public functions and method signatures
- Docstrings: Google style, only on public classes and functions
- No comments unless explaining non-obvious business or financial logic
- Conventional commits: feat:, fix:, docs:, test:, refactor:, chore:

## Attribution Rules
- NEVER include "Co-Authored-By" or any AI attribution in commits, code, or metadata
- NEVER add comments like "AI-generated", "created by Claude", or similar
- No @author tags or generation timestamps

## Testing
- pytest with >80% coverage target
- Unit tests: financial calculations, forecasting logic, cost curve fitting
- Integration tests: full pipeline from data load to forecast generation
- Fixtures in conftest.py with realistic equipment lifecycle data
- Tests in tests/ mirroring src/ structure

## Data Rules
- ALL data must be synthetic — no real patient, hospital, or equipment serial data
- Synthetic data generator in scripts/generate_data.py
- Realistic equipment types: CT scanners, MRI, ultrasound, ventilators, infusion pumps, patient monitors
- Realistic manufacturers: GE Healthcare, Siemens Healthineers, Philips Healthcare, Canon Medical, Mindray, Draeger

## Database
- SQLAlchemy 2.0 with mapped_column syntax
- SQLite for local dev, connection string via DATABASE_URL env var
- Use Base.metadata.create_all() for table creation (no Alembic)

## Financial Calculations
- NPV: manual implementation with configurable discount rate
- Depreciation: straight-line and MACRS methods
- All monetary values in USD, Numeric(14,2)
- Fiscal year: October 1 - September 30 (hospital standard)

## Dependencies
- Pin all versions in pyproject.toml
- Dev dependencies separate: [project.optional-dependencies] dev = [...]