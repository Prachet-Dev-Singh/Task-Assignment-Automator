# Workplace Task Assignment System

An end-to-end, AI-powered workplace task assignment and workload balancing system. Inbound emails arrive, the Groq LLM extracts structured task requirements (title, skills, seniority, deadline, category), and a candidate scoring engine identifies the best-fit employee based on skill coverage, current workload availability, recency-weighted historical performance, and seniority fit. All decisions are persisted with plain-English reasoning and fed into a continuous feedback loop.

---

## 🏗️ Architecture & Core Components

```
                    ┌─────────────────┐
                    │  Inbound Email  │
                    │  (Mailgun/curl) │
                    └────────┬────────┘
                             │ POST /ingest
                             ▼
                    ┌─────────────────┐
                    │  FastAPI Server │
                    │   (asyncpg)     │
                    └────────┬────────┘
                             │ Enqueue
                             ▼
                    ┌─────────────────┐
                    │  Redis Broker   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │  Celery Worker  │ ◄──────► Groq LLM API (tool-use)
                    │   (psycopg2)    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   PostgreSQL    │ (5 Normalized Tables + GIN Indexes)
                    └─────────────────┘
```

1. **FastAPI HTTP API:** Serves query endpoints, ingests emails with idempotency (`message_id`), validates state transitions, and serves human-in-the-loop approvals.
2. **PostgreSQL Database:** Single source of truth across 5 tables (`emails`, `tasks`, `employees`, `assignments`, `task_history`). Uses GIN indexes on skills arrays and partial unique index on active assignments.
3. **Redis Broker & Result Store:** Asynchronous message queue between API ingestion and background extraction/scoring workers.
4. **Celery Worker:** Decoupled background processor chaining Stage 2 (LLM extraction), Stage 3 (candidate scoring), and Stage 4 (assignment).
5. **Groq LLM Engine:** Free-tier `llama-3.3-70b-versatile` running forced JSON Schema tool-use with `<email>` injection defense and dynamic vocabulary grounding.

---

## ⚡ Key Technical Features & Guarantees

- **Idempotent Ingestion:** Every inbound email requires a unique `message_id` (RFC 2822). Retried webhooks return the existing record without duplicating tasks.
- **Coverage Scoring (Not Jaccard):** Uses $|T \cap E| / |T|$ to measure skill coverage. A senior with 10 skills covering a 2-skill task is never penalized for broad expertise.
- **Urgency Weight-Shifting:** When a task deadline is within 24 hours, scoring shifts dynamically to **45% availability** to prioritize candidates with immediate bandwidth.
- **Concurrency Safety:** Uses blocking `SELECT ... FOR UPDATE` inside the assignment transaction and re-verifies employee capacity under lock to eliminate race conditions between multiple workers.
- **Continuous Feedback Loop:** Completing tasks writes performance records with auto-ratings (4.0 on-time / 2.0 late) or manual ratings (1.0–5.0). Future scoring runs automatically incorporate recency-weighted category history ($0.9^i$).
- **Low-Confidence Review Queue:** Tasks extracted with confidence $< 0.60$ transition to `review_required` for human verification via `POST /tasks/{id}/approve`.

---

## 🚀 Quick Start Guide

### 1. Environment Setup

Clone the repository and copy the environment configuration:

```bash
cd task-assignment-system
cp .env.example .env
```

