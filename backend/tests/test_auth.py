"""Signup, login, and the protected-route check.

The interesting cases are the ones where the failure has to be a rejection
rather than a 500. A wrong password that raises instead of returning 401 tells
an attacker the username exists, and a malformed token that crashes tells them
the difference between "no such user" and "bad signature".
"""

import pytest

pytestmark = pytest.mark.asyncio


async def test_signup_returns_token_and_user(client):
    resp = await client.post(
        "/auth/signup", json={"username": "newcomer", "password": "supersecret123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "newcomer"
    assert body["access_token"]
    assert body["token_type"] == "bearer"
    # The hash must never travel back out, at either level.
    assert "password" not in body
    assert "password_hash" not in body
    assert "password_hash" not in body["user"]


async def test_signup_rejects_duplicate_username(client, db_session):
    from app.services import auth_service

    await auth_service.create_user(db_session, "taken", "supersecret123")
    await db_session.commit()

    resp = await client.post(
        "/auth/signup", json={"username": "taken", "password": "supersecret123"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "USERNAME_TAKEN"


async def test_signup_rejects_short_password(client):
    resp = await client.post(
        "/auth/signup", json={"username": "tiny", "password": "short"}
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_login_succeeds(client, user_factory):
    await user_factory(username="loginuser")
    resp = await client.post(
        "/auth/login", json={"username": "loginuser", "password": "supersecret123"}
    )
    assert resp.status_code == 200
    assert resp.json()["access_token"]


async def test_login_rejects_wrong_password(client, user_factory):
    await user_factory(username="realuser")
    resp = await client.post(
        "/auth/login", json={"username": "realuser", "password": "wrongpassword"}
    )
    assert resp.status_code == 401
    assert "access_token" not in resp.json()


async def test_login_of_unknown_user_is_indistinguishable(client):
    """A missing username must not be distinguishable from a wrong password.

    If these differ in status code, the login form becomes a username oracle:
    anyone can enumerate who has an account.
    """
    resp = await client.post(
        "/auth/login", json={"username": "ghost", "password": "whatever123"}
    )
    assert resp.status_code == 401

    await client.post("/auth/signup", json={"username": "ghosty", "password": "supersecret123"})
    wrong = await client.post(
        "/auth/login", json={"username": "ghosty", "password": "wrongpassword"}
    )
    assert resp.status_code == wrong.status_code
    assert resp.json()["error"]["code"] == wrong.json()["error"]["code"]


async def test_password_is_hashed_not_stored(client, db_session, user_factory):
    from sqlalchemy import select

    from app.db.models import User

    user = await user_factory(username="hashcheck")
    stored = (
        await db_session.execute(select(User).where(User.id == user.id))
    ).scalar_one()
    assert stored.password_hash != "supersecret123"
    assert stored.password_hash.startswith("$2")


async def test_me_requires_a_token(client):
    resp = await client.get("/auth/me")
    assert resp.status_code == 401


async def test_me_rejects_a_bad_token(client):
    resp = await client.get("/auth/me", headers={"Authorization": "Bearer nonsense"})
    assert resp.status_code == 401


async def test_me_rejects_token_signed_with_another_secret(client, user_factory):
    """A token whose signature does not match the server secret is worthless.

    The algorithms list is passed explicitly when decoding, so a token cannot
    talk the server into trusting a different algorithm than the one configured.
    """
    from jose import jwt

    user = await user_factory(username="victim2")
    wrong_secret = jwt.encode(
        {"sub": str(user.id)}, "some-other-secret", algorithm="HS256"
    )
    resp = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {wrong_secret}"}
    )
    assert resp.status_code == 401


async def test_me_rejects_unsigned_token(client, user_factory):
    """An `alg: none` token is forged by hand, not signed with anything.

    Built from base64 directly rather than through a library, because the point
    is that the request arrives with no valid signature at all and the server
    must still refuse it.
    """
    import base64
    import json as jsonlib

    user = await user_factory(username="victim3")

    def seg(obj: dict) -> str:
        raw = base64.urlsafe_b64encode(jsonlib.dumps(obj).encode()).rstrip(b"=")
        return raw.decode()

    forged = f"{seg({'alg': 'none', 'typ': 'JWT'})}.{seg({'sub': str(user.id)})}."

    resp = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 401


async def test_me_returns_the_current_user(client, user_factory):
    await user_factory(username="whois")
    resp = await client.post(
        "/auth/login", json={"username": "whois", "password": "supersecret123"}
    )
    token = resp.json()["access_token"]
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["username"] == "whois"