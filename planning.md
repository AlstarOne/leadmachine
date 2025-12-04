# LeadMachine - Implementation Plan

## Project Overview
A complete lead acquisition workflow system with 6 core steps: Scraping, Enrichment, Scoring, Personalization, Mailing, and Tracking.

**Target deployment:** Docker on VPS with Portainer + Traefik at `lm.allardvolker.nl`
**GitHub repo:** https://github.com/AlstarOne/leadmachine

---

## Technology Stack

| Component | Technology | Justification |
|-----------|------------|---------------|
| Backend | Python 3.12 + FastAPI | Async support, great for scraping, LLM integration |
| Database | PostgreSQL 16 | Robust relational DB for lead data |
| Task Queue | Celery + Redis | Background jobs (scraping, mailing) |
| Scraping | Playwright + BeautifulSoup | JavaScript rendering + HTML parsing |
| LLM | OpenAI API (GPT-4) | Email personalization with high quality output |
| Email Server | docker-mailserver | Self-hosted SMTP/IMAP with DKIM/SPF |
| Email Client | aiosmtplib + aioimaplib | Async SMTP/IMAP handling |
| Frontend | React + Tailwind | Simple admin dashboard |
| Auth | Username/Password + JWT | Secure dashboard access with hashed passwords |
| Testing | pytest + pytest-asyncio | Comprehensive test coverage |
| CI/CD | GitHub Actions | Automated testing on push |
| Deployment | Docker Compose | Single-command deployment |

---

## Database Schema Overview

```
companies (id, name, domain, industry, employee_count, open_vacancies, source, status, created_at)
leads (id, company_id, first_name, last_name, email, job_title, linkedin_url, icp_score, status, created_at)
emails (id, lead_id, sequence_step, subject, body_text, body_html, tracking_id, status, scheduled_at, sent_at, opened_at, clicked_at, replied_at)
events (id, email_id, event_type, timestamp, ip_address, user_agent, metadata)
scrape_jobs (id, source, keywords, status, started_at, completed_at, results_count)
```

---

## Implementation Phases

### PHASE 0: Project Foundation & Infrastructure
**Goal:** Establish project structure, Docker setup, CI/CD, and deploy empty app

#### Tasks:
1. Initialize Git repository and push to GitHub
2. Create Python project structure with Poetry
3. Set up FastAPI skeleton with health endpoint
4. Create PostgreSQL + Redis Docker setup
5. Configure Traefik labels for `lm.allardvolker.nl`
6. Set up GitHub Actions for CI
7. Create base Alembic migrations
8. Deploy to VPS and verify connectivity

#### Directory Structure:
```
leadmachine/
├── docker-compose.yml
├── docker-compose.prod.yml
├── Dockerfile
├── .env.example
├── .github/workflows/ci.yml
├── pyproject.toml
├── alembic/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   ├── schemas/
│   ├── api/
│   ├── services/
│   └── workers/
├── tests/
│   ├── conftest.py
│   ├── test_health.py
│   └── ...
└── frontend/
    └── ...
```

#### Tests (must pass):
- [ ] `test_health_endpoint` - GET /health returns 200
- [ ] `test_database_connection` - Can connect to PostgreSQL
- [ ] `test_redis_connection` - Can connect to Redis
- [ ] `test_docker_build` - Docker image builds successfully

#### Git Tag: `v0.1.0-foundation`

---

### PHASE 1: Data Models & Database
**Goal:** Complete database schema with all tables and relationships

#### Tasks:
1. Create SQLAlchemy models for all entities
2. Create Alembic migrations
3. Create Pydantic schemas for validation
4. Implement CRUD operations for all models
5. Create database seeding script for testing

#### Models to Create:
- `Company` (companies table)
- `Lead` (leads table with FK to Company)
- `Email` (emails table with FK to Lead)
- `Event` (events table with FK to Email)
- `ScrapeJob` (scrape_jobs table)
- `ScrapeConfig` (scrape_configs table for keywords/filters)