Open `.env` and fill in:
- `GROQ_API_KEY`: Get a free key at [console.groq.com](https://console.groq.com)
- `WEBHOOK_SECRET`: A secure shared secret string for authenticating ingestion calls

### 2. Start Infrastructure with Docker

```bash
docker-compose up -d db redis
```

This starts PostgreSQL on port `5432` and Redis on port `6379`.

### 3. Install Python Dependencies

```bash
cd backend
python -m venv .venv
# On Windows:
.venv\Scripts\activate
# On Linux/macOS:
# source .venv/bin/activate

pip install -r requirements.txt
```

### 4. Run Migrations & Seed Canonical Employees

```bash
# Apply database schema
alembic upgrade head

# Seed 10 canonical employees (across junior, mid, senior, lead)
psql postgresql://user:pass@localhost:5432/taskdb -f tests/fixtures/seed_employees.sql
```

### 5. Launch the Application

In Terminal 1 (API Server):
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

In Terminal 2 (Background Celery Worker):
```bash
celery -A worker.celery_app worker --loglevel=info
```

API documentation and interactive Swagger UI are available at:
`http://localhost:8000/docs`

---

## 🧪 Testing Strategy

Run the complete automated test suite:

```bash
# Run all 28 unit tests
python -m pytest tests/unit -v

# Run integration tests (HTTP pipeline, constraints, feedback loop)
python -m pytest tests/integration -v

# Run entire test suite
python -m pytest tests/ -v
```

### Standalone CLI Assignment Runner
You can test extraction, scoring, and assignment on any raw email fixture without starting the full stack:

```bash
python scripts/test_assign.py --email tests/fixtures/emails/clear_task.txt
python scripts/test_assign.py --email tests/fixtures/emails/urgent.txt
```

### Opt-in Live Extractor Evaluation
To run live precision and recall benchmarking against the 10 labelled eval datasets using your real `GROQ_API_KEY`:

```bash
python -m pytest tests/eval/ --live -v -s
```

---

## 📡 API Reference Surface

| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/health` | Liveness check verifying DB & Redis connectivity | Public |
| `POST` | `/ingest` | Ingest email payload asynchronously; returns `email_id` | `X-Webhook-Secret` |
| `POST` | `/ingest/mailgun` | Mailgun inbound routing webhook receiver | Mailgun HMAC |
| `GET` | `/emails/{id}` | Poll email processing status and list extracted task IDs | Public |
| `GET` | `/tasks` | List tasks (filters: `email_id`, `status`, `priority`) | Public |
| `GET` | `/tasks/{id}` | Single task with active assignment and score breakdown | Public |
| `PATCH`| `/tasks/{id}/status` | Validated state transition (`in_progress`, `completed`, `cancelled`, `reassigned`) | Public |
| `POST` | `/tasks/{id}/approve`| Approve a `review_required` task to trigger assignment | Public |
| `POST` | `/tasks/{id}/rate` | Submit manual 1.0–5.0 rating for a completed task | Public |
| `GET` | `/employees` | List all employees with live active task count | Public |
| `POST` | `/employees` | Create employee record | Public |
| `PATCH`| `/employees/{id}` | Update skills, capacity, or availability (OOO flag) | Public |
| `GET` | `/assignments` | List assignments (filters: `task_id`, `employee_id`, `status`, dates) | Public |
| `GET` | `/assignments/{id}` | Full assignment details with `score_breakdown` JSON | Public |

---

## 📁 Repository Structure

```
task-assignment-system/
├── docker-compose.yml              # Local Postgres 16 and Redis 7 services
├── .env.example                    # Template environment variables
├── README.md                       # Complete documentation and quickstart
└── backend/
    ├── requirements.txt            # Production dependencies
    ├── Dockerfile                  # Container buildfile
    ├── alembic.ini                 # Database migration config
    ├── conftest.py                 # Pytest fixtures and CLI options
    ├── app/
    │   ├── main.py                 # FastAPI app entry point & /health
    │   ├── config.py               # Pydantic BaseSettings + category vocabulary
    │   ├── database.py             # Dual asyncpg & psycopg2 database session engines
    │   ├── logging_config.py       # Structured JSON logging (structlog)
    │   ├── models/                 # SQLAlchemy ORM definitions
    │   │   ├── enums.py            # TaskStatus, ACTIVE_TASK_STATUSES, VALID_TRANSITIONS
    │   │   ├── email.py            # emails table + message_id unique constraint
    │   │   ├── task.py             # tasks table + position unique constraint
    │   │   ├── employee.py         # employees table
    │   │   ├── assignment.py       # assignments table
    │   │   └── task_history.py     # task_history table
    │   ├── schemas/                # Pydantic request / response contracts
    │   ├── routers/                # Thin route delegates (ingest, emails, tasks, employees, assignments)
    │   └── services/               # Core business logic
    │       ├── extractor.py        # Groq tool-use task extraction with injection defense
    │       ├── scorer.py           # 4-signal candidate scoring with coverage metric
    │       ├── assigner.py         # Assignment engine with SELECT FOR UPDATE row locking
    │       └── tracker.py          # Lifecycle status transitions, auto-rating, reassignment
    ├── worker/
    │   ├── celery_app.py           # Celery broker & backend setup
    │   └── tasks.py                # process_email and assign_task background jobs
    ├── migrations/                 # Alembic migration scripts
    ├── scripts/
    │   └── test_assign.py          # Standalone CLI test script
    └── tests/
        ├── fixtures/               # Seed SQL & 8 email test fixtures
        ├── eval/                   # 10 labelled eval cases & live accuracy test
        ├── unit/                   # 28 isolated unit tests
        └── integration/            # Full HTTP & pipeline integration tests
```
