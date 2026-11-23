# Changelog

## 0.4.0 — 2026-11-23

### Added
- Alembic migrations (`app/db/migrations`): the initial schema with pgvector, the HNSW index and
  RLS policies, then the audit log. The app upgrades on startup; databases created before
  migrations are stamped at the baseline automatically. Tests check that migrations match the
  models and run down and up again, on SQLite and PostgreSQL.
- Audit log (`audit_events`, `GET /api/v1/audit` for admins): workspace creation, joins, logins and
  failed logins, invites (never the code), uploads, deletions and tickets, with actor, IP and
  request ID. Tenant-isolated, and append-only on PostgreSQL (no UPDATE/DELETE policy).
- `POST /api/v1/search`: retrieval only, with `embed_ms` / `search_ms` and a `Server-Timing` header.
- Load test (`loadtest/`, `scripts/seed_bulk.py`, `.github/workflows/perf.yml`) against PostgreSQL
  + pgvector with a 20k-chunk tenant, published in the job summary.
- `APP_ENV=demo`, a Render Blueprint (`render.yaml`) and `docs/deploy.md`; the image honours `$PORT`.

### Changed
- The schema is created by migrations instead of `metadata.create_all()`.

## 0.3.0 — 2026-11-23

### Added
- Rate limiting for `/auth/login` (per client IP + username) and `/chat/stream` (per user), returning
  `429` with `Retry-After`. In-memory by default; `RATE_LIMIT_BACKEND=redis` shares counters across
  API replicas.
- `limit` / `offset` pagination on `GET /documents` and `GET /tickets`, with the total in
  `X-Total-Count`.
- `X-Request-ID` on every response (a well-formed incoming ID is reused, anything else replaced) and
  a structured access log line per API request.

## 0.2.0 — 2026-11-14

A rewrite focused on verifiable tenant isolation.

### Added
- PostgreSQL Row-Level Security on all tenant-owned tables, with an unprivileged app role and an
  RLS status check (`/api/v1/health`).
- Workspace sign-up, single-use invites, and per-request user re-validation.
- Adversarial test suite (forged/tampered/expired tokens, tenant spoofing, cross-tenant IDs,
  prompt injection) running on SQLite and PostgreSQL in CI.
- Local embeddings (fastembed), any OpenAI-compatible LLM, and an offline extractive answer mode.
- File uploads (.txt/.md/.pdf), recursive chunking with overlap, HNSW index.
- Abstain guardrail with human escalation tickets.
- `scripts/eval.py` with a threshold sweep; new dependency-free web UI.

### Changed
- Tenant is taken from the token only; request bodies naming a tenant are rejected.
- Ingestion runs in-process by default; Celery is optional.

### Removed
- Hard-coded intent router and simulated "action tool" responses.
- Mock keyword embeddings presented as semantic search.
