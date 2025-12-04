"""Celery application configuration."""

from celery import Celery
from celery.schedules import crontab

from src.config import get_settings

settings = get_settings()

celery_app = Celery(
    "leadmachine",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "src.workers.scrape_tasks",
        "src.workers.enrich_tasks",
        # "src.workers.send_tasks",
        # "src.workers.reply_tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Amsterdam",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max per task
    worker_prefetch_multiplier=1,
    worker_concurrency=4,
)

# Beat schedule for periodic tasks
celery_app.conf.beat_schedule = {
    # Scraping jobs - daily at 06:00
    "daily-scrape": {
        "task": "src.workers.scrape_tasks.run_daily_scrape",
        "schedule": crontab(hour=6, minute=0),
    },
    # Enrichment - daily at 08:00
    "daily-enrich": {
        "task": "src.workers.enrich_tasks.run_daily_enrichment",
        "schedule": crontab(hour=8, minute=0),
    },
    # Reply checking - every 30 minutes
    # "check-replies": {
    #     "task": "src.workers.reply_tasks.check_inbox",
    #     "schedule": crontab(minute="*/30"),
    # },
}
