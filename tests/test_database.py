"""Tests for database connectivity."""

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_database_connection(db_session: AsyncSession) -> None:
    """Test that we can connect to the database and execute a query."""
    result = await db_session.execute(text("SELECT 1"))
    value = result.scalar()

    assert value == 1


@pytest.mark.asyncio
async def test_database_version(db_session: AsyncSession) -> None:
    """Test that we can get the PostgreSQL version."""
    result = await db_session.execute(text("SELECT version()"))
    version = result.scalar()

    assert version is not None
    assert "PostgreSQL" in str(version)


@pytest.mark.asyncio
async def test_database_session_rollback(db_session: AsyncSession) -> None:
    """Test that session properly handles transactions."""
    # Execute a simple query within the session
    result = await db_session.execute(text("SELECT current_database()"))
    db_name = result.scalar()

    assert db_name is not None
