FROM python:3.11-slim AS base

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml .
COPY src/ src/
COPY scripts/ scripts/

RUN pip install --no-cache-dir .

RUN mkdir -p /app/data

# ── API target ───────────────────────────────────────────────────────
FROM base AS api
EXPOSE 8000
CMD ["uvicorn", "equipcost_forecast.api.main:app", "--host", "0.0.0.0", "--port", "8000"]

# ── Dashboard target ─────────────────────────────────────────────────
FROM base AS dashboard
EXPOSE 8501
CMD ["streamlit", "run", "src/equipcost_forecast/dashboard/app.py", "--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]
