"""Response envelope shared by every tool."""

import json
from typing import Any


def response(status_code: int, body: dict[str, Any]) -> dict[str, Any]:
    """Consistent JSON response wrapper."""
    return {"statusCode": status_code, "body": json.dumps(body)}


def error(status_code: int, message: str, code: str) -> dict[str, Any]:
    return response(status_code, {"success": False, "error": message, "error_code": code})
