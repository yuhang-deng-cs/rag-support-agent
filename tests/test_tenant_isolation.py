"""Cross-tenant isolation through the public API."""

from __future__ import annotations

import pytest

from tests.conftest import ACME_BILLING, UMBRA_SECRET, ask, invite_member, signup, upload


@pytest.fixture
def two_tenants(client):
    acme = signup(client, "Acme")
    umbra = signup(client, "Umbra")
    acme_doc = upload(client, acme, "billing.md", ACME_BILLING)
    umbra_doc = upload(client, umbra, "incident.md", UMBRA_SECRET)
    return acme, umbra, acme_doc, umbra_doc


def test_each_tenant_answers_from_its_own_documents(client, two_tenants):
    acme, umbra, *_ = two_tenants

    acme_answer = ask(client, acme, "How long do refunds take?")
    assert acme_answer["done"]["answerable"] is True
    assert "5 to 10 business days" in acme_answer["answer"]
    assert {s["filename"] for s in acme_answer["sources"]} == {"billing.md"}

    umbra_answer = ask(client, umbra, "What happened with the Riverside SMS reminders?")
    assert "1,842 patients" in umbra_answer["answer"]


def test_cannot_retrieve_another_tenants_document(client, two_tenants):
    acme, *_ = two_tenants
    result = ask(client, acme, "What happened in incident INC-2291 with Riverside SMS reminders?")
    assert result["sources"] == []
    assert result["done"]["answerable"] is False
    assert "1,842" not in result["answer"]


def test_tenant_id_in_request_body_is_rejected(client, two_tenants):
    acme, umbra, *_ = two_tenants
    resp = client.post(
        "/api/v1/chat/stream",
        json={"question": "incident INC-2291", "tenant_id": umbra.tenant_id},
        headers=acme.headers,
    )
    assert resp.status_code == 422


def test_document_listing_is_scoped(client, two_tenants):
    acme, _, acme_doc, _ = two_tenants
    acme_ids = {d["id"] for d in client.get("/api/v1/documents", headers=acme.headers).json()}
    assert acme_ids == {acme_doc["id"]}


@pytest.mark.parametrize("method", ["get", "delete"])
def test_foreign_document_ids_look_nonexistent(client, two_tenants, method):
    acme, umbra, _, umbra_doc = two_tenants
    resp = getattr(client, method)(f"/api/v1/documents/{umbra_doc['id']}", headers=acme.headers)
    assert resp.status_code == 404
    # ...and the document is still there for its owner.
    assert (
        client.get(f"/api/v1/documents/{umbra_doc['id']}", headers=umbra.headers).status_code == 200
    )


def test_tickets_are_scoped(client, two_tenants):
    acme, umbra, *_ = two_tenants
    client.post("/api/v1/tickets", json={"question": "acme question"}, headers=acme.headers)
    client.post("/api/v1/tickets", json={"question": "umbra question"}, headers=umbra.headers)
    acme_tickets = client.get("/api/v1/tickets", headers=acme.headers).json()
    assert [t["question"] for t in acme_tickets] == ["acme question"]


def test_members_only_see_their_own_tickets(client):
    admin = signup(client, "Acme")
    alice = invite_member(client, admin, "alice")
    bob = invite_member(client, admin, "bob")
    client.post("/api/v1/tickets", json={"question": "from alice"}, headers=alice.headers)
    client.post("/api/v1/tickets", json={"question": "from bob"}, headers=bob.headers)

    assert [t["question"] for t in client.get("/api/v1/tickets", headers=bob.headers).json()] == [
        "from bob"
    ]
    assert len(client.get("/api/v1/tickets", headers=admin.headers).json()) == 2


def test_members_cannot_upload_or_delete(client):
    admin = signup(client, "Acme")
    member = invite_member(client, admin, "alice")
    doc = upload(client, admin, "billing.md", ACME_BILLING)

    resp = client.post(
        "/api/v1/documents",
        files={"file": ("x.txt", b"hello", "text/plain")},
        headers=member.headers,
    )
    assert resp.status_code == 403
    assert (
        client.delete(f"/api/v1/documents/{doc['id']}", headers=member.headers).status_code == 403
    )
