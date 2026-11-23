"""Turn a Locust CSV + server timings into a Markdown table (and GitHub annotations in CI).

    python loadtest/summarize.py loadtest/out/run_stats.csv loadtest/out/server_timings.json \\
        --users 20 --chunks 20000
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import platform
from pathlib import Path


def _cpu() -> str:
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return f"{line.split(':', 1)[1].strip()} × {os.cpu_count()}"
    except OSError:
        pass
    return f"{platform.processor() or platform.machine()} × {os.cpu_count()}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stats_csv", type=Path)
    parser.add_argument("server_json", type=Path)
    parser.add_argument("--users", type=int, required=True)
    parser.add_argument("--chunks", type=int, required=True)
    parser.add_argument("--duration", default="60s")
    args = parser.parse_args()

    rows = [
        r for r in csv.DictReader(args.stats_csv.open()) if r["Name"] not in ("login", "Aggregated")
    ]
    server = json.loads(args.server_json.read_text())

    lines = [
        f"### Load test — {args.users} concurrent users, {args.duration}, "
        f"{args.chunks:,} extra chunks in the tenant",
        "",
        "| Endpoint | Requests | Failures | RPS | p50 ms | p95 ms | p99 ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r['Name']} | {r['Request Count']} | {r['Failure Count']} "
            f"| {float(r['Requests/s']):.1f} | {r['50%']} | {r['95%']} | {r['99%']} |"
        )
    lines += [
        "",
        "Server-side breakdown of `/search` (from the response timings):",
        "",
        "| Step | p50 ms | p95 ms | p99 ms |",
        "|---|---:|---:|---:|",
        f"| query embedding (bge-small, CPU) | {server['embed_ms']['p50']} "
        f"| {server['embed_ms']['p95']} | {server['embed_ms']['p99']} |",
        f"| vector search (pgvector HNSW, RLS) | {server['search_ms']['p50']} | "
        f"{server['search_ms']['p95']} | {server['search_ms']['p99']} |",
        "",
        f"Machine: {_cpu()}; one uvicorn worker; PostgreSQL 16 + pgvector on the same host.",
    ]
    print("\n".join(lines))

    if os.getenv("GITHUB_ACTIONS"):
        for r in rows:
            print(
                f"::notice title=load test {r['Name']}::p50={r['50%']}ms p95={r['95%']}ms "
                f"p99={r['99%']}ms rps={float(r['Requests/s']):.1f} failures={r['Failure Count']} "
                f"users={args.users} chunks={args.chunks}"
            )
        print(
            f"::notice title=load test server timings::embed p95={server['embed_ms']['p95']}ms "
            f"vector search p95={server['search_ms']['p95']}ms (p50 {server['search_ms']['p50']}ms)"
        )


if __name__ == "__main__":
    main()
