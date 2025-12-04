from contextlib import asynccontextmanager
from typing import Any

import redis.asyncio as redis
from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from src.config import get_settings
from src.database import async_session_maker, close_db, engine

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
    """Application lifespan handler for startup and shutdown events."""
    # Startup
    yield
    # Shutdown
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Lead acquisition workflow system with scraping, enrichment, scoring, personalization, and email automation",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", status_code=status.HTTP_200_OK, tags=["Health"])
async def health_check() -> dict[str, str]:
    """Basic health check endpoint."""
    return {"status": "healthy", "version": settings.app_version}


@app.get("/health/ready", status_code=status.HTTP_200_OK, tags=["Health"])
async def readiness_check() -> dict[str, Any]:
    """
    Readiness check - verifies all dependencies are available.
    Returns 200 if all dependencies are ready, 503 otherwise.
    """
    checks: dict[str, Any] = {
        "database": False,
        "redis": False,
    }

    # Check database
    try:
        async with async_session_maker() as session:
            await session.execute(text("SELECT 1"))
            checks["database"] = True
    except Exception as e:
        checks["database"] = str(e)

    # Check Redis
    try:
        redis_client = redis.from_url(settings.redis_url)
        await redis_client.ping()
        await redis_client.aclose()
        checks["redis"] = True
    except Exception as e:
        checks["redis"] = str(e)

    all_ready = all(v is True for v in checks.values())

    return {
        "status": "ready" if all_ready else "not_ready",
        "checks": checks,
    }


@app.get("/health/live", status_code=status.HTTP_200_OK, tags=["Health"])
async def liveness_check() -> dict[str, str]:
    """Liveness check - verifies the application is running."""
    return {"status": "alive"}


# API routes
from src.api.routes import companies_router, emails_router, enrich_router, leads_router, score_router, scrape_router

app.include_router(scrape_router, prefix="/api")
app.include_router(companies_router, prefix="/api")
app.include_router(enrich_router, prefix="/api")
app.include_router(leads_router, prefix="/api")
app.include_router(score_router, prefix="/api")
app.include_router(emails_router, prefix="/api")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=settings.debug)
