from collections.abc import AsyncGenerator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import Settings, get_settings
from src.database import Base, get_db
from src.main import app

# Import all models to register them with Base.metadata
from src.models import (  # noqa: F401
    Company,
    Lead,
    Email,
    Event,
    ScrapeJob,
    User,
)


def get_test_settings() -> Settings:
    """Get test settings with test database."""
    import os
    # Use environment variables for CI/Docker, fallback to localhost for local dev
    # Note: password and port must match what postgres was initialized with in docker-compose
    db_host = os.getenv("TEST_DB_HOST", "localhost")
    db_port = os.getenv("TEST_DB_PORT", "5433")  # Docker maps to 5433 on host
    db_password = os.getenv("TEST_DB_PASSWORD", "password")
    redis_host = os.getenv("TEST_REDIS_HOST", "localhost")
    return Settings(
        database_url=f"postgresql+asyncpg://leadmachine:{db_password}@{db_host}:{db_port}/leadmachine_test",
        redis_url=f"redis://{redis_host}:6379/0",
        jwt_secret="test-secret-key",
        openai_api_key="sk-test-key",
        debug=True,
    )


@pytest.fixture(scope="function")
def test_settings() -> Settings:
    """Get test settings."""
    return get_test_settings()


@pytest_asyncio.fixture(scope="function")
async def test_engine(test_settings: Settings):  # type: ignore[no-untyped-def]
    """Create test database engine."""
    engine = create_async_engine(
        test_settings.database_url,
        echo=False,
        pool_pre_ping=True,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine) -> AsyncGenerator[AsyncSession, None]:  # type: ignore[no-untyped-def]
    """Create a test database session."""
    async_session = async_sessionmaker(
        test_engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )

    async with async_session() as session:
        yield session
        await session.rollback()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession, test_settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    """Create an async test client."""

    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    def override_get_settings() -> Settings:
        return test_settings

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_settings] = override_get_settings

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
