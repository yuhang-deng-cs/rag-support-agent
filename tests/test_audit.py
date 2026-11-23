"""Audit log: what gets recorded, who can read it, and (on PostgreSQL) that it is append-only."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import invite_member, signup, upload

PASSWORD = "correct-horse-battery"


def audit(client, account, **params):
    return client.get("/api/v1/audit", params=params, headers=account.headers)


def test_security_relevant_actions_are_recorded(client):
    admin = signup(client, "Acme")
    member = invite_member(client, admin, "bob")
    client.post("/api/v1/auth/login", json={"username": "bob", "password": "not-the-password"})
    client.post("/api/v1/auth/login", json={"username": "bob", "password": PASSWORD})
    doc = upload(client, admin, "faq.md", "Refunds take five business days.")
    client.delete(f"/api/v1/documents/{doc['id']}", headers=admin.headers)
    client.post(
        "/api/v1/tickets", json={"question": "Can I pay by invoice?"}, headers=member.headers
    )

    resp = audit(client, admin)
    assert resp.status_code == 200
    events = resp.json()
    assert {e["action"] for e in events} == {
        "workspace.created",
        "invite.created",
        "member.joined",
        "auth.login_failed",
        "auth.login",
        "document.uploaded",
        "document.deleted",
        "ticket.created",
    }
    assert resp.headers["X-Total-Count"] == str(len(events))
    assert [e["id"] for e in events] == sorted(
        (e["id"] for e in events), reverse=True
    )  # newest first

    failed = next(e for e in events if e["action"] == "auth.login_failed")
    assert failed["actor_username"] == "bob" and failed["detail"] == {"reason": "bad_password"}
    uploaded = next(e for e in events if e["action"] == "document.uploaded")
    assert uploaded["target_id"] == str(doc["id"]) and uploaded["detail"]["filename"] == "faq.md"
    assert all(e["request_id"] and e["ip"] for e in events)


def test_secrets_are_never_written_to_the_log(client):
    admin = signup(client, "Acme")
    code = client.post("/api/v1/invites", json={"role": "member"}, headers=admin.headers).json()[
        "code"
    ]
    raw = audit(client, admin).text
    assert code not in raw and PASSWORD not in raw


def test_audit_log_is_admin_only_and_tenant_scoped(client):
    acme, umbra = signup(client, "Acme"), signup(client, "Umbra")
    member = invite_member(client, acme, "bob")

    assert audit(client, member).status_code == 403
    assert client.get("/api/v1/audit").status_code == 401

    umbra_events = audit(client, umbra).json()
    assert [e["action"] for e in umbra_events] == ["workspace.created"]
    assert all(e["actor_username"] == "umbra-admin" for e in umbra_events)

    joined = audit(client, acme, action="member.joined").json()
    assert len(joined) == 1 and joined[0]["detail"] == {"role": "member"}
    assert len(audit(client, acme, limit=1).json()) == 1


@pytest.mark.postgres
def test_audit_log_is_append_only_on_postgres(client, settings):
    if settings.is_sqlite:
        pytest.skip("RLS is PostgreSQL-only")
    admin = signup(client, "Acme")
    db = client.app.state.services.db

    async def tamper() -> tuple[int, int, int]:
        async with db.tenant_session(admin.tenant_id) as session:
            updated = (await session.execute(text("UPDATE audit_events SET action = 'x'"))).rowcount
            deleted = (await session.execute(text("DELETE FROM audit_events"))).rowcount
            left = (await session.execute(text("SELECT count(*) FROM audit_events"))).scalar_one()
        return updated, deleted, left

    assert client.portal.call(tamper) == (0, 0, 1)
