"""CRUD operations for Lead model."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.base import CRUDBase
from src.models.lead import Lead, LeadClassification, LeadStatus
from src.schemas.lead import LeadCreate, LeadUpdate


class CRUDLead(CRUDBase[Lead, LeadCreate, LeadUpdate]):
    """CRUD operations for Lead."""

    async def get_by_email(
        self, db: AsyncSession, *, email: str
    ) -> Lead | None:
        """Get lead by email."""
        result = await db.execute(
            select(Lead).where(Lead.email == email)
        )
        return result.scalar_one_or_none()

    async def get_by_company(
        self,
        db: AsyncSession,
        *,
        company_id: int,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Lead]:
        """Get leads by company ID."""
        result = await db.execute(
            select(Lead)
            .where(Lead.company_id == company_id)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_status(
        self,
        db: AsyncSession,
        *,
        status: LeadStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Lead]:
        """Get leads by status."""
        result = await db.execute(
            select(Lead)
            .where(Lead.status == status)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_classification(
        self,
        db: AsyncSession,
        *,
        classification: LeadClassification,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Lead]:
        """Get leads by classification."""
        result = await db.execute(
            select(Lead)
            .where(Lead.classification == classification)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_qualified(
        self,
        db: AsyncSession,
        *,
        min_score: int = 60,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Lead]:
        """Get qualified leads (score >= min_score)."""
        result = await db.execute(
            select(Lead)
            .where(Lead.icp_score >= min_score)
            .order_by(Lead.icp_score.desc())
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_score(
        self,
        db: AsyncSession,
        *,
        db_obj: Lead,
        score: int,
        breakdown: dict,
    ) -> Lead:
        """Update lead score and classification."""
        from datetime import datetime

        classification = Lead.get_classification_for_score(score)
        db_obj.icp_score = score
        db_obj.score_breakdown = breakdown
        db_obj.classification = classification
        db_obj.scored_at = datetime.now()

        # Set status based on score threshold (60+ = QUALIFIED)
        if score >= 60:
            db_obj.status = LeadStatus.QUALIFIED
        else:
            db_obj.status = LeadStatus.DISQUALIFIED

        db.add(db_obj)
        await db.commit()
        await db.refresh(db_obj)
        return db_obj

    async def update_status(
        self,
        db: AsyncSession,
        *,
        db_obj: Lead,
        new_status: LeadStatus,
    ) -> Lead:
        """Update lead status if transition is valid."""
        if db_obj.can_transition_to(new_status):
            db_obj.status = new_status
            db.add(db_obj)
            await db.commit()
            await db.refresh(db_obj)
        return db_obj


lead = CRUDLead(Lead)
