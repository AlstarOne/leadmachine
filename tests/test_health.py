"""Tests for health check endpoints."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_endpoint(client: AsyncClient) -> None:
    """Test that GET /health returns 200 with status healthy."""
    response = await client.get("/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data


@pytest.mark.asyncio
async def test_liveness_endpoint(client: AsyncClient) -> None:
    """Test that GET /health/live returns 200 with status alive."""
    response = await client.get("/health/live")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "alive"


@pytest.mark.asyncio
async def test_readiness_endpoint_structure(client: AsyncClient) -> None:
    """Test that GET /health/ready returns proper structure."""
    response = await client.get("/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "checks" in data
    assert "database" in data["checks"]
    assert "redis" in data["checks"]