#### Tests (must pass):
- [ ] `test_company_crud` - Create, read, update, delete company
- [ ] `test_lead_crud` - Create, read, update, delete lead
- [ ] `test_email_crud` - Create, read, update, delete email
- [ ] `test_event_crud` - Create, read, update, delete event
- [ ] `test_lead_company_relationship` - Lead belongs to Company
- [ ] `test_email_lead_relationship` - Email belongs to Lead
- [ ] `test_status_transitions` - Valid status changes only
- [ ] `test_migrations_up_down` - Migrations can be applied and rolled back
- [ ] All Phase 0 tests still pass

#### Git Tag: `v0.2.0-models`

---

### PHASE 2: Scraping Engine (STAP 1)
**Goal:** Scrape companies from all sources (Indeed, KvK, LinkedIn, Techleap)

#### Tasks:
1. Create base scraper interface
2. Implement Indeed scraper (vacatures - 5+ openstaand)
3. Implement KvK scraper (nieuwe BV's in relevante sectoren)
4. Implement LinkedIn scraper (with proxy rotation + rate limiting)
5. Implement Techleap/Dealroom scraper (funded scale-ups)
6. Create deduplication logic (domain + fuzzy name matching)
7. Set up Celery task for scheduled scraping (daily at 06:00)
8. Create API endpoints to trigger/monitor scrapes
9. Implement proxy rotation for LinkedIn protection

#### Scrapers:
```python
class BaseScraper:
    async def scrape(self, keywords: list[str], filters: dict) -> list[CompanyRaw]

class IndeedScraper(BaseScraper): ...     # Vacatures, min 5+
class KvKScraper(BaseScraper): ...        # Nieuwe BV's
class LinkedInScraper(BaseScraper): ...   # With proxy rotation
class TechleapScraper(BaseScraper): ...   # Funded scale-ups
```

#### API Endpoints:
- `POST /api/scrape/start` - Start scrape job
- `GET /api/scrape/jobs` - List scrape jobs
- `GET /api/scrape/jobs/{id}` - Get job status/results
- `GET /api/companies` - List scraped companies
- `GET /api/companies/{id}` - Get company details

#### Tests (must pass):
- [ ] `test_indeed_scraper_parses_html` - Parses Indeed results correctly
- [ ] `test_kvk_scraper_parses_html` - Parses KvK results correctly
- [ ] `test_linkedin_scraper_parses_html` - Parses LinkedIn results correctly
- [ ] `test_techleap_scraper_parses_html` - Parses Techleap results correctly
- [ ] `test_deduplication_by_domain` - Same domain = same company
- [ ] `test_deduplication_by_name` - Fuzzy name matching
- [ ] `test_scrape_job_status_tracking` - Job status updates correctly
- [ ] `test_scrape_results_saved` - Companies saved to database
- [ ] `test_celery_task_runs` - Scrape task executes
- [ ] `test_api_start_scrape` - API endpoint works
- [ ] `test_rate_limiting` - Respects rate limits
- [ ] `test_proxy_rotation` - Proxies rotate for LinkedIn
- [ ] All Phase 0-1 tests still pass

#### Git Tag: `v0.3.0-scraping`

---

### PHASE 3: Enrichment Engine (STAP 2)
**Goal:** Enrich companies with contact details and email verification

#### Tasks:
1. Implement domain normalizer
2. Create DNS/MX record checker
3. Build website scraper for team/about pages
4. Implement email pattern generator
5. Create SMTP verification (optional, careful)
6. Build LinkedIn profile scraper (mock/careful)
7. Create Celery enrichment task
8. Create API endpoints for enrichment

#### Services:
```python
class DomainService:
    def normalize(domain: str) -> str
    def check_mx_records(domain: str) -> bool

class WebsiteScraper:
    async def find_team_page(domain: str) -> list[Person]
    async def find_contact_info(domain: str) -> ContactInfo

class EmailFinder:
    def generate_patterns(first_name: str, last_name: str, domain: str) -> list[str]
    async def verify_email(email: str) -> tuple[bool, int]  # valid, confidence
```

#### API Endpoints:
- `POST /api/enrich/start` - Start enrichment job
- `GET /api/enrich/jobs/{id}` - Get enrichment status
- `GET /api/leads` - List enriched leads
- `GET /api/leads/{id}` - Get lead details

#### Tests (must pass):
- [ ] `test_domain_normalizer` - www.example.com -> example.com
- [ ] `test_mx_record_check` - Detects valid email domains
- [ ] `test_team_page_scraper` - Extracts names from team pages
- [ ] `test_email_pattern_generation` - Generates correct patterns
- [ ] `test_email_verification` - SMTP check works (mock)
- [ ] `test_enrichment_saves_lead` - Lead created from company
- [ ] `test_no_email_status` - NO_EMAIL status when not found
- [ ] `test_enriched_status` - ENRICHED status when complete
- [ ] `test_api_enrich_endpoint` - API works correctly
- [ ] All Phase 0-2 tests still pass

#### Git Tag: `v0.4.0-enrichment`

---

### PHASE 4: Scoring Engine (STAP 3)
**Goal:** Score leads based on ICP criteria

#### Tasks:
1. Create scoring configuration system
2. Implement company size scorer
3. Implement industry match scorer
4. Implement growth signals scorer
5. Implement founder activity scorer
6. Implement location scorer
7. Create total score calculator
8. Create classification system (HOT/WARM/COOL/COLD)
9. Create API endpoints for scoring

#### Scoring Logic:
```python
class ICPScorer:
    def score_company_size(employee_count: int) -> int  # max 30
    def score_industry(industry: str) -> int  # max 25
    def score_growth(vacancies: int, has_funding: bool) -> int  # max 20
    def score_activity(linkedin_posts: int) -> int  # max 15
    def score_location(location: str) -> int  # max 10
    def calculate_total(lead: Lead) -> tuple[int, dict]  # score, breakdown
    def classify(score: int) -> str  # HOT/WARM/COOL/COLD
```

#### API Endpoints:
- `POST /api/score/calculate` - Score single lead
- `POST /api/score/batch` - Score all ENRICHED leads
- `GET /api/leads/qualified` - List qualified leads (score >= 60)
- `PUT /api/score/config` - Update scoring weights

#### Tests (must pass):
- [ ] `test_company_size_scoring` - Correct points per range
- [ ] `test_industry_scoring` - Exact match = 25, related = 15, etc.
- [ ] `test_growth_scoring` - Vacancy + funding calculation
- [ ] `test_activity_scoring` - LinkedIn posts scoring
- [ ] `test_location_scoring` - Randstad = 10, etc.
- [ ] `test_total_calculation` - Sum is correct
- [ ] `test_classification` - HOT >= 75, WARM >= 60, etc.
- [ ] `test_qualified_threshold` - Only >= 60 qualified
- [ ] `test_score_breakdown_saved` - Breakdown stored in DB
- [ ] `test_batch_scoring` - Multiple leads scored
- [ ] All Phase 0-3 tests still pass

#### Git Tag: `v0.5.0-scoring`

---

### PHASE 5: Email Personalization (STAP 4)
**Goal:** Generate personalized email sequences using OpenAI API

#### Tasks:
1. Set up OpenAI API integration (GPT-4o-mini for cost efficiency)
2. Create prompt templates for Dutch cold emails
3. Implement email generator service
4. Generate 4-email sequence per lead
5. Create email template storage and versioning
6. Create Celery task for batch generation
7. Create API endpoints for email management
8. Add token usage tracking and rate limiting

#### Services:
```python
class OpenAIService:
    async def generate(prompt: str, system_prompt: str) -> str
    def count_tokens(text: str) -> int

class EmailGenerator:
    async def generate_sequence(lead: Lead) -> list[Email]
    def build_prompt(lead: Lead, email_type: str) -> str
    # email_type: initial, followup1, followup2, breakup
```

#### Email Sequence:
1. Initial (day 0) - Personalized intro
2. Follow-up 1 (day 3) - Reference first mail
3. Follow-up 2 (day 7) - New angle
4. Breakup (day 14) - Final attempt

#### API Endpoints:
- `POST /api/emails/generate/{lead_id}` - Generate sequence for lead
- `POST /api/emails/generate/batch` - Generate for all qualified
- `GET /api/emails/{lead_id}` - Get email sequence for lead
- `PUT /api/emails/{email_id}` - Edit generated email
- `GET /api/emails/templates` - Get/manage templates

#### Tests (must pass):
- [ ] `test_openai_connection` - Can connect to OpenAI API
- [ ] `test_prompt_building` - Prompt includes all context
- [ ] `test_email_generation` - LLM generates valid Dutch email
- [ ] `test_email_max_100_words` - Email respects word limit
- [ ] `test_sequence_creation` - 4 emails created per lead
- [ ] `test_email_scheduling` - Correct scheduled_at dates (0, 3, 7, 14)
- [ ] `test_subject_generation` - Subject line generated
- [ ] `test_html_generation` - HTML version created
- [ ] `test_batch_generation` - Multiple leads processed
- [ ] `test_lead_status_sequenced` - Lead marked SEQUENCED
- [ ] `test_token_tracking` - Token usage logged
- [ ] All Phase 0-4 tests still pass

#### Git Tag: `v0.6.0-personalization`

---

### PHASE 6: Email Sending (STAP 5)
**Goal:** Send emails with proper timing, tracking, and self-hosted mail server

#### Tasks:
1. Set up docker-mailserver container with DKIM/SPF/DMARC
2. Configure DNS records documentation (MX, SPF, DKIM, DMARC)
3. Create SMTP service connecting to docker-mailserver
4. Implement rate limiting (max 50/day, warmup period)
5. Create tracking ID generator (UUID-based)
6. Implement tracking pixel injection
7. Implement link wrapping for click tracking
8. Create business hours checker (ma-vr, 9:00-17:00 CET)
9. Build email sender Celery task with 2-5 min random delays
10. Create bounce handling via webhook
11. Create API endpoints

#### Services:
```python
class SMTPService:
    async def send(to: str, subject: str, body_html: str, body_text: str) -> str

class EmailSender:
    def inject_tracking_pixel(html: str, tracking_id: str) -> str
    def wrap_links(html: str, tracking_id: str) -> str
    async def send_email(email: Email) -> bool

class SchedulerService:
    def is_business_hours() -> bool
    def get_next_send_slot() -> datetime
    def check_daily_limit() -> bool
```

#### API Endpoints:
- `POST /api/send/start` - Start sending job
- `POST /api/send/pause` - Pause sending
- `GET /api/send/status` - Get sending status
- `GET /api/send/queue` - View email queue
- `PUT /api/send/config` - Configure rate limits

#### Tests (must pass):
- [ ] `test_smtp_connection` - Can connect to SMTP server
- [ ] `test_tracking_id_unique` - All tracking IDs unique
- [ ] `test_tracking_pixel_injection` - Pixel in HTML
- [ ] `test_link_wrapping` - All links wrapped
- [ ] `test_business_hours_check` - Correct time detection
- [ ] `test_rate_limiting` - Respects daily limit
- [ ] `test_email_send_updates_status` - SENT status
- [ ] `test_bounce_handling` - BOUNCED status on failure
- [ ] `test_sequence_timing` - Correct day gaps
- [ ] `test_reply_stops_sequence` - No more emails after reply
- [ ] All Phase 0-5 tests still pass

#### Git Tag: `v0.7.0-sending`

---

### PHASE 7: Tracking System (STAP 6)
**Goal:** Track opens, clicks, and replies

#### Tasks:
1. Create tracking pixel endpoint
2. Create click redirect endpoint
3. Implement IMAP reply checker
4. Build event logging system
5. Create real-time stats aggregation
6. Create notification service (Slack/email)
7. Create Celery task for reply checking

#### Endpoints:
```
GET /t/o/{tracking_id}.gif  - Open tracking pixel
GET /t/c/{tracking_id}?url= - Click redirect
```

#### Services:
```python
class TrackingService:
    async def log_open(tracking_id: str, ip: str, user_agent: str)
    async def log_click(tracking_id: str, url: str, ip: str, user_agent: str)

class ReplyChecker:
    async def check_inbox() -> list[Reply]
    async def match_to_lead(from_email: str) -> Lead | None

class NotificationService:
    async def notify_reply(lead: Lead)
```

#### API Endpoints:
- `GET /api/tracking/stats` - Overall statistics
- `GET /api/tracking/lead/{id}` - Lead engagement stats
- `GET /api/tracking/events` - Event log

#### Tests (must pass):
- [ ] `test_open_tracking_pixel` - Returns 1x1 gif
- [ ] `test_open_logged` - Event created on open
- [ ] `test_click_redirect` - Redirects to original URL
- [ ] `test_click_logged` - Event created on click
- [ ] `test_imap_connection` - Can connect to IMAP
- [ ] `test_reply_detection` - Detects replies
- [ ] `test_reply_matches_lead` - Matches to correct lead
- [ ] `test_reply_stops_sequence` - Sequence halted
- [ ] `test_stats_aggregation` - Correct open/click rates
- [ ] `test_notification_sent` - Notification on reply
- [ ] All Phase 0-6 tests still pass

#### Git Tag: `v0.8.0-tracking`

---

### PHASE 8: Admin Dashboard
**Goal:** Web interface for managing the workflow with secure authentication

#### Tasks:
1. Set up React project with Vite + TypeScript
2. Create User model with hashed passwords (bcrypt)
3. Implement JWT authentication (access + refresh tokens)
4. Create login page with secure session handling
5. Build dashboard overview page with key metrics
6. Create companies list/detail views with filters
7. Create leads list/detail views with status filters
8. Create email sequence viewer/editor
9. Create scrape job management (start/stop/schedule)
10. Create settings/config page (scoring weights, rate limits)
11. Build real-time stats widgets (WebSocket updates)
12. Create Docker build for frontend (nginx serving static)

#### Pages:
- `/` - Dashboard with stats overview
- `/companies` - Company list with filters
- `/leads` - Lead list with status filters
- `/leads/{id}` - Lead detail with email sequence
- `/scrape` - Scrape job management
- `/settings` - Configuration

#### Tests (must pass):
- [ ] `test_frontend_build` - React app builds successfully
- [ ] `test_dashboard_loads` - Dashboard renders (authenticated)
- [ ] `test_user_registration` - Can create user with hashed password
- [ ] `test_login_returns_jwt` - Login returns access + refresh tokens
- [ ] `test_jwt_validation` - Valid JWT grants access
- [ ] `test_jwt_expiry` - Expired JWT is rejected
- [ ] `test_refresh_token` - Can refresh access token
- [ ] `test_protected_endpoints` - Unauthenticated requests rejected
- [ ] `test_company_list_api` - Company list loads (authenticated)
- [ ] `test_lead_list_api` - Lead list loads (authenticated)
- [ ] `test_stats_api` - Stats endpoint works
- [ ] `test_password_hashing` - Passwords properly hashed (bcrypt)
- [ ] All Phase 0-7 tests still pass

#### Git Tag: `v0.9.0-dashboard`

---

### PHASE 9: Production Hardening
**Goal:** Make application production-ready

#### Tasks:
1. Add comprehensive error handling
2. Implement request logging
3. Add Prometheus metrics
4. Create health check endpoints
5. Implement graceful shutdown
6. Add database connection pooling
7. Configure Traefik HTTPS
8. Set up backup strategy
9. Create deployment documentation
10. Security audit (input validation, SQL injection, XSS)

#### Health Endpoints:
- `GET /health` - Basic health
- `GET /health/ready` - All dependencies ready
- `GET /health/live` - Application alive
- `GET /metrics` - Prometheus metrics

#### Tests (must pass):
- [ ] `test_error_handling` - Errors return proper responses
- [ ] `test_input_validation` - Invalid input rejected
- [ ] `test_sql_injection_prevention` - SQL injection blocked
- [ ] `test_xss_prevention` - XSS blocked
- [ ] `test_rate_limiting_api` - API rate limits work
- [ ] `test_graceful_shutdown` - Clean shutdown
- [ ] `test_health_endpoints` - All health checks work
- [ ] `test_metrics_endpoint` - Metrics exposed
- [ ] All Phase 0-8 tests still pass

#### Git Tag: `v1.0.0-production`

---

### PHASE 10: Deployment & Documentation
**Goal:** Deploy to production and document everything

#### Tasks:
1. Final Docker Compose configuration
2. Create `.env.production` template
3. Set up Portainer stack
4. Configure Traefik routing
5. Verify SSL certificates
6. Create README.md with setup instructions
7. Create DEPLOYMENT.md
8. Create API documentation (auto-generated)
9. Final integration test on production
10. Tag release v1.0.0

#### Deployment Config:
```yaml
# Traefik labels for lm.allardvolker.nl
labels:
  - traefik.enable=true
  - traefik.http.routers.leadmachine.rule=Host(`lm.allardvolker.nl`)
  - traefik.http.routers.leadmachine.tls=true
  - traefik.http.routers.leadmachine.tls.certresolver=letsencrypt
```

#### Tests (must pass):
- [ ] `test_production_smoke` - App responds on production URL
- [ ] `test_ssl_certificate` - HTTPS works
- [ ] `test_full_workflow` - End-to-end workflow test
- [ ] All Phase 0-9 tests still pass

#### Git Tag: `v1.0.0`

---

## Docker Configuration

### docker-compose.yml (Development)
```yaml
services:
  api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://leadmachine:password@db:5432/leadmachine
      - REDIS_URL=redis://redis:6379/0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SMTP_HOST=mailserver
      - SMTP_PORT=25
    depends_on:
      - db
      - redis
    volumes:
      - ./src:/app/src

  worker:
    build: .
    command: celery -A src.workers worker -l info
    environment:
      - DATABASE_URL=postgresql://leadmachine:password@db:5432/leadmachine
      - REDIS_URL=redis://redis:6379/0
      - OPENAI_API_KEY=${OPENAI_API_KEY}
    depends_on:
      - db
      - redis

  beat:
    build: .
    command: celery -A src.workers beat -l info
    environment:
      - REDIS_URL=redis://redis:6379/0
    depends_on:
      - redis

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=leadmachine
      - POSTGRES_PASSWORD=password
      - POSTGRES_DB=leadmachine
    volumes:
      - postgres_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data

  mailserver:
    image: ghcr.io/docker-mailserver/docker-mailserver:latest
    hostname: mail.lm.allardvolker.nl
    ports:
      - "25:25"    # SMTP
      - "587:587"  # Submission
      - "993:993"  # IMAPS
    environment:
      - ENABLE_SPAMASSASSIN=0
      - ENABLE_CLAMAV=0
      - ENABLE_FAIL2BAN=0
      - ENABLE_POSTGREY=0
      - ONE_DIR=1
      - DMS_DEBUG=0
    volumes:
      - maildata:/var/mail
      - mailstate:/var/mail-state
      - maillogs:/var/log/mail
      - ./docker/mailserver/config:/tmp/docker-mailserver

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "3000:80"
    depends_on:
      - api

volumes:
  postgres_data:
  redis_data:
  maildata:
  mailstate:
  maillogs:
```

### docker-compose.prod.yml (Production with Traefik)
```yaml
services:
  api:
    image: ghcr.io/alstarone/leadmachine:latest
    labels:
      - traefik.enable=true
      - traefik.http.routers.leadmachine-api.rule=Host(`lm.allardvolker.nl`) && PathPrefix(`/api`)
      - traefik.http.routers.leadmachine-api.tls=true
      - traefik.http.routers.leadmachine-api.tls.certresolver=letsencrypt
      - traefik.http.services.leadmachine-api.loadbalancer.server.port=8000
      # Tracking endpoints (no /api prefix)
      - traefik.http.routers.leadmachine-tracking.rule=Host(`lm.allardvolker.nl`) && PathPrefix(`/t`)
      - traefik.http.routers.leadmachine-tracking.tls=true
      - traefik.http.routers.leadmachine-tracking.tls.certresolver=letsencrypt
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SMTP_HOST=mailserver
      - SMTP_PORT=25
      - JWT_SECRET=${JWT_SECRET}
    networks:
      - traefik
      - internal
    depends_on:
      - db
      - redis

  frontend:
    image: ghcr.io/alstarone/leadmachine-frontend:latest
    labels:
      - traefik.enable=true
      - traefik.http.routers.leadmachine-frontend.rule=Host(`lm.allardvolker.nl`)
      - traefik.http.routers.leadmachine-frontend.tls=true
      - traefik.http.routers.leadmachine-frontend.tls.certresolver=letsencrypt
      - traefik.http.services.leadmachine-frontend.loadbalancer.server.port=80
      - traefik.http.routers.leadmachine-frontend.priority=1
    networks:
      - traefik

  worker:
    image: ghcr.io/alstarone/leadmachine:latest
    command: celery -A src.workers worker -l info
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - OPENAI_API_KEY=${OPENAI_API_KEY}
      - SMTP_HOST=mailserver
    networks:
      - internal
    depends_on:
      - db
      - redis

  beat:
    image: ghcr.io/alstarone/leadmachine:latest
    command: celery -A src.workers beat -l info
    environment:
      - REDIS_URL=${REDIS_URL}
    networks:
      - internal
    depends_on:
      - redis

  db:
    image: postgres:16-alpine
    environment:
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
      - POSTGRES_DB=${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    networks:
      - internal

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    networks:
      - internal

  mailserver:
    image: ghcr.io/docker-mailserver/docker-mailserver:latest
    hostname: mail.lm.allardvolker.nl
    ports:
      - "25:25"
      - "587:587"
      - "993:993"
    environment:
      - ENABLE_SPAMASSASSIN=0
      - ENABLE_CLAMAV=0
      - ENABLE_FAIL2BAN=1
      - SSL_TYPE=letsencrypt
    volumes:
      - maildata:/var/mail
      - mailstate:/var/mail-state
      - maillogs:/var/log/mail
      - ./docker/mailserver/config:/tmp/docker-mailserver
      - /etc/letsencrypt:/etc/letsencrypt:ro
    networks:
      - internal

networks:
  traefik:
    external: true
  internal:

volumes:
  postgres_data:
  redis_data:
  maildata:
  mailstate:
  maillogs:
```

---

## GitHub Actions CI/CD

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16-alpine
        env:
          POSTGRES_PASSWORD: test
        options: >-
          --health-cmd pg_isready
          --health-interval 10s
          --health-timeout 5s
          --health-retries 5
      redis:
        image: redis:7-alpine

    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - name: Install dependencies
        run: pip install poetry && poetry install
      - name: Run tests
        run: poetry run pytest --cov=src
      - name: Upload coverage
        uses: codecov/codecov-action@v4

  build:
    runs-on: ubuntu-latest
    needs: test
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t leadmachine .
```

---

## Test Strategy

### Test Categories:
1. **Unit tests** - Individual functions/methods
2. **Integration tests** - Service interactions
3. **API tests** - Endpoint behavior
4. **E2E tests** - Full workflow tests

### Test Requirements:
- Minimum 80% code coverage
- All tests must pass before merging
- Tests run on every push via GitHub Actions
- Use pytest fixtures for database/redis setup
- Mock external services (OpenAI API, SMTP, IMAP, scraping targets)
- Use `responses` or `httpx-mock` for HTTP mocking
- Use `pytest-asyncio` for async test support

### Test Database:
- Use PostgreSQL in Docker for tests
- Reset database between test runs
- Use factories for test data generation

---

## Critical Files to Create/Modify

### Phase 0:
- `pyproject.toml`
- `Dockerfile`
- `docker-compose.yml`
- `docker-compose.prod.yml`
- `.env.example`
- `src/main.py`
- `src/config.py`
- `src/database.py`
- `.github/workflows/ci.yml`
- `tests/conftest.py`

### Phase 1:
- `src/models/__init__.py`
- `src/models/company.py`
- `src/models/lead.py`
- `src/models/email.py`
- `src/models/event.py`
- `src/models/user.py` (for auth)
- `src/schemas/*.py`
- `alembic/versions/*.py`

### Phase 2:
- `src/services/scrapers/base.py`
- `src/services/scrapers/indeed.py`
- `src/services/scrapers/kvk.py`
- `src/services/scrapers/linkedin.py`
- `src/services/scrapers/techleap.py`
- `src/services/scrapers/proxy_manager.py`
- `src/api/routes/scrape.py`
- `src/workers/scrape_tasks.py`

### Phase 3:
- `src/services/enrichment/domain.py`
- `src/services/enrichment/website.py`
- `src/services/enrichment/email_finder.py`
- `src/api/routes/enrich.py`
- `src/workers/enrich_tasks.py`

### Phase 4:
- `src/services/scoring/icp_scorer.py`
- `src/services/scoring/config.py`
- `src/api/routes/score.py`

### Phase 5:
- `src/services/llm/openai_service.py`
- `src/services/email/generator.py`
- `src/services/email/templates.py`
- `src/api/routes/emails.py`

### Phase 6:
- `src/services/email/sender.py`
- `src/services/email/smtp.py`
- `src/workers/send_tasks.py`
- `docker/mailserver/config/` (mailserver config)

### Phase 7:
- `src/api/routes/tracking.py`
- `src/services/tracking/tracker.py`
- `src/services/tracking/reply_checker.py`
- `src/workers/reply_tasks.py`

### Phase 8:
- `src/api/routes/auth.py`
- `src/services/auth/jwt_service.py`
- `src/services/auth/password.py`
- `frontend/package.json`
- `frontend/src/App.tsx`
- `frontend/src/pages/Login.tsx`
- `frontend/src/pages/Dashboard.tsx`
- `frontend/src/pages/Companies.tsx`
- `frontend/src/pages/Leads.tsx`
- `frontend/src/components/*.tsx`
- `frontend/Dockerfile`

### Phase 9-10:
- `src/middleware/error_handler.py`
- `src/middleware/logging.py`
- `src/middleware/rate_limit.py`
- `README.md`
- `DEPLOYMENT.md`
- `DNS_SETUP.md` (mail server DNS records)

---

## DNS Configuration Required

For the self-hosted mail server to work properly, you'll need these DNS records:

```
# MX Record
lm.allardvolker.nl.    MX    10 mail.lm.allardvolker.nl.

# A Record for mail server
mail.lm.allardvolker.nl.    A    <VPS_IP_ADDRESS>

# SPF Record
lm.allardvolker.nl.    TXT    "v=spf1 mx a:mail.lm.allardvolker.nl -all"

# DKIM Record (generated by docker-mailserver)
mail._domainkey.lm.allardvolker.nl.    TXT    "v=DKIM1; k=rsa; p=<GENERATED_KEY>"

# DMARC Record
_dmarc.lm.allardvolker.nl.    TXT    "v=DMARC1; p=quarantine; rua=mailto:postmaster@lm.allardvolker.nl"

# PTR Record (reverse DNS - configure via VPS provider)
<VPS_IP_ADDRESS>    PTR    mail.lm.allardvolker.nl
```

---

## Success Criteria

Each phase is complete when:
1. All tasks for the phase are implemented
2. All tests for the phase pass
3. All tests from previous phases still pass
4. Code is committed and pushed to GitHub
5. Phase is tagged with version number
6. Docker build succeeds

Final success:
- Application deployed to `lm.allardvolker.nl`
- All 10 phases complete with passing tests
- Full workflow works end-to-end
- Documentation complete
