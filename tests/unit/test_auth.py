from types import SimpleNamespace

import jwt

from financial_assistant.auth import decode_claims, get_bearer_token, resolve_identity

KEY = "unit-test-signing-key-that-is-long-enough"


def token(**claims) -> str:
    return jwt.encode(claims, KEY, algorithm="HS256")


def context(authorization=None):
    headers = {"Authorization": authorization} if authorization else {}
    return SimpleNamespace(request_headers=headers)


def test_get_bearer_token():
    assert get_bearer_token(context("Bearer abc.def")) == "abc.def"
    assert get_bearer_token(context("Basic abc")) is None
    assert get_bearer_token(context()) is None
    assert get_bearer_token(SimpleNamespace(request_headers=None)) is None
    assert get_bearer_token(object()) is None


def test_decode_claims_does_not_need_the_signing_key():
    assert decode_claims(token(sub="u-1", email="john@example.com"))["email"] == "john@example.com"
    assert decode_claims("not-a-jwt") == {}


def test_resolve_identity_from_cognito_claims():
    jwt_token = token(sub="u-1", email="jane@example.com", **{"cognito:groups": ["premium"]})
    user = resolve_identity(context(f"Bearer {jwt_token}"), {})
    assert (user.actor_id, user.email, user.groups, user.token) == ("u-1", "jane@example.com", ("premium",), jwt_token)


def test_resolve_identity_fallbacks():
    assert resolve_identity(context(f"Bearer {token(username='john')}"), {}).actor_id == "john"
    assert resolve_identity(context(), {"user_id": "local"}).actor_id == "local"
    assert resolve_identity(context(), {}).actor_id == "default-user"
