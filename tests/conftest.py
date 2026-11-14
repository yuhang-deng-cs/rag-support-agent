"""Shared fixtures.

Every API test runs against SQLite, and also against PostgreSQL + pgvector when
TEST_DATABASE_URL points at a database where the app connects as an unprivileged role
(see infra/postgres/app_role.psql). CI runs both.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import Settings
from app.db.models import Base
from app.db.session import Database
from app.main import create_app

PG_URL = os.getenv("TEST_DATABASE_URL")


def make_settings(database_url: str, **overrides) -> Settings:
    values = {
        "app_env": "test",
        "database_url": database_url,
        "jwt_secret": "test-secret-" + "x" * 32,
        "embedding_provider": "hash",
        "llm_provider": "extractive",
        "retrieval_min_score": 0.15,
        "chunk_size": 400,
        "chunk_overlap": 60,
    } | overrides
    return Settings(_env_file=None, **values)


async def _reset_postgres(url: str) -> None:
    db = Database(url, null_pool=True)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await db.dispose()


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def database_url(request, tmp_path) -> str:
    if request.param == "sqlite":
        return f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}"
    if not PG_URL:
        pytest.skip("TEST_DATABASE_URL not set")
    asyncio.run(_reset_postgres(PG_URL))
    return PG_URL


@pytest.fixture
def settings(database_url: str) -> Settings:
    return make_settings(database_url)


@pytest.fixture
def client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as test_client:
        yield test_client


# --- API helpers --------------------------------------------------------------


@dataclass
class Account:
    username: str
    token: str
    tenant_id: str
    role: str
    headers: dict[str, str] = field(init=False)

    def __post_init__(self) -> None:
        self.headers = {"Authorization": f"Bearer {self.token}"}


def _account(payload: dict) -> Account:
    user = payload["user"]
    return Account(user["username"], payload["access_token"], user["tenant_id"], user["role"])


def signup(client: TestClient, name: str) -> Account:
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "workspace_name": name,
            "username": f"{name.lower()}-admin",
            "email": f"admin@{name.lower()}.example.com",
            "password": "correct-horse-battery",
        },
    )
    assert resp.status_code == 201, resp.text
    return _account(resp.json())


def invite_member(
    client: TestClient, admin: Account, username: str, role: str = "member"
) -> Account:
    code = client.post("/api/v1/invites", json={"role": role}, headers=admin.headers).json()["code"]
    resp = client.post(
        "/api/v1/auth/join",
        json={
            "invite_code": code,
            "username": username,
            "email": f"{username}@example.com",
            "password": "correct-horse-battery",
        },
    )
    assert resp.status_code == 201, resp.text
    return _account(resp.json())


def upload(client: TestClient, admin: Account, filename: str, content: str) -> dict:
    resp = client.post(
        "/api/v1/documents",
        files={"file": (filename, content.encode("utf-8"), "text/plain")},
        headers=admin.headers,
    )
    assert resp.status_code == 202, resp.text
    doc = client.get(f"/api/v1/documents/{resp.json()['id']}", headers=admin.headers).json()
    assert doc["status"] == "ready", doc  # inline ingestion has finished by now
    return doc


def parse_sse(body: str) -> list[tuple[str, dict]]:
    events = []
    for block in body.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


def ask(client: TestClient, account: Account, question: str) -> dict:
    resp = client.post("/api/v1/chat/stream", json={"question": question}, headers=account.headers)
    assert resp.status_code == 200, resp.text
    events = parse_sse(resp.text)
    by_name: dict = {}
    for name, data in events:
        by_name.setdefault(name, []).append(data)
    return {
        "events": [name for name, _ in events],
        "sources": by_name.get("sources", [{"sources": []}])[0]["sources"],
        "answer": "".join(d["text"] for d in by_name.get("token", [])),
        "done": by_name.get("done", [{}])[0],
    }


ACME_BILLING = """# Billing

Acme bills every workspace monthly in advance.
Annual plans can be refunded in full within 30 days of purchase.
Refunds are returned to the original payment method within 5 to 10 business days.
"""

UMBRA_SECRET = """# Internal incident INC-2291

Confidential. A misconfigured reminder job sent duplicate SMS reminders to 1,842 patients
of the Riverside clinic group. Riverside was credited $4,200.
"""
