<div align="center">

# RAG Support Agent

**A multi-tenant RAG support agent where PostgreSQL itself guarantees one customer can never retrieve another customer's documents.**

[![CI](https://github.com/yuhang-deng-cs/rag-support-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/yuhang-deng-cs/rag-support-agent/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-3776AB)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

English · [简体中文](README.zh-CN.md)

<img src="docs/images/acme.png" alt="Acme's agent answers a billing question with citations, then refuses a question about another tenant's incident" width="820">

<sub>Acme's agent answers from Acme's docs with citations — and finds nothing when asked about Umbra's confidential incident, even though it sits in the same database.</sub>

</div>

---

## Why this exists

Most multi-tenant RAG examples isolate customers with a `WHERE tenant_id = ?` in application code.
One forgotten filter, one ORM query written in a hurry, one prompt-injected tool call — and a vector
search happily returns another customer's data to the LLM.

This project treats tenant isolation as a **database invariant**, not a coding convention:

| Layer | What enforces it |
|---|---|
| **Identity** | The tenant comes only from a signed JWT, re-checked against the user row on every request. Request bodies that try to name a `tenant_id` are rejected (`422`). |
| **Application** | Every query on tenant data runs inside `Database.tenant_session(tenant_id)` and filters by tenant. |
| **Database** | PostgreSQL **Row-Level Security** with `FORCE ROW LEVEL SECURITY`. Each transaction pins `app.tenant_id`; the policy hides every other tenant's rows — even from a raw `SELECT *` with no `WHERE`. No tenant set ⇒ no rows (fails closed). |
| **Schema** | A composite foreign key makes it impossible for a chunk to point at another tenant's document. |

…and it **proves** it with an adversarial test suite that runs against a real PostgreSQL in CI.

## Features

- 🔒 **Tenant isolation enforced by Postgres RLS** — plus tests that bypass the app and query the DB directly
- 🧪 **Attack tests**: `alg:none` JWTs, wrong-key and tampered tokens, expired/deactivated users, cross-tenant IDs, tenant spoofing, prompt-injection documents
- 🔎 **Semantic search with pgvector** (HNSW index) — falls back to SQLite + NumPy for zero-setup local dev
- 🧠 **Runs fully offline**: local ONNX embeddings via [fastembed](https://github.com/qdrant/fastembed) and an extractive answer mode — no API key needed to try it
- 🔌 **Any OpenAI-compatible LLM** for generated answers: OpenAI, DeepSeek, Ollama, vLLM, LiteLLM, …
- 📎 **Cited, streamed answers** over SSE, with an **abstain guardrail** when retrieval confidence is low
- ✂️ **Context pruning** that trims retrieved chunks before the LLM call — with measured savings, not marketing numbers
- 🙋 **Human escalation**: unanswerable questions become tickets
- 👥 **Workspaces & invites**: sign-up creates a tenant + admin; teammates join with single-use invite codes
- 🚦 **Rate limiting** on login (per IP + username) and chat (per user), in-memory or shared via Redis, with `429` + `Retry-After`
- 📄 **Paginated lists** (`limit` / `offset`, total in `X-Total-Count`) and an **`X-Request-ID`** on every response, written to the access log
- 📊 **Reproducible evaluation** (`scripts/eval.py`) with a threshold sweep, run in CI

## Quick start

### Docker (recommended — gives you PostgreSQL + RLS)

```bash
git clone https://github.com/yuhang-deng-cs/rag-support-agent.git
cd rag-support-agent
docker compose up --build
```

Open <http://localhost:8000> and click a demo account (password `demo-password`):

| Account | Workspace | Try asking |
|---|---|---|
| `acme-member` | Acme Cloud (SaaS docs) | *How long do refunds take?* · *What caused the duplicate SMS incident at Riverside?* ← Umbra's data, must fail |
| `umbra-admin` | Umbra Health (clinic software) | *What caused the duplicate SMS incident at Riverside?* ← works here |

The header badge shows **RLS enforced** when the app is connected as a role that RLS applies to.

### Without Docker

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[local]"
cp .env.example .env
uvicorn app.main:app --reload
```

This uses SQLite (isolation enforced by the application layer only; the UI badge says so).
Point `DATABASE_URL` at PostgreSQL to get RLS — see [docs/security.md](docs/security.md#running-postgresql-safely).

### Use a real LLM

Answers are extractive (verbatim cited sentences) by default. For generated answers, set in `.env`:

```bash
LLM_PROVIDER=openai
LLM_BASE_URL=https://api.openai.com/v1     # or https://api.deepseek.com/v1, http://localhost:11434/v1 (Ollama), ...
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-...
```

## How isolation works

```mermaid
sequenceDiagram
    participant C as Client
    participant A as API (FastAPI)
    participant P as PostgreSQL (RLS)
    C->>A: POST /chat/stream  Authorization: Bearer JWT
    A->>A: verify JWT · load user · tenant = user.tenant_id
    A->>P: BEGIN · set_config('app.tenant_id', tenant, true)
    A->>P: SELECT ... ORDER BY embedding <=> :q LIMIT k
    Note over P: policy: tenant_id = current_setting('app.tenant_id')<br/>other tenants' rows are invisible
    P-->>A: only this tenant's chunks
    A-->>C: SSE: sources → context → tokens → done
```

The policy ([`app/db/rls.py`](app/db/rls.py)) applied to `documents`, `document_chunks` and `tickets`:

```sql
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks FORCE ROW LEVEL SECURITY;   -- applies to the table owner too
CREATE POLICY tenant_isolation ON document_chunks
  USING      (tenant_id = current_setting('app.tenant_id', true))
  WITH CHECK (tenant_id = current_setting('app.tenant_id', true));
```

RLS does not apply to superusers or `BYPASSRLS` roles, so the app connects as an unprivileged role
([`infra/postgres/app_role.psql`](infra/postgres/app_role.psql)) and reports its status at
`GET /api/v1/health`. When the RLS tests are run as a superuser, all of them fail — they really test the database.

Full threat model: [docs/security.md](docs/security.md).

## Evaluation

`python scripts/eval.py` seeds the two demo workspaces and asks 26 questions: 19 answerable, 4
cross-tenant (asking one tenant about the other's documents) and 3 off-topic.
Results with the default `BAAI/bge-small-en-v1.5` embeddings, `top_k=4`, `RETRIEVAL_MIN_SCORE=0.6`:

| Metric | Result |
|---|---|
| hit@k — expected document retrieved (answerable) | **100%** |
| cross-tenant leaks — any source from another tenant | **0%** |
| abstain — retrieved nothing for cross-tenant/off-topic | 71% |
| answer text still present after context pruning | 95% |
| context tokens saved by pruning | 37% |

The 29% of non-abstentions are questions where the agent retrieved a loosely related document of
**its own** tenant (e.g. Acme's SSO page for a HIPAA question) — never another tenant's.
`python scripts/eval.py --sweep` shows the precision/recall trade-off of the abstain threshold:

| min_score | hit@k | abstain | leaks |
|---|---|---|---|
| 0.50 | 100% | 43% | 0% |
| 0.60 | 100% | 71% | 0% |
| 0.65 | 84% | 100% | 0% |
| 0.70 | 68% | 100% | 0% |

The sample set is small and hand-written: treat these as a regression baseline, not a benchmark.

## API

Interactive docs at `/docs`. All endpoints are under `/api/v1`.

| Method | Path | Who | Description |
|---|---|---|---|
| `POST` | `/auth/signup` | public | Create a workspace (tenant); caller becomes its admin |
| `POST` | `/auth/join` | public | Join a workspace with a single-use invite code |
| `POST` | `/auth/login` | public | Get an access token (rate limited per IP + username) |
| `GET` | `/auth/me` | member | Current user |
| `POST` | `/invites` | admin | Create an invite (`member` or `admin`) |
| `POST` | `/documents` | admin | Upload `.txt` / `.md` / `.pdf` (202, processed in background) |
| `GET` | `/documents`, `/documents/{id}` | member | List (`?limit=&offset=`, total in `X-Total-Count`) / poll status |
| `DELETE` | `/documents/{id}` | admin | Delete a document and its chunks |
| `POST` | `/chat/stream` | member | Ask a question — SSE events `sources`, `context`, `token`, `done` (rate limited per user) |
| `POST`/`GET` | `/tickets` | member | Escalate a question / list escalations |
| `GET` | `/health` | public | Status, DB dialect, RLS status, providers |

```bash
TOKEN=$(curl -s localhost:8000/api/v1/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"acme-member","password":"demo-password"}' | jq -r .access_token)
curl -N localhost:8000/api/v1/chat/stream -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"question":"How long do refunds take?"}'
```

## Project layout

```text
app/
  api/            routes (auth, documents, chat, tickets), schemas, auth dependencies
  core/           settings, password hashing, JWT
  db/             models, sessions (tenant_session), RLS policies
  rag/            chunking, embeddings, retrieval, pruning, LLM providers, answer pipeline
  ingestion/      chunk → embed → store; optional Celery worker
  static/         dependency-free web UI
infra/postgres/   unprivileged app role for RLS
scripts/eval.py   retrieval / guardrail / pruning evaluation
tests/            API, attack, RLS and unit tests (SQLite + PostgreSQL)
```

## Development

```bash
pip install -e ".[dev,local]"
ruff check . && ruff format --check .
pytest                                          # SQLite
TEST_DATABASE_URL=postgresql://rag_app:...@localhost:5432/rag_test pytest   # + PostgreSQL & RLS tests
```

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Limitations & roadmap

Honest about what this is: a well-tested reference implementation, not a turnkey product.

- [ ] Alembic migrations (schema is currently created on startup)
- [ ] Hybrid search (BM25 + vectors) and reranking
- [x] Rate limiting (login + chat), pagination, request IDs
- [ ] Audit log
- [ ] Conversation memory / follow-up questions
- [ ] Larger evaluation set, including multilingual queries
- Context pruning is a lexical heuristic; the extractive mode is a fallback, not an LLM.

Ideas and PRs welcome — see the [issues](https://github.com/yuhang-deng-cs/rag-support-agent/issues).

## License

[MIT](LICENSE)
