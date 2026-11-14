# Contributing

Thanks for helping! Bug reports, docs fixes and features are all welcome.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev,local]"
pytest
```

## Running the PostgreSQL / RLS tests

The test suite runs every API test against SQLite, and additionally against PostgreSQL when
`TEST_DATABASE_URL` is set. Connect as an **unprivileged** role, otherwise RLS is bypassed and the
RLS tests fail (by design):

```bash
docker run -d --name rag-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=rag_test -p 5432:5432 pgvector/pgvector:pg16
psql -h localhost -U postgres -d rag_test -v app_user=rag_app -v app_password=rag_app \
     -f infra/postgres/app_role.psql
TEST_DATABASE_URL=postgresql://rag_app:rag_app@localhost:5432/rag_test pytest
```

## Guidelines

- `ruff check . && ruff format .` before committing; CI enforces both.
- Add tests with every behaviour change. Changes to data access need a test that runs on PostgreSQL.
- **New tenant-owned table?** Give it a `tenant_id` column, add it to `TENANT_OWNED_TABLES` in
  `app/db/models.py` (that applies the RLS policy), access it only through
  `Database.tenant_session`, and extend `tests/test_postgres_rls.py`.
- If you change retrieval, chunking or pruning, run `python scripts/eval.py` and mention the
  before/after numbers in the PR.
- Keep PRs focused; use [Conventional Commits](https://www.conventionalcommits.org/) style messages.
