"""Initial models for Phase 1.

Revision ID: 001_initial_models
Revises:
Create Date: 2025-01-15

Creates tables:
- users (authentication)
- companies (scraped companies)
- leads (contact persons from companies)
- emails (email sequences)
- events (tracking events)
- scrape_jobs (scrape job tracking)
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "001_initial_models"
down_revision = None
branch_labels = None
depends_on = None

# Define enum types with create_type=False since we create them explicitly
companystatus = postgresql.ENUM(
    'NEW', 'ENRICHING', 'ENRICHED', 'NO_CONTACT', 'DISQUALIFIED', 'ARCHIVED',
    name='companystatus',
    create_type=False
)
companysource = postgresql.ENUM(
    'INDEED', 'KVK', 'LINKEDIN', 'TECHLEAP', 'DEALROOM', 'MANUAL', 'OTHER',
    name='companysource',
    create_type=False
)
leadstatus = postgresql.ENUM(
    'NEW', 'ENRICHED', 'NO_EMAIL', 'SCORED', 'QUALIFIED', 'SEQUENCED',
    'CONTACTED', 'REPLIED', 'CONVERTED', 'DISQUALIFIED',
    name='leadstatus',
    create_type=False
)
leadclassification = postgresql.ENUM(
    'HOT', 'WARM', 'COOL', 'COLD', 'UNSCORED',
    name='leadclassification',
    create_type=False
)
emailstatus = postgresql.ENUM(
    'DRAFT', 'PENDING', 'SENDING', 'SENT', 'OPENED', 'CLICKED',
    'REPLIED', 'BOUNCED', 'CANCELLED',
    name='emailstatus',
    create_type=False
)
emailsequencestep = postgresql.ENUM(
    '1', '2', '3', '4',
    name='emailsequencestep',
    create_type=False
)
eventtype = postgresql.ENUM(
    'open', 'click', 'reply', 'bounce', 'complaint', 'unsubscribe',
    name='eventtype',
    create_type=False
)
scrapejobstatus = postgresql.ENUM(
    'PENDING', 'RUNNING', 'COMPLETED', 'FAILED', 'CANCELLED',
    name='scrapejobstatus',
    create_type=False
)


def upgrade() -> None:
    # Create enum types explicitly first
    companystatus.create(op.get_bind(), checkfirst=True)
    companysource.create(op.get_bind(), checkfirst=True)
    leadstatus.create(op.get_bind(), checkfirst=True)
    leadclassification.create(op.get_bind(), checkfirst=True)
    emailstatus.create(op.get_bind(), checkfirst=True)
    emailsequencestep.create(op.get_bind(), checkfirst=True)
    eventtype.create(op.get_bind(), checkfirst=True)
    scrapejobstatus.create(op.get_bind(), checkfirst=True)

    # Create users table
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default='true', nullable=False),
        sa.Column("is_superuser", sa.Boolean(), server_default='false', nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # Create companies table
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("website_url", sa.String(500), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("employee_count", sa.Integer(), nullable=True),
        sa.Column("open_vacancies", sa.Integer(), nullable=True),
        sa.Column("location", sa.String(255), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", companysource, nullable=False),
        sa.Column("source_url", sa.String(500), nullable=True),
        sa.Column("status", companystatus, nullable=False, server_default="NEW"),
        sa.Column("raw_data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_companies_domain", "companies", ["domain"], unique=True)
    op.create_index("ix_companies_source", "companies", ["source"])
    op.create_index("ix_companies_status", "companies", ["status"])

    # Create leads table
    op.create_table(
        "leads",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("company_id", sa.Integer(), nullable=False),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("job_title", sa.String(200), nullable=True),
        sa.Column("linkedin_url", sa.String(500), nullable=True),
        sa.Column("phone", sa.String(50), nullable=True),
        sa.Column("status", leadstatus, nullable=False, server_default="NEW"),
        sa.Column("icp_score", sa.Integer(), nullable=True),
        sa.Column("classification", leadclassification, nullable=False, server_default="UNSCORED"),
        sa.Column("score_breakdown", sa.JSON(), nullable=True),
        sa.Column("email_confidence", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("scored_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sequenced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_leads_company_id", "leads", ["company_id"])
    op.create_index("ix_leads_email", "leads", ["email"], unique=True)
    op.create_index("ix_leads_status", "leads", ["status"])
    op.create_index("ix_leads_classification", "leads", ["classification"])

    # Create emails table
    op.create_table(
        "emails",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body_text", sa.Text(), nullable=False),
        sa.Column("body_html", sa.Text(), nullable=True),
        sa.Column("sequence_step", emailsequencestep, nullable=False, server_default="1"),
        sa.Column("scheduled_day", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tracking_id", sa.String(36), nullable=False),
        sa.Column("message_id", sa.String(255), nullable=True),
        sa.Column("status", emailstatus, nullable=False, server_default="DRAFT"),
        sa.Column("open_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("click_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("bounced_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_emails_lead_id", "emails", ["lead_id"])
    op.create_index("ix_emails_tracking_id", "emails", ["tracking_id"], unique=True)
    op.create_index("ix_emails_status", "emails", ["status"])
    op.create_index("ix_emails_scheduled_at", "emails", ["scheduled_at"])

    # Create events table
    op.create_table(
        "events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email_id", sa.Integer(), nullable=False),
        sa.Column("event_type", eventtype, nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("referer", sa.String(500), nullable=True),
        sa.Column("clicked_url", sa.String(2000), nullable=True),
        sa.Column("extra_data", sa.JSON(), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["email_id"], ["emails.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_events_email_id", "events", ["email_id"])
    op.create_index("ix_events_event_type", "events", ["event_type"])
    op.create_index("ix_events_timestamp", "events", ["timestamp"])

    # Create scrape_jobs table
    op.create_table(
        "scrape_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source", companysource, nullable=False),
        sa.Column("keywords", sa.JSON(), nullable=True),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("status", scrapejobstatus, nullable=False, server_default="PENDING"),
        sa.Column("results_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("new_companies_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("celery_task_id", sa.String(255), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scrape_jobs_source", "scrape_jobs", ["source"])
    op.create_index("ix_scrape_jobs_status", "scrape_jobs", ["status"])


def downgrade() -> None:
    # Drop tables in reverse order (respecting foreign keys)
    op.drop_table("scrape_jobs")
    op.drop_table("events")
    op.drop_table("emails")
    op.drop_table("leads")
    op.drop_table("companies")
    op.drop_table("users")

    # Drop enum types
    scrapejobstatus.drop(op.get_bind(), checkfirst=True)
    eventtype.drop(op.get_bind(), checkfirst=True)
    emailsequencestep.drop(op.get_bind(), checkfirst=True)
    emailstatus.drop(op.get_bind(), checkfirst=True)
    leadclassification.drop(op.get_bind(), checkfirst=True)
    leadstatus.drop(op.get_bind(), checkfirst=True)
    companysource.drop(op.get_bind(), checkfirst=True)
    companystatus.drop(op.get_bind(), checkfirst=True)
