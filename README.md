# Clinic Booking API

A REST API for a small clinic: patients view a doctor's free 30-minute slots for
a day, book one, cancel it, or reschedule it — with a hard guarantee that a slot
is never double-booked, even under concurrent requests.

Built with **FastAPI + SQLModel + PostgreSQL**, deployed on **Render** with a
**GitHub Actions** pipeline that tests every PR and deploys on merge.

Hardened with **JWT auth + refresh tokens and patient/staff role-based access
control**, **idempotent booking** (Idempotency-Key), **rate limiting**,
**paginated reads**, and **asynchronous email notifications** (Celery + Redis,
with appointment reminders) — see [Authentication & roles](#authentication--roles),
[Hardening features](#hardening-features), and [Notifications](#notifications-async).

- **Live API:** `https://clinic-booking-api-v0cj.onrender.com`
- **Interactive docs (Swagger):** `https://clinic-booking-api-v0cj.onrender.com/docs`
- **Health check:** `https://clinic-booking-api-v0cj.onrender.com/health`

> First request after idle may take ~30–60s — Render's free tier spins the
> service down when idle and wakes it on the next request.

---

## Table of contents

1. [Section 1 — System design](#section-1--system-design)
2. [Authentication & roles](#authentication--roles)
3. [Hardening features](#hardening-features)
4. [API reference](#api-reference)
5. [Running locally](#running-locally)
6. [Testing](#testing)
7. [Section 3 — Deployment & CI/CD](#section-3--deployment--cicd)
8. [Ambiguities & decisions](#ambiguities--decisions)
9. [Limitations & next steps](#limitations--next-steps)
10. [Section 4 — AI reflection](#section-4--ai-reflection)

---

## Section 1 — System design

### The scenario

> A clinic with 5 doctors. Each doctor has set working hours and works in
> 30-minute slots. Patients see which slots are free for a doctor on a day, book
> one, and that slot becomes unavailable to others. Patients can cancel (and
> reschedule). Starting small, but want to grow.

### Components

| Component | Responsibility |
|---|---|
| **API layer** (`app/api/`) | HTTP routing, request/response schemas, status codes. Thin — no business logic. |
| **Service layer** (`app/services/`) | All booking rules. `slots.py` is **pure** (no DB/HTTP) so the core logic is trivially testable; `availability.py` / `booking.py` wrap it with persistence. |
| **Models** (`app/models/`) | SQLModel tables + the partial unique index that guarantees slot exclusivity. |
| **Auth** (`app/security.py`, `app/api/deps.py`, `app/api/auth.py`) | JWT issuing/verification, bcrypt password hashing, and role guards (patient vs. staff). |
| **Cross-cutting** (`app/ratelimit.py`, `app/errors.py`) | Rate limiting and a single consistent error envelope for every failure. |
| **Notifications** (`app/notifications/`, `app/tasks.py`, `app/celery_app.py`) | Async email on book/cancel/reschedule + reminders, via Celery tasks on a Redis broker. |
| **Migrations** (`alembic/`) | Versioned schema (four revisions): core tables + partial unique index; users + idempotency keys; refresh tokens; appointment `reminder_sent_at`. |
| **Config** (`app/config.py`) | 12-factor settings from env vars (DB URL, timezone, slot length, lead time, JWT secret, rate limits, page sizes). |

### Data model

```mermaid
erDiagram
    DOCTOR ||--o{ WORKING_HOURS : has
    DOCTOR ||--o{ APPOINTMENT : receives
    PATIENT ||--o{ APPOINTMENT : books
    PATIENT ||--o| USER : "logs in as"
    USER ||--o{ IDEMPOTENCY_KEY : owns
    USER ||--o{ REFRESH_TOKEN : "holds"

    USER {
      int id PK
      string email UK
      string hashed_password
      enum role "patient|staff"
      int patient_id FK "null for staff"
      bool is_active
    }
    IDEMPOTENCY_KEY {
      int id PK
      int user_id FK
      string idem_key
      string request_fingerprint
      string status "processing|completed"
      int response_status
      string response_body
    }
    REFRESH_TOKEN {
      int id PK
      int user_id FK
      string token_hash "sha256"
      datetime expires_at
      bool revoked
    }
    DOCTOR {
      int id PK
      string name
      string specialty
    }
    WORKING_HOURS {
      int id PK
      int doctor_id FK
      int day_of_week "0=Mon..6=Sun"
      time start_time "clinic-local"
      time end_time   "clinic-local"
    }
    PATIENT {
      int id PK
      string name
      string email
      string phone
    }
    APPOINTMENT {
      int id PK
      int doctor_id FK
      int patient_id FK
      datetime start_at "UTC, tz-aware"
      int duration_minutes
      enum status "booked|cancelled|completed"
      string cancellation_reason
      datetime reminder_sent_at "null until reminded"
      datetime created_at
      datetime updated_at
    }
```

### Key decision 1 — Availability is *derived*, never stored

We do **not** pre-generate a row for every doctor × every 30-minute interval ×
every day. Instead we store only the *rules* (`working_hours`) and the *facts*
(`appointments`), and compute availability on demand:

```
available(doctor, date) = working-hours grid − active appointments − slots too soon to book
```

Why: pre-materialised slots grow without bound, are painful to regenerate when a
doctor's hours change, and bake a timezone-dependent grid into storage. Deriving
them keeps the schema tiny and makes "the clinic wants to grow" cheap (change
hours → availability just recomputes). The grid logic lives in one pure function
(`services/slots.py`), reused by **both** the availability endpoint and the
booking validator, so the two can never disagree about whether a slot is bookable.

### Key decision 2 — Slot exclusivity is enforced by the database

The single most important requirement is *"once booked, that slot must not be
available to others."* The race is real: two patients POST the same slot at the
same instant. We guarantee correctness with a **partial unique index**:

```sql
CREATE UNIQUE INDEX uq_active_appointment_slot
  ON appointments (doctor_id, start_at)
  WHERE status = 'booked';
```

- Two concurrent inserts for the same slot → the database lets exactly **one**
  commit; the other raises `IntegrityError`, which we map to **409 Conflict**.
- The `WHERE status = 'booked'` clause means a **cancelled** appointment is
  excluded from the index, so a freed slot becomes bookable again **without
  deleting history** (we keep the cancelled row and its reason for audit).
- **Reschedule** is just `UPDATE appointments SET start_at = :new WHERE id = :id`
  on the same row: the original slot frees atomically and the same index rejects
  the move if the destination is taken.

**Why not application-level checks or locks?** A check-then-insert in app code
has a time-of-check/time-of-use race. In-process locks (`threading.Lock`,
`asyncio.Lock`) are *useless here* because the app is deployed with multiple
gunicorn workers (and can scale to multiple instances) — a lock in one process
says nothing to another. The database is the only shared, authoritative arbiter,
so that is where the guarantee belongs. (`SELECT ... FOR UPDATE` and SERIALIZABLE
isolation would also work but add contention/complexity for no benefit here.)

### Key decision 3 — Store UTC, reason in clinic-local time

All timestamps are stored **timezone-aware in UTC**. Working hours are
wall-clock times interpreted in the clinic timezone (`Africa/Nairobi`, UTC+3).
An incoming `start_time` with an offset is respected; a naive one is interpreted
as clinic-local. This keeps storage unambiguous while matching how staff think
("book 2pm").

### Key decision 4 — Idempotent booking writes

POST is not idempotent by default, so a network retry or a double-click can send
the same booking twice. Clients may send an `Idempotency-Key` header; the first
request does the work and stores its response (scoped to the user), and any
replay with the same key returns that stored response instead of acting again.
The `(user_id, idem_key)` unique constraint is the race arbiter — identical to
the slot-exclusivity pattern — so even two simultaneous retries resolve to one
booking. A key reused with a *different* body is rejected (422); a key is
released if the first attempt failed, so a corrected retry can reuse it.

---

## Authentication & roles

Every data endpoint requires a **JWT bearer token** (`Authorization: Bearer
<token>`). Passwords are hashed with **bcrypt**; access tokens are signed HS256
with `SECRET_KEY` and are **short-lived (30 min)**.

**Refresh tokens** are long-lived (14 days), opaque, and **DB-backed** — only a
SHA-256 hash is stored, so a database leak exposes no usable token. They are
**rotated on every refresh** (the old one is revoked) and **revocable** via
logout. Presenting an already-rotated token is treated as reuse and revokes all
of that user's tokens defensively. `GET /auth/me` returns the current user.

Two roles:

- **patient** — linked to a Patient record; may book, cancel, reschedule and list
  **only their own** appointments.
- **staff** (clinical/reception) — may act across **all** patients and provision
  other staff accounts.

Flow: `POST /auth/register` (self-service patient signup) → `POST /auth/login`
(returns a token) → send the token on every other call. Staff accounts are
seeded or created by existing staff via `POST /auth/staff`.

**Demo credentials** (created by `scripts/seed.py`): patient
`patient@example.com` / `patientpass123`, staff `staff@clinic.test` /
`staffpass123`.

## Hardening features

| Feature | How | Why |
|---|---|---|
| **RBAC** | `get_current_user` + role guards on every route; patients forced to their own `patient_id` | Clinical data must be access-controlled |
| **Idempotent booking** | `Idempotency-Key` header + `(user_id, key)` unique row | Safe client retries without duplicate bookings |
| **Rate limiting** | slowapi: global `120/min` + `15/min` on booking, keyed by client IP (X-Forwarded-For aware) | Protect the service from spam/abuse |
| **Pagination** | `limit`/`offset` with `has_more` (fetch limit+1, no COUNT) on list reads | Fast reads as data grows |
| **Async notifications** | Celery tasks on a Redis broker; email on book/cancel/reschedule + reminders | Confirmations/reminders without slowing the request |
| **Consistent errors** | one `{"error":{code,message}}` envelope for domain, auth, and validation failures | Predictable client handling |

> Rate-limit note: the default limiter store is in-memory, i.e. **per worker**.
> For a hard global limit across workers/instances, set `RATE_LIMIT_STORAGE_URI`
> to a Redis URL — the same "shared guarantees need shared state" lesson as slot
> locking.

---

## Notifications (async)

Booking events send email **out of the request path** so the API stays fast and
a slow/unavailable mail server never blocks a booking.

- **Flow:** a successful `POST /appointments`, cancel, or reschedule enqueues a
  Celery task (`app/tasks.py`) on a **Redis** broker; a **worker** process runs
  it, loads the appointment/patient/doctor from the DB, builds the message
  (`app/notifications/messages.py`, pure/testable), and sends it over **Gmail
  SMTP** (`app/notifications/email.py`).
- **Reminders:** Celery **beat** runs `scan_and_send_reminders` on a schedule;
  it finds booked appointments starting within `REMINDER_LEAD_MINUTES` that
  haven't been reminded, emails them, and stamps `reminder_sent_at` so none is
  reminded twice.
- **Serialization safety:** tasks carry only JSON-serializable primitives (ids,
  ISO strings) and the Celery serializer is **JSON, never pickle** (pickle
  deserialization is an RCE vector). Tasks reload rich data from the DB.
- **Resilience:** enqueue is wrapped so a broker outage logs and is ignored —
  the booking already succeeded; email is best-effort. Sending is **gated by
  `NOTIFICATIONS_ENABLED`** (off by default, so dev/tests never send mail), and
  `NOTIFY_OVERRIDE_EMAIL` can redirect all mail to one inbox for testing.

**Config:** `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `NOTIFICATIONS_ENABLED`,
`SMTP_HOST`/`SMTP_PORT`/`SMTP_USERNAME`/`SMTP_PASSWORD` (a Gmail **App
Password**), `EMAIL_FROM`, `NOTIFY_OVERRIDE_EMAIL`, `REMINDER_LEAD_MINUTES`,
`REMINDER_SCAN_INTERVAL_MINUTES`.

Run the whole stack locally with `docker compose up --build` (adds `redis` and a
`worker` running `celery -A app.celery_app worker -B`).

---

## API reference

All data endpoints require `Authorization: Bearer <token>`. All error responses
share one shape:

```json
{ "error": { "code": "slot_taken", "message": "That slot has just been booked by someone else" } }
```

### `POST /auth/register` — patient self-signup
```json
{ "email": "jane@example.com", "password": "secretpw1", "name": "Jane", "phone": "+254..." }
```
Creates a linked Patient + patient User. `409` if the email is taken.

### `POST /auth/login` — obtain tokens
Form-encoded (OAuth2 password flow): `username=<email>&password=<password>` →
`{ "access_token": "...", "refresh_token": "...", "token_type": "bearer" }`.
`401` on bad credentials.

### `POST /auth/refresh` — rotate tokens
`{ "refresh_token": "..." }` → a new `{ access_token, refresh_token }`. The old
refresh token is revoked (rotation). `401` if the token is invalid, expired, or
already used.

### `POST /auth/logout` — revoke a refresh token
`{ "refresh_token": "..." }` → `204`. Idempotent (revoking an unknown/already
-revoked token still returns `204`).

### `GET /auth/me` — current user
Returns `{ id, email, role, patient_id }` for the bearer token. `401` if missing/invalid.

### `POST /auth/staff` — create a staff account _(staff only)_
`{ "email": "...", "password": "..." }` → `201`. `403` for non-staff.

### `POST /appointments` — book a slot
```json
{ "doctor_id": 1, "patient_id": 1, "start_time": "2026-10-26T09:00:00+03:00" }
```
Optional header `Idempotency-Key: <stable-id>` makes retries safe (see Key
decision 4). `201` on success. A **patient** may only book for their own
`patient_id` (else `403`); **staff** may book for any patient. Validates: doctor &
patient exist, start is a real 30-min slot inside the doctor's working hours on a
working day, not in the past, and (bonus) at least 60 minutes ahead.

### `GET /doctors/{id}/availability?date=YYYY-MM-DD`
Returns the available 30-minute slots for that doctor on that date (clinic tz):
```json
{
  "doctor_id": 1, "date": "2026-10-26", "slot_duration_minutes": 30,
  "available_slots": [{ "start_time": "2026-10-26T06:00:00Z", "end_time": "2026-10-26T06:30:00Z" }]
}
```

### `PATCH /appointments/{id}/cancel`
```json
{ "reason": "Patient unwell" }
```
Marks the appointment cancelled (slot becomes bookable again). `409` if already
cancelled, `404` if not found, `422` if reason is empty.

### `PATCH /appointments/{id}/reschedule`
```json
{ "start_time": "2026-10-26T10:30:00+03:00" }
```
Moves to a new slot, validated as a fresh booking; original frees atomically.
`409` if the appointment is cancelled or the target slot is taken.

### `GET /patients/{id}/appointments?limit=20&offset=0` _(bonus)_
Upcoming **booked** appointments, soonest first (cancelled/past excluded).
Patients may read only their own list; staff may read any. Paginated:
```json
{ "items": [ ... ], "limit": 20, "offset": 0, "has_more": false }
```

### Status-code strategy

| Code | When |
|---|---|
| `201` | Appointment / account created |
| `200` | Cancel / reschedule / login / reads |
| `422` | Request **shape** invalid (missing field, empty reason, bad date, bad limit) — Pydantic |
| `400` | Request well-formed but breaks a **business rule** (past, outside hours, lead time) |
| `401` | Missing or invalid token |
| `403` | Authenticated but not allowed (patient acting on another's data; non-staff hitting a staff route) |
| `404` | Doctor / patient / appointment not found |
| `409` | Slot already taken, or illegal state transition (cancel an already-cancelled, reschedule a cancelled) |
| `429` | Rate limit exceeded |

### Edge cases handled

Past slots; the 60-minute lead rule; misaligned starts (e.g. 09:15); slots
outside working hours; the lunch-break gap; non-working days (empty availability,
not an error); the last slot of a block requiring the full 30 minutes to fit
(a block ending 17:00 yields a last slot at 16:30); double-cancel; reschedule of
a cancelled appointment; reschedule into an occupied slot (original preserved);
unknown doctor/patient/appointment; malformed date; timezone conversion between
clinic-local input and UTC storage; the concurrent double-booking race; a
retried/duplicate POST collapsing to one booking via Idempotency-Key; and a
patient attempting to read or modify another patient's appointments (403).

---

## Running locally

### Option A — Docker (one command)
```bash
docker compose up --build
# API on http://localhost:8000  (migrations + seed run automatically)
# Swagger UI: http://localhost:8000/docs
```

### Option B — local Python + your own Postgres
```bash
uv venv && source .venv/bin/activate      # or: python -m venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"                 # or: pip install -e ".[dev]"
cp .env.example .env                        # edit DATABASE_URL to your Postgres
alembic upgrade head
python -m scripts.seed
uvicorn app.main:app --reload
```

---

## Testing

```bash
export DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/clinic_test
pytest --cov=app --cov-report=term-missing
```

**66 tests, ~97% coverage.** Layers:

- **Unit** (`tests/unit/`) — the pure slot grid and timezone logic: boundaries,
  lunch gaps, off days, last-slot-must-fit, lead-time filtering. No DB, fast.
- **Integration** (`tests/integration/`) — every endpoint against a real
  Postgres: happy paths, all validation failures and status codes, the full
  cancel/reschedule lifecycle, and the bonus patient list.
- **Concurrency** (`tests/integration/test_concurrency.py`) — fires 20 real
  concurrent booking attempts at the same slot (each on its own connection) and
  asserts **exactly one succeeds** and the database ends with exactly one active
  row. This is the proof that the slot guarantee holds under load.
- **Auth & RBAC** (`test_auth_rbac.py`) — register/login, 401 without a token,
  and patients blocked (403) from acting on other patients or staff routes.
- **Tokens** (`test_auth_tokens.py`) — `/auth/me`; refresh issues a working
  access token and rotates the refresh token; a reused/rotated token is rejected
  (401); logout revokes.
- **Notifications** (`test_notifications.py`) — Celery runs eagerly with SMTP
  mocked: book/cancel/reschedule each enqueue the right email; the reminder scan
  selects due appointments, dedupes, and skips far-off ones; SMTP is untouched
  when disabled.
- **Idempotency** (`test_idempotency.py`) — same key replays the original 201,
  different body is rejected, a failed attempt releases the key.
- **Pagination** (`test_pagination.py`) and **rate limiting**
  (`test_rate_limit.py`, self-contained with limits on).

The test suite builds its schema by running the **Alembic migrations**, so every
run also verifies migrations apply cleanly and create the partial unique index.

---

## Section 3 — Deployment & CI/CD

**Platform:** Render (Dockerized web service + managed Postgres + Redis + a
Celery worker), defined as infrastructure-as-code in [`render.yaml`](./render.yaml).

**Deploy trigger:** merges to **`main`**. Direct pushes to `main` should be
blocked by branch protection so all changes arrive via reviewed, test-passing PRs.

**Pipeline** ([`.github/workflows/ci.yml`](./.github/workflows/ci.yml)):

1. **On every pull request →** spin up a Postgres service and run the full test
   suite. This is a required status check, so a PR can't merge while red.
2. **On merge to `main` (push) →** run the suite again, and **only if it passes**
   call the Render **deploy hook** to ship the new revision.

So the flow is **test → gate → deploy**, all visible in one Actions run. Render's
own auto-deploy is turned **off** (`autoDeploy: false`) so the pipeline is the
single source of deployment truth, rather than trusting a push to deploy on its
own.

One secret is required in the GitHub repo: `RENDER_DEPLOY_HOOK_URL` (from the
Render service's *Settings → Deploy Hook*). The container's entrypoint runs
`alembic upgrade head` on every boot before serving, so deploys are
self-migrating.

**Notification services:** `render.yaml` also declares a **Redis** (Key Value)
instance and a **Celery worker** (`celery -A app.celery_app worker -B`, same
image, command overridden). The Postgres and Redis free tiers suffice, but
**Render worker services are a paid type** — so for a free deployment, keep
`NOTIFICATIONS_ENABLED=false` on the web service and run the worker locally
(`docker compose up`) or on another host, or add the paid worker to turn
notifications on. The SMTP credentials are set as **unsynced env vars**
(`sync: false`) so the Gmail App Password is entered in the dashboard, never
committed.

> **Alternative considered:** let Render auto-deploy on push to `main` and rely
> on branch protection to ensure tests passed first. Simpler (less YAML) but it
> decouples the deploy from the test result and trusts branch config rather than
> re-verifying — so I chose the gated pipeline above.

---

## Ambiguities & decisions

The brief invited judgement calls; here are the notable ones.

- **Authentication & RBAC are implemented** (JWT, patient/staff roles). The brief
  didn't require them; they were added deliberately to make the API production-shaped.
  Decision: patients self-register and are auto-linked to a Patient record; staff
  accounts are provisioned (seeded or by existing staff), not self-service.
- **Patients aren't blocked from overlapping across doctors.** The requirement is
  per-doctor slot exclusivity. A patient booking two different doctors at the same
  time is a real-world conflict but out of the stated scope — noted, not enforced.
- **Cancelled rows are kept, not deleted** — needed for the partial-index trick,
  the cancellation reason, and audit history.
- **Naive datetimes are treated as clinic-local**, not UTC — matches how staff
  phrase times; aware datetimes are respected as sent.
- **60-minute lead time is configurable** (`MIN_LEAD_MINUTES`, 0 disables) and is
  applied identically to availability and booking so they never disagree.
- **Slot length is stored per-appointment** (`duration_minutes`) even though it's
  fixed at 30 today — cheap insurance for "we want to grow".
- **Notifications use Celery + Redis** (durable queue, retries, scales), chosen
  over in-process `BackgroundTasks`; the trade-off is a Redis broker and a worker
  process to operate. The serializer is JSON (never pickle) for safety, and
  sending is gated off by default so nothing emails real patients by accident.

---

## Limitations & next steps

Auth/RBAC, idempotent booking, rate limiting, and pagination are **implemented**
(see [Hardening features](#hardening-features)). Remaining:

- **Redis-backed rate limiting** for a true cross-worker/instance global limit
  (in-memory today), plus request logging/observability.
- **Idempotency-key TTL / sweeper** so an interrupted request can't hold a key
  in `processing` forever.
- **Keyset (cursor) pagination** for very large lists (offset degrades deep in).
- **Doctor time-off / holidays** as a first-class concept (today, only recurring
  weekly hours exist).
- **SMS / push notifications** (email is implemented; SMS/push would reuse the
  same Celery task layer).
- **Dedicated Celery beat service** (today beat is embedded in the worker via
  `-B`; a separate beat avoids duplicate schedules when scaling workers).
- **Patient-level overlap prevention** across doctors (currently per-doctor only).

---

## Section 4 — AI reflection

The brief says AI use is expected and that honesty matters more than the answer,
so here is how I actually built this.

**1. What I used AI for across the four sections.**
I leaned on AI (Claude) a lot here, basically as a fast pair programmer, while I
kept hold of the design and the decisions. It helped me write up the system
design and data model, scaffold the project, and produce the models, service
layer, endpoints and tests. It also wrote the Dockerfile, docker-compose,
render.yaml and the GitHub Actions pipeline, and later the extra hardening I
decided to add (JWT auth and refresh tokens, RBAC, idempotent booking, rate
limiting, pagination, and the Celery/Redis notifications). I worked by telling it
what I wanted in plain language, reading every change, and running it against a
real Postgres before I accepted anything. I treated it as fast hands rather than
something to trust blindly.

**2. One example where AI improved my work.**
I asked how to stop two patients booking the same slot across multiple workers
without pre-generating a row for every slot. Instead of reaching for locks in the
app, it suggested a partial unique index (UNIQUE on `doctor_id, start_at` WHERE
`status = 'booked'`) and letting the database reject whoever loses the race, which
the API turns into a 409. That one idea shaped the whole design. Availability ends
up being calculated on the fly instead of stored, cancelling a slot frees it again
without deleting any history, and rescheduling becomes a single row update. It
also caught something that would have broken the deploy: Render gives you a
`postgres://` URL, but SQLAlchemy needs it as `postgresql+psycopg://`.

**3. One example where AI output was wrong or incomplete, and how I caught it.**
Partway through, a route check showed `include_router` apparently adding no routes,
and the AI decided it was a Starlette version bug and even pinned a downgrade. That
didn't feel right to me, so instead of trusting the check I had it actually run the
app with a `TestClient`. Every endpoint was there and working. The "missing routes"
were just how this version of FastAPI stores included routers, and the real issue
turned out to be a different Starlette incompatibility that only showed up when the
thing was running. After that I made a rule for the rest of the build: trust a
running service and a real database over introspection or the AI sounding
confident. That is also why I insisted the tests run on real Postgres and not
SQLite, since the whole double-booking guarantee relies on Postgres behaviour
SQLite can't copy.

**4. Two decisions I made without the AI, or against it.**
First, using Celery and Redis for the notifications. The AI actually recommended
the simpler in-process BackgroundTasks because it fits Render's free tier better.
I went with a Redis broker and a Celery worker anyway, because I wanted the
durable, retryable setup you would really run in production, and I was fine taking
on the extra infrastructure and cost for it.

Second, taking the work well past what the brief asked for. The assignment only
needed four endpoints. I decided it should look more like something you would
actually ship, with access control over what is basically health data, safe
retries, some protection against abuse, and proper notifications. The AI would
have happily stopped at the requirements. Deciding what "finished" really meant
was on me.
