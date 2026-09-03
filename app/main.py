"""FastAPI application. Every surface — web, Android, cron — is a client of this."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import routes_brief, routes_checkin, routes_data, routes_supplements, routes_sync
from app.config import get_settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

settings = get_settings()

app = FastAPI(
    title="Health Dashboard API",
    version="0.1.0",
    description="Personal health aggregation. Phase 1: ingestion, check-in, supplements.",
    docs_url="/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8081", "http://localhost:19006"],  # Expo dev
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

API_PREFIX = "/api/v1"
app.include_router(routes_checkin.router, prefix=API_PREFIX)
app.include_router(routes_supplements.router, prefix=API_PREFIX)
app.include_router(routes_sync.router, prefix=API_PREFIX)
app.include_router(routes_sync.public, prefix=API_PREFIX)
app.include_router(routes_data.router, prefix=API_PREFIX)
app.include_router(routes_brief.router, prefix=API_PREFIX)
app.include_router(routes_brief.metrics_router, prefix=API_PREFIX)


@app.get("/health", tags=["ops"])
def health() -> dict:
    """Unauthenticated liveness probe. Phase 0 acceptance test targets this."""
    return {"status": "ok", "environment": settings.environment, "version": "0.1.0"}
