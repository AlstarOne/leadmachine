"""Tests for Redis connectivity."""

import pytest
import redis.asyncio as redis

from src.config import Settings


@pytest.mark.asyncio
async def test_redis_connection(test_settings: Settings) -> None:
    """Test that we can connect to Redis and ping."""
    client = redis.from_url(test_settings.redis_url)

    try:
        result = await client.ping()
        assert result is True
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_set_get(test_settings: Settings) -> None:
    """Test that we can set and get values from Redis."""
    client = redis.from_url(test_settings.redis_url)

    try:
        # Set a test value
        await client.set("test_key", "test_value", ex=10)

        # Get the value back
        value = await client.get("test_key")
        assert value == b"test_value"

        # Clean up
        await client.delete("test_key")
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_redis_increment(test_settings: Settings) -> None:
    """Test Redis increment operations."""
    client = redis.from_url(test_settings.redis_url)

    try:
        key = "test_counter"

        # Start fresh
        await client.delete(key)

        # Increment
        result = await client.incr(key)
        assert result == 1

        result = await client.incr(key)
        assert result == 2

        # Clean up
        await client.delete(key)
    finally:
        await client.aclose()
