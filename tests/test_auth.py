"""Sign-up, invites and login."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from app.db.models import Invite
from tests.conftest import invite_member, make_settings, signup

PASSWORD = "correct-horse-battery"


def test_signup_creates_workspace_with_admin(client):
    account = signup(client, "Acme")
    assert account.role == "admin"
    assert account.tenant_id.startswith("acme-")
    me = client.get("/api/v1/auth/me", headers=account.headers).json()
    assert me["username"] == "acme-admin"


def test_signups_get_distinct_tenants_even_with_same_name(client):
    first = signup(client, "Acme")
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "workspace_name": "Acme",
            "username": "other",
            "email": "o@example.com",
            "password": PASSWORD,
        },
    )
    assert resp.json()["user"]["tenant_id"] != first.tenant_id


def test_signup_rejects_client_chosen_role_or_tenant(client):
    for extra in ({"role": "admin"}, {"tenant_id": "victim"}):
        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "workspace_name": "Xyz",
                "username": "mallory",
                "email": "m@example.com",
                "password": PASSWORD,
            }
            | extra,
        )
        assert resp.status_code == 422


def test_duplicate_username_conflicts(client):
    signup(client, "Acme")
    resp = client.post(
        "/api/v1/auth/signup",
        json={
            "workspace_name": "Other",
            "username": "acme-admin",
            "email": "new@example.com",
            "password": PASSWORD,
        },
    )
    assert resp.status_code == 409


def test_signup_can_be_disabled(database_url):
    from fastapi.testclient import TestClient

    from app.main import create_app

    with TestClient(create_app(make_settings(database_url, allow_public_signup=False))) as c:
        resp = c.post(
            "/api/v1/auth/signup",
            json={
                "workspace_name": "Xyz",
                "username": "x-admin",
                "email": "x@example.com",
                "password": PASSWORD,
            },
        )
        assert resp.status_code == 403


def test_login(client):
    signup(client, "Acme")
    ok = client.post("/api/v1/auth/login", json={"username": "acme-admin", "password": PASSWORD})
    assert ok.status_code == 200
    bad = client.post(
        "/api/v1/auth/login", json={"username": "acme-admin", "password": "nope-nope"}
    )
    assert bad.status_code == 401
    unknown = client.post("/api/v1/auth/login", json={"username": "ghost", "password": PASSWORD})
    assert unknown.status_code == 401
    assert bad.json() == unknown.json()  # no username enumeration


def test_invite_joins_inviters_tenant_with_invite_role(client):
    admin = signup(client, "Acme")
    member = invite_member(client, admin, "alice")
    assert (member.tenant_id, member.role) == (admin.tenant_id, "member")
    second_admin = invite_member(client, admin, "carol", role="admin")
    assert second_admin.role == "admin"


def test_invite_is_single_use(client):
    admin = signup(client, "Acme")
    code = client.post("/api/v1/invites", json={}, headers=admin.headers).json()["code"]
    body = {
        "invite_code": code,
        "username": "alice",
        "email": "a@example.com",
        "password": PASSWORD,
    }
    assert client.post("/api/v1/auth/join", json=body).status_code == 201
    reuse = body | {"username": "eve", "email": "e@example.com"}
    assert client.post("/api/v1/auth/join", json=reuse).status_code == 400


def test_expired_invite_is_rejected(client):
    admin = signup(client, "Acme")
    code = client.post("/api/v1/invites", json={}, headers=admin.headers).json()["code"]
    db = client.app.state.services.db

    async def expire() -> None:
        async with db.session() as session:
            past = datetime.now(UTC) - timedelta(minutes=1)
            await session.execute(update(Invite).where(Invite.code == code).values(expires_at=past))

    client.portal.call(expire)
    body = {
        "invite_code": code,
        "username": "alice",
        "email": "a@example.com",
        "password": PASSWORD,
    }
    assert client.post("/api/v1/auth/join", json=body).status_code == 400


def test_members_cannot_create_invites(client):
    admin = signup(client, "Acme")
    member = invite_member(client, admin, "alice")
    resp = client.post("/api/v1/invites", json={"role": "admin"}, headers=member.headers)
    assert resp.status_code == 403
