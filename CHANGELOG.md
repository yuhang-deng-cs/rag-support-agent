# Changelog

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
