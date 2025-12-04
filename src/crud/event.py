"""CRUD operations for Event model."""

from datetime import datetime

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.base import CRUDBase
from src.models.event import Event, EventType
from src.schemas.event import EventCreate


class CRUDEvent(CRUDBase[Event, EventCreate, EventCreate]):
    """CRUD operations for Event."""

    async def get_by_email(
        self,
        db: AsyncSession,
        *,
        email_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        """Get events by email ID."""
        result = await db.execute(
            select(Event)
            .where(Event.email_id == email_id)
            .order_by(Event.timestamp.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_type(
        self,
        db: AsyncSession,
        *,
        event_type: EventType,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Event]:
        """Get events by type."""
        result = await db.execute(
            select(Event)
            .where(Event.event_type == event_type)
            .order_by(Event.timestamp.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def create_open_event(
        self,
        db: AsyncSession,
        *,
        email_id: int,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Event:
        """Create an open tracking event."""
        event = Event.create_open_event(
            email_id=email_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    async def create_click_event(
        self,
        db: AsyncSession,
        *,
        email_id: int,
        clicked_url: str,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> Event:
        """Create a click tracking event."""
        event = Event.create_click_event(
            email_id=email_id,
            clicked_url=clicked_url,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    async def create_reply_event(
        self,
        db: AsyncSession,
        *,
        email_id: int,
        extra_data: dict | None = None,
    ) -> Event:
        """Create a reply event."""
        event = Event.create_reply_event(
            email_id=email_id,
            extra_data=extra_data,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    async def create_bounce_event(
        self,
        db: AsyncSession,
        *,
        email_id: int,
        extra_data: dict | None = None,
    ) -> Event:
        """Create a bounce event."""
        event = Event.create_bounce_event(
            email_id=email_id,
            extra_data=extra_data,
        )
        db.add(event)
        await db.commit()
        await db.refresh(event)
        return event

    async def count_by_type(
        self,
        db: AsyncSession,
        *,
        email_id: int | None = None,
    ) -> dict[EventType, int]:
        """Count events by type, optionally filtered by email_id."""
        query = select(Event.event_type, func.count(Event.id)).group_by(Event.event_type)

        if email_id is not None:
            query = query.where(Event.email_id == email_id)

        result = await db.execute(query)
        return {row[0]: row[1] for row in result.all()}

    async def get_unique_opens(
        self,
        db: AsyncSession,
        *,
        email_id: int,
    ) -> int:
        """Count unique opens (by IP address) for an email."""
        result = await db.execute(
            select(func.count(func.distinct(Event.ip_address)))
            .where(Event.email_id == email_id)
            .where(Event.event_type == EventType.OPEN)
        )
        return result.scalar_one() or 0


event = CRUDEvent(Event)
