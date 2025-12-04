"""CRUD operations for Company model."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.crud.base import CRUDBase
from src.models.company import Company, CompanySource, CompanyStatus
from src.schemas.company import CompanyCreate, CompanyUpdate


class CRUDCompany(CRUDBase[Company, CompanyCreate, CompanyUpdate]):
    """CRUD operations for Company."""

    async def get_by_domain(
        self, db: AsyncSession, *, domain: str
    ) -> Company | None:
        """Get company by domain."""
        result = await db.execute(
            select(Company).where(Company.domain == domain)
        )
        return result.scalar_one_or_none()

    async def get_by_status(
        self,
        db: AsyncSession,
        *,
        status: CompanyStatus,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Company]:
        """Get companies by status."""
        result = await db.execute(
            select(Company)
            .where(Company.status == status)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_by_source(
        self,
        db: AsyncSession,
        *,
        source: CompanySource,
        skip: int = 0,
        limit: int = 100,
    ) -> list[Company]:
        """Get companies by source."""
        result = await db.execute(
            select(Company)
            .where(Company.source == source)
            .offset(skip)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_or_create_by_domain(
        self,
        db: AsyncSession,
        *,
        obj_in: CompanyCreate,
    ) -> tuple[Company, bool]:
        """Get existing company by domain or create new one.

        Returns:
            Tuple of (company, created) where created is True if new company was created.
        """
        if obj_in.domain:
            existing = await self.get_by_domain(db, domain=obj_in.domain)
            if existing:
                return existing, False

        company = await self.create(db, obj_in=obj_in)
        return company, True

    async def update_status(
        self,
        db: AsyncSession,
        *,
        db_obj: Company,
        new_status: CompanyStatus,
    ) -> Company:
        """Update company status if transition is valid."""
        if db_obj.can_transition_to(new_status):
            db_obj.status = new_status
            db.add(db_obj)
            await db.commit()
            await db.refresh(db_obj)
        return db_obj


company = CRUDCompany(Company)
