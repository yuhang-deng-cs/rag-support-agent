"""Operational safeguards: rate limiting, pagination and request IDs."""

from __future__ import annotations

import asyncio

from fastapi.testclient import TestClient

from app.core.ratelimit import MemoryLimiter
from app.main import create_app
from tests.conftest import make_settings, signup, upload


def test_memory_limiter_allows_up_to_the_limit_per_window():
    limiter = MemoryLimiter()

    async def run() -> list[bool]:
        return [(await limiter.hit("k", limit=2)).allowed for _ in range(3)]

    assert asyncio.run(run()) == [True, True, False]


def test_login_is_rate_limited_per_ip_and_username(database_url):
    settings = make_settings(database_url, rate_limit_enabled=True, login_rate_per_minute=3)
    with TestClient(create_app(settings)) as client:
        signup(client, "Acme")
        wrong = {"username": "acme-admin", "password": "not-the-password"}
        codes = [client.post("/api/v1/auth/login", json=wrong).status_code for _ in range(3)]
        assert codes == [401, 401, 401]

        blocked = client.post("/api/v1/auth/login", json=wrong)
        assert blocked.status_code == 429
        assert int(blocked.headers["Retry-After"]) >= 1

        # a different username has its own budget, so one attacker cannot lock out everyone
        other = {"username": "someone-else", "password": "not-the-password"}
        assert client.post("/api/v1/auth/login", json=other).status_code == 401


def test_chat_is_rate_limited_per_user(database_url):
    settings = make_settings(database_url, rate_limit_enabled=True, chat_rate_per_minute=2)
    with TestClient(create_app(settings)) as client:
        admin = signup(client, "Acme")
        ask = {"question": "How long do refunds take?"}
        codes = [
            client.post("/api/v1/chat/stream", json=ask, headers=admin.headers).status_code
            for _ in range(3)
        ]
        assert codes == [200, 200, 429]


def test_documents_and_tickets_are_paginated(client):
    admin = signup(client, "Acme")
    for i in range(3):
        upload(client, admin, f"doc{i}.txt", f"Policy number {i}. Refunds take {i + 3} days.")

    page = client.get("/api/v1/documents?limit=2&offset=0", headers=admin.headers)
    assert page.status_code == 200
    assert len(page.json()) == 2 and page.headers["X-Total-Count"] == "3"
    rest = client.get("/api/v1/documents?limit=2&offset=2", headers=admin.headers).json()
    assert len(rest) == 1
    ids = {d["id"] for d in page.json()} | {d["id"] for d in rest}
    assert len(ids) == 3  # no overlap between pages

    assert client.get("/api/v1/documents?limit=500", headers=admin.headers).status_code == 422

    for i in range(2):
        client.post("/api/v1/tickets", json={"question": f"Question {i}?"}, headers=admin.headers)
    tickets = client.get("/api/v1/tickets?limit=1", headers=admin.headers)
    assert len(tickets.json()) == 1 and tickets.headers["X-Total-Count"] == "2"


def test_request_id_is_generated_or_echoed(client):
    generated = client.get("/api/v1/health").headers["X-Request-ID"]
    assert 1 <= len(generated) <= 64

    echoed = client.get("/api/v1/health", headers={"X-Request-ID": "trace-123"})
    assert echoed.headers["X-Request-ID"] == "trace-123"

    # malformed IDs (log injection, oversized) are replaced, never reflected
    hostile = client.get("/api/v1/health", headers={"X-Request-ID": "bad id\nINFO fake log line"})
    assert hostile.headers["X-Request-ID"] != "bad id\nINFO fake log line"
