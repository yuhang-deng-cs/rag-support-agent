"""Retrieval-only endpoint."""

from __future__ import annotations

from tests.conftest import ACME_BILLING, UMBRA_SECRET, signup, upload


def test_search_returns_scored_chunks_of_the_callers_tenant_only(client):
    acme, umbra = signup(client, "Acme"), signup(client, "Umbra")
    upload(client, acme, "billing.md", ACME_BILLING)
    upload(client, umbra, "incident.md", UMBRA_SECRET)

    resp = client.post(
        "/api/v1/search",
        json={"query": "How long do refunds take?", "top_k": 3},
        headers=acme.headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["results"] and all(r["filename"] == "billing.md" for r in body["results"])
    assert [r["score"] for r in body["results"]] == sorted(
        (r["score"] for r in body["results"]), reverse=True
    )
    assert body["embed_ms"] >= 0 and body["search_ms"] >= 0
    assert (
        "embed;dur=" in resp.headers["Server-Timing"] and "db;dur=" in resp.headers["Server-Timing"]
    )


def test_search_validates_input(client):
    acme = signup(client, "Acme")
    assert client.post("/api/v1/search", json={"query": "x"}).status_code == 401
    for bad in ({"query": ""}, {"query": "x", "top_k": 50}, {"query": "x", "tenant_id": "other"}):
        assert client.post("/api/v1/search", json=bad, headers=acme.headers).status_code == 422
