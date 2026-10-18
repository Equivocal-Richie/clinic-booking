# Clinic Booking API

A REST API for a small clinic: patients view a doctor's free 30-minute slots for
a day, book one, cancel it, or reschedule it — with a hard guarantee that a slot
is never double-booked, even under concurrent requests.

Built with **FastAPI + SQLModel + PostgreSQL**, deployed on **Render** with a
**GitHub Actions** pipeline that tests every PR and deploys on merge.

- **Live API:** `https://<your-service>.onrender.com`  _(replace after first deploy)_
- **Interactive docs (Swagger):** `https://<your-service>.onrender.com/docs`
- **Health check:** `https://<your-service>.onrender.com/health`

> First request after idle may take ~30–60s — Render's free tier spins the
> service down when idle and wakes it on the next request.

---

## Table of contents

1. [Section 1 — System design](#section-1--system-design)
2. [API reference](#api-reference)
3. [Running locally](#running-locally)
4. [Testing](#testing)
5. [Section 3 — Deployment & CI/CD](#section-3--deployment--cicd)
6. [Ambiguities & decisions](#ambiguities--decisions)
7. [Limitations & next steps](#limitations--next-steps)
8. [Section 4 — AI reflection](#section-4--ai-reflection)

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
| **Migrations** (`alembic/`) | Versioned schema, including the partial unique index. |
| **Config** (`app/config.py`) | 12-factor settings from env vars (DB URL, timezone, slot length, lead time). |

### Data model

```mermaid
erDiagram
    DOCTOR ||--o{ WORKING_HOURS : has
    DOCTOR ||--o{ APPOINTMENT : receives
    PATIENT ||--o{ APPOINTMENT : books

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

---

## API reference

All error responses share one shape:

```json
{ "error": { "code": "slot_taken", "message": "That slot has just been booked by someone else" } }
```

### `POST /appointments` — book a slot
```json
{ "doctor_id": 1, "patient_id": 1, "start_time": "2026-10-26T09:00:00+03:00" }
```
`201` on success. Validates: doctor & patient exist, start is a real 30-min slot
inside the doctor's working hours on a working day, not in the past, and (bonus)
at least 60 minutes ahead.

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

### `GET /patients/{id}/appointments` _(bonus)_
Upcoming **booked** appointments, soonest first (cancelled/past excluded).

### Status-code strategy

| Code | When |
|---|---|
| `201` | Appointment created |
| `200` | Cancel / reschedule / reads |
| `422` | Request **shape** invalid (missing field, empty reason, bad date) — Pydantic |
| `400` | Request well-formed but breaks a **business rule** (past, outside hours, lead time) |
| `404` | Doctor / patient / appointment not found |
| `409` | Slot already taken, or illegal state transition (cancel an already-cancelled, reschedule a cancelled) |

### Edge cases handled

Past slots; the 60-minute lead rule; misaligned starts (e.g. 09:15); slots
outside working hours; the lunch-break gap; non-working days (empty availability,
not an error); the last slot of a block requiring the full 30 minutes to fit
(a block ending 17:00 yields a last slot at 16:30); double-cancel; reschedule of
a cancelled appointment; reschedule into an occupied slot (original preserved);
unknown doctor/patient/appointment; malformed date; timezone conversion between
clinic-local input and UTC storage; and the concurrent double-booking race.

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

**35 tests, ~99% coverage.** Three layers:

- **Unit** (`tests/unit/`) — the pure slot grid and timezone logic: boundaries,
  lunch gaps, off days, last-slot-must-fit, lead-time filtering. No DB, fast.
- **Integration** (`tests/integration/`) — every endpoint against a real
  Postgres: happy paths, all validation failures and status codes, the full
  cancel/reschedule lifecycle, and the bonus patient list.
- **Concurrency** (`tests/integration/test_concurrency.py`) — fires 20 real
  concurrent booking attempts at the same slot (each on its own connection) and
  asserts **exactly one succeeds** and the database ends with exactly one active
  row. This is the proof that the slot guarantee holds under load.

The test suite builds its schema by running the **Alembic migrations**, so every
run also verifies migrations apply cleanly and create the partial unique index.

---

## Section 3 — Deployment & CI/CD

**Platform:** Render (Dockerized web service + managed Postgres), defined as
infrastructure-as-code in [`render.yaml`](./render.yaml).

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

> **Alternative considered:** let Render auto-deploy on push to `main` and rely
> on branch protection to ensure tests passed first. Simpler (less YAML) but it
> decouples the deploy from the test result and trusts branch config rather than
> re-verifying — so I chose the gated pipeline above.

---

## Ambiguities & decisions

The brief invited judgement calls; here are the notable ones.

- **No authentication.** The brief doesn't mention it; I left it out deliberately
  rather than ship a half-built auth layer, and flagged it under next steps. In
  production this API must be authenticated.
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

---

## Limitations & next steps

- **Auth & roles** (patient vs. clinic staff) — the clearest gap.
- **Idempotency keys** on `POST /appointments` to make client retries safe.
- **Pagination** on patient appointment lists as data grows.
- **Rate limiting** and request logging/observability.
- **Doctor time-off / holidays** as a first-class concept (today, only recurring
  weekly hours exist).
- **Notifications** (email/SMS reminders) — a natural clinic feature.

---

## Section 4 — AI reflection

> The brief says AI use is expected and that honesty matters more than the answer.
> This reflects how the project was actually built. _(Richard: please read and
> adjust to your own voice/experience before submitting.)_

**1. What AI was used for across the four sections.** Scaffolding the project
layout; drafting the SQLModel models, the pure/impure service split, and the
Alembic setup; generating the first pass of the test suite (including the
concurrency test); writing the Dockerfile, `docker-compose`, `render.yaml`, and
the CI workflow; and drafting this README. I treated AI as a fast pair, not an
oracle — every piece was run and verified against a real Postgres before being
accepted.

**2. One example where AI improved the work.** Prompted with *"how do I guarantee
no double-booking across multiple workers without pre-generating slot rows?"*, AI
proposed a **partial unique index** (`... WHERE status = 'booked'`) rather than
application locks. That single idea shaped the whole design: it makes the
guarantee race-proof at the database, lets cancellations free a slot without
deleting rows, and makes reschedule a one-row update. It also flagged the
`postgres://` → `postgresql+psycopg://` driver gotcha that would otherwise have
broken the Render deploy.

**3. One example where AI output was wrong or incomplete, and how I caught it.**
While wiring the app, route introspection showed `include_router` apparently
adding *zero* routes, and the first instinct (mine and the tool's) was a Starlette
version bug — a Starlette pin was even applied. Running the app against a real
`TestClient` showed all six endpoints responding fine: the "missing routes" were
an artifact of this FastAPI version keeping included routers as a sub-router
object rather than flattening them. Lesson: trust an end-to-end check over
introspection. (Separately, a genuinely incompatible Starlette 1.x *was* caught
and pinned — but only functional testing distinguished the real problem from the
false alarm.)

**4. Two decisions made without AI, and why I trusted my own judgment.**
(a) **Deriving availability instead of storing slot rows** — a data-modelling
call grounded in knowing how pre-materialised schedules rot as hours change and
data grows; I wanted the schema to stay small as the clinic scales. (b) **Running
tests against real Postgres (not SQLite) and building the test schema from the
migrations** — because the whole correctness story depends on a Postgres-specific
partial index and `IntegrityError` behaviour that SQLite can't reproduce; testing
on SQLite would have been testing a fiction.
