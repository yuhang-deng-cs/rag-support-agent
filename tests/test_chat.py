"""Streaming answer pipeline through the API."""

from __future__ import annotations

from tests.conftest import ACME_BILLING, ask, signup, upload


def test_stream_event_order_and_citations(client):
    admin = signup(client, "Acme")
    upload(client, admin, "billing.md", ACME_BILLING)

    result = ask(client, admin, "How long do refunds take?")

    assert result["events"][0] == "sources"
    assert result["events"][1] == "context"
    assert result["events"][-1] == "done"
    assert result["sources"][0]["filename"] == "billing.md"
    assert "[1]" in result["answer"]
    assert result["done"] == {"answerable": True, "generator": "extractive"}


def test_abstains_on_empty_knowledge_base(client):
    admin = signup(client, "Acme")
    result = ask(client, admin, "How long do refunds take?")
    assert result["sources"] == []
    assert result["done"]["answerable"] is False
    assert "escalate" in result["answer"]


def test_escalation_ticket_roundtrip(client):
    admin = signup(client, "Acme")
    created = client.post(
        "/api/v1/tickets", json={"question": "Can I pay by wire?"}, headers=admin.headers
    )
    assert created.status_code == 201
    assert created.json()["status"] == "open"
    assert client.get("/api/v1/tickets", headers=admin.headers).json()[0]["question"] == (
        "Can I pay by wire?"
    )


def test_upload_rejects_unsupported_and_oversized_files(client):
    admin = signup(client, "Acme")
    exe = client.post(
        "/api/v1/documents",
        files={"file": ("x.exe", b"MZ", "application/octet-stream")},
        headers=admin.headers,
    )
    assert exe.status_code == 415
    big = b"a" * (10 * 1024 * 1024 + 1)
    huge = client.post(
        "/api/v1/documents", files={"file": ("big.txt", big, "text/plain")}, headers=admin.headers
    )
    assert huge.status_code == 413


def test_health(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["row_level_security"] in {"enforced", "unsupported"}
