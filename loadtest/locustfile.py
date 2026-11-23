"""Load test as a logged-in workspace member.

    locust -f loadtest/locustfile.py --headless -u 20 -r 10 -t 60s --host http://127.0.0.1:8000 \\
        --csv loadtest/out/run

Traffic mix: 4x retrieval (`POST /search`) for every full answer (`POST /chat/stream`, read to
the end). Server-side timings from /search (query embedding vs. vector search) are collected and
written to SERVER_TIMINGS_OUT when the run stops. Run with RATE_LIMIT_ENABLED=false on the server.
"""

from __future__ import annotations

import json
import os
import random
from pathlib import Path

from locust import HttpUser, between, events, task

USERNAME = os.getenv("LOADTEST_USER", "acme-member")
PASSWORD = os.getenv("LOADTEST_PASSWORD", "demo-password")
QUESTIONS = [
    "How long do refunds take?",
    "How do I enable single sign-on?",
    "Which plans include priority support?",
    "How do I rotate an API key?",
    "What happens when an invoice payment fails?",
    "Can I export my data?",
    "How do I invite a teammate?",
    "Where are your data centres?",
    "What is the uptime commitment?",
    "How do I cancel my subscription?",
]
SERVER = {"embed_ms": [], "search_ms": []}


class Member(HttpUser):
    wait_time = between(0.1, 0.5)

    def on_start(self) -> None:
        resp = self.client.post(
            "/api/v1/auth/login", json={"username": USERNAME, "password": PASSWORD}, name="login"
        )
        resp.raise_for_status()
        self.client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"

    @task(4)
    def search(self) -> None:
        body = {"query": random.choice(QUESTIONS)}  # noqa: S311 - picks a test question
        with self.client.post(
            "/api/v1/search", json=body, name="POST /search", catch_response=True
        ) as r:
            if r.status_code != 200:
                r.failure(f"HTTP {r.status_code}")
                return
            data = r.json()
            SERVER["embed_ms"].append(data["embed_ms"])
            SERVER["search_ms"].append(data["search_ms"])

    @task(1)
    def chat(self) -> None:
        body = {"question": random.choice(QUESTIONS)}  # noqa: S311 - picks a test question
        with self.client.post(
            "/api/v1/chat/stream",
            json=body,
            name="POST /chat/stream (full answer)",
            catch_response=True,
        ) as r:
            if r.status_code != 200 or "event: done" not in r.text:
                r.failure(f"HTTP {r.status_code} or incomplete stream")


def _percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round(pct / 100 * (len(ordered) - 1)))
    return round(ordered[index], 2)


@events.test_stop.add_listener
def _dump_server_timings(environment, **_kwargs) -> None:
    out = Path(os.getenv("SERVER_TIMINGS_OUT", "loadtest/out/server_timings.json"))
    out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        name: {"count": len(vals), **{f"p{p}": _percentile(vals, p) for p in (50, 95, 99)}}
        for name, vals in SERVER.items()
    }
    out.write_text(json.dumps(summary, indent=2))
