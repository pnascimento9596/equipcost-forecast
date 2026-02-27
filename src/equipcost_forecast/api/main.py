import logging
import time
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from equipcost_forecast.api.routes import equipment, financial, fleet, forecasts
from equipcost_forecast.models.database import get_engine, init_db

logger = logging.getLogger("equipcost_forecast.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting equipcost-forecast API")
    engine = get_engine()
    init_db(engine)
    yield
    logger.info("Shutting down equipcost-forecast API")


app = FastAPI(
    title="equipcost-forecast API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.time()
    response = await call_next(request)
    elapsed = time.time() - start
    logger.info(
        "%s %s %d %.3fs",
        request.method,
        request.url.path,
        response.status_code,
        elapsed,
    )
    return response


app.include_router(equipment.router, prefix="/api/v1")
app.include_router(forecasts.router, prefix="/api/v1")
app.include_router(financial.router, prefix="/api/v1")
app.include_router(fleet.router, prefix="/api/v1")


@app.get("/api/v1/health")
def health():
    """Root-level health check."""
    return {"status": "ok", "service": "equipcost-forecast"}
