"""CRUD operations for Email model."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.base import CRUDBase
from src.models.email import Email, EmailSequenceStep, EmailStatus
from src.schemas.email import EmailCreate, EmailUpdate


class CRUDEmail(CRUDBase[Email, EmailCreate, EmailUpdate]):
    """CRUD operations for Email."""

    async def get_by_tracking_id(
        self, db: AsyncSession, *, tracking_id: str
    ) -> Email | None:
        """Get email by tracking ID."""
        result = await db.execute(
            select(Email).where(Email.tracking_id == tracking_id)
        )
        return result.scalar_one_or_none()

    async def get_by_lead(
        self,
        db: AsyncSession,
        *,
        lead_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Email]:
        """Get emails by lead ID."""
        result = await db.execute(
            select(Email)
            .where(Email.lead_id == lead_id)
            .order_by(Email.sequence_step)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_status(
        self,
        db: AsyncSession,
        *,
        status: EmailStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Email]:
        """Get emails by status."""
        result = await db.execute(
            select(Email)
            .where(Email.status == status)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_pending_to_send(
        self,
        db: AsyncSession,
        *,
        before: datetime | None = None,
        limit: int = 50,
    ) -> list[Email]:
        """Get pending emails scheduled to send."""
        query = select(Email).where(Email.status == EmailStatus.PENDING)

        if before:
            query = query.where(Email.scheduled_at <= before)

        query = query.order_by(Email.scheduled_at).limit(limit)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_sequence_for_lead(
        self,
        db: AsyncSession,
        *,
        lead_id: int,
    ) -> list[Email]:
        """Get complete email sequence for a lead."""
        result = await db.execute(
            select(Email)
            .where(Email.lead_id == lead_id)
            .order_by(Email.sequence_step)
        )
        return list(result.scalars().all())

    async def create_sequence(
        self,
        db: AsyncSession,
        *,
        lead_id: int,
        emails: list[dict],
    ) -> list[Email]:
        """Create a complete email sequence for a lead."""
        sequence = []
        for email_data in emails:
            email_data["lead_id"] = lead_id
            email_create = EmailCreate(**email_data)
            email = await self.create(db, obj_in=email_create)
            sequence.append(email)
        return sequence

    async def record_open(
        self,
        db: AsyncSession,
        *,
        db_obj: Email,
    ) -> Email:
        """Record an email open event."""
        db_obj.record_open()
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def record_click(
        self,
        db: AsyncSession,
        *,
        db_obj: Email,
    ) -> Email:
        """Record a link click event."""
        db_obj.record_click()
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def record_reply(
        self,
        db: AsyncSession,
        *,
        db_obj: Email,
    ) -> Email:
        """Record a reply event."""
        db_obj.record_reply()
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def record_bounce(
        self,
        db: AsyncSession,
        *,
        db_obj: Email,
    ) -> Email:
        """Record a bounce event."""
        db_obj.record_bounce()
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def mark_as_sent(
        self,
        db: AsyncSession,
        *,
        db_obj: Email,
        message_id: str,
    ) -> Email:
        """Mark email as sent with SMTP message ID."""
        db_obj.status = EmailStatus.SENT
        db_obj.message_id = message_id
        db_obj.sent_at = datetime.now()
        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj


email = CRUDEmail(Email)
