import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import Settings, get_settings
from src.database import Base, get_db
from src.main import app


def get_test_settings() -> Settings:
    """Get test settings with test database."""
    return Settings(
        database_url="postgresql+asyncpg://leadmachine:testpassword@localhost:5432/leadmachine_test",
        redis_url="redis://localhost:6379/0",
        jwt_secret="test-secret-key",
        openai_api_key="sk-test-key",
        debug=True,
    )


@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    """Create an instance of the event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings() -> Settings:
    """Get test settings."""
    return get_test_settings()


@pytest_asyncio.fixture(scope="session")
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


@pytest_asyncio.fixture
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
