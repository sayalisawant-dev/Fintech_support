"""Caller identity, taken from the Cognito access token on the request."""

from dataclasses import dataclass
from typing import Any

import jwt


@dataclass(frozen=True)
class UserIdentity:
    actor_id: str
    email: str = ""
    groups: tuple[str, ...] = ()
    token: str | None = None


def get_bearer_token(context) -> str | None:
    """Extract the Bearer token from the Authorization header."""
    auth = (getattr(context, "request_headers", None) or {}).get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


def decode_claims(token: str) -> dict[str, Any]:
    """Decode JWT claims. The Runtime's JWT authorizer has already validated the token."""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except jwt.exceptions.DecodeError:
        return {}


def resolve_identity(context, payload: dict[str, Any]) -> UserIdentity:
    """Work out who is calling. The actor ID scopes AgentCore Memory to this user."""
    token = get_bearer_token(context)
    claims = decode_claims(token) if token else {}
    email = claims.get("email") or claims.get("username", "")
    groups = tuple(claims.get("cognito:groups", []))
    actor_id = claims.get("sub") or email or payload.get("user_id") or "default-user"
    return UserIdentity(actor_id=actor_id, email=email, groups=groups, token=token)
