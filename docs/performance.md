# Performance

Measured by [`.github/workflows/perf.yml`](../.github/workflows/perf.yml) — anyone can re-run it
(Actions → *Load test* → *Run workflow*) and get the same setup. Two runs on 2026-11-23 (same code;
shared GitHub runners vary, so both are published):

**Setup**: GitHub Actions `ubuntu-latest` runner · one uvicorn worker · PostgreSQL 16 + pgvector
(HNSW, cosine) in a service container on the same host · the app connects as an unprivileged role,
so **Row-Level Security is on** for every query · local `bge-small-en-v1.5` embeddings (fastembed,
CPU) · extractive answers (no external LLM call) · the demo tenant grown to **20,000 extra chunks**
with `scripts/seed_bulk.py` · Locust, **20 concurrent users**, 60 s after a 15 s warm-up, traffic mix
4 searches : 1 full answer.

| Run | Endpoint | p50 | p95 | p99 | Throughput | Failures |
|---|---|---:|---:|---:|---:|---:|
| [1](https://github.com/yuhang-deng-cs/rag-support-agent/actions/runs/45091973843) | `POST /search` (embed query + vector search) | 16 ms | **65 ms** | 130 ms | 45.8 req/s | 0 |
| [1](https://github.com/yuhang-deng-cs/rag-support-agent/actions/runs/45091973843) | `POST /chat/stream` (whole SSE answer, extractive) | 17 ms | 60 ms | 160 ms | 11.5 req/s | 0 |
| [2](https://github.com/yuhang-deng-cs/rag-support-agent/actions/runs/45092369216) | `POST /search` | 58 ms | **140 ms** | 230 ms | 39.5 req/s | 0 |
| [2](https://github.com/yuhang-deng-cs/rag-support-agent/actions/runs/45092369216) | `POST /chat/stream` | 63 ms | 180 ms | 270 ms | 9.6 req/s | 0 |

Server-side split of `/search` (from the `embed_ms` / `search_ms` fields):

| Step | p50 (run 1 / 2) | p95 (run 1 / 2) |
|---|---:|---:|
| Query embedding (bge-small, CPU) | — | 12.5 / 50.5 ms |
| Vector search (pgvector HNSW, with the RLS policy) | 5.2 / 13.7 ms | 35 / 40 ms |

## Reading the numbers

- The database part is small: half of all vector searches over 20k+ chunks finish in 5–14 ms, even
  with the RLS predicate on every row. Run 2's slower embedding step (CPU-bound) shows the runner
  itself was slower; quote the range, not the best run.
- The tail (p95/p99) comes mostly from one worker serving 20 users at once — requests queue behind
  each other. More uvicorn workers or replicas (rate limits then go to Redis:
  `RATE_LIMIT_BACKEND=redis`) would cut it.
- With a hosted LLM (`LLM_PROVIDER=openai`) the answer time is dominated by the model; `/chat/stream`
  sends the cited `sources` event before the first token, so the UI shows evidence immediately.
- Synthetic chunks have random vectors, so they never match a real question; they exist to make the
  HNSW index and table realistically sized.

## Reproduce locally

```bash
docker compose up -d db                          # PostgreSQL + pgvector
export DATABASE_URL=postgresql://rag_app:rag_app_dev_password@localhost:5432/rag
SEED_DEMO=true RATE_LIMIT_ENABLED=false uvicorn app.main:app &
python scripts/seed_bulk.py --tenant acme --chunks 20000
pip install locust
locust -f loadtest/locustfile.py --headless -u 20 -r 10 -t 60s --host http://127.0.0.1:8000 --csv loadtest/out/run
python loadtest/summarize.py loadtest/out/run_stats.csv loadtest/out/server_timings.json --users 20 --chunks 20000
```
