# Deploying a public demo

The app is one Docker image plus PostgreSQL with pgvector. On startup it runs the Alembic
migrations (tables, HNSW index, Row-Level Security policies) and, with `SEED_DEMO=true`, creates the
two demo workspaces. `APP_ENV=demo` keeps production rules (a real `JWT_SECRET` is required) while
allowing the demo seed.

## Option A — Render (one click, everything included)

1. Open <https://render.com/deploy?repo=https://github.com/yuhang-deng-cs/rag-support-agent>
   and sign in with GitHub.
2. Render reads [`render.yaml`](../render.yaml): a free Docker web service in Singapore and a free
   PostgreSQL 16 database. Click **Apply**.
3. The first build takes a few minutes (it bakes the embedding model into the image). When it is
   live, open `https://<service>.onrender.com/api/v1/health` — it should report
   `"database": "postgresql"` and `"row_level_security": "enforced"`.

Why RLS is enforced there: the app connects as the database owner Render creates, which is not a
superuser and has no `BYPASSRLS`, and every tenant table uses `FORCE ROW LEVEL SECURITY`, which
applies policies to the owner too.

Free-plan limits: the service sleeps after ~15 minutes without traffic (the next request wakes it
in about a minute) and the free database is deleted after 30 days. For a link that stays up, use
option B for the database.

## Option B — Render web service + Neon database (free, no expiry)

1. Create a project at <https://neon.tech> (region: Singapore or Sydney) and copy the connection
   string (`postgresql://...`). pgvector is available on Neon; the app runs
   `CREATE EXTENSION IF NOT EXISTS vector` itself.
2. Deploy with the button above, then in the Render dashboard set `DATABASE_URL` on the web service
   to the Neon string and delete the Render database.

Check `/api/v1/health` afterwards: `row_level_security` must be `enforced`. If it says `bypassed`,
the connection uses a role with `BYPASSRLS`; create an ordinary role (see
[`infra/postgres/app_role.psql`](../infra/postgres/app_role.psql)) and connect as that.

## Option C — any Docker host (Fly.io, Railway, a VPS)

```bash
docker build -t rag-support-agent .
docker run -p 8000:8000 \
  -e APP_ENV=demo -e SEED_DEMO=true \
  -e JWT_SECRET="$(python -c 'import secrets; print(secrets.token_urlsafe(48))')" \
  -e DATABASE_URL=postgresql://user:pass@host:5432/rag \
  rag-support-agent
```

The image listens on `$PORT` (default 8000). Behind a reverse proxy, set `FORWARDED_ALLOW_IPS` to
the proxy's address so rate limits and the audit log see real client IPs.

## Keeping a public demo tidy

Visitors can sign up new workspaces (that is part of the demo) and the demo admins can upload
documents. Uploads are capped by `MAX_UPLOAD_MB`, and logins, questions and searches are rate
limited. To reset the demo, drop the database tables (or recreate the free database) and restart:
migrations and the seed run again.
