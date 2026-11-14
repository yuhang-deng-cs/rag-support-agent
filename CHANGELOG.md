# Changelog

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
