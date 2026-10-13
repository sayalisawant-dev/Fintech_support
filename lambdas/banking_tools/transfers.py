"""Transfer tool (BankingTarget). The agent's confirmation gate and the Cedar policies run before this."""

import uuid
from typing import Any

from .data import ACCOUNTS, TRANSFERS
from .responses import error, response


def transfer_funds(event: dict[str, Any]):
    """Move money between two of the same customer's deposit accounts (checking/savings)."""
    customer_id = event.get("customer_id")
    src, dst = event.get("from_account_id"), event.get("to_account_id")
    amount = event.get("amount")

    required = (("customer_id", customer_id), ("from_account_id", src), ("to_account_id", dst), ("amount", amount))
    for name, value in required:
        if value in (None, ""):
            return error(400, f"{name} is required", "MISSING_PARAMETER")
    if src == dst:
        return error(400, "Source and destination accounts must differ", "SAME_ACCOUNT")
    for acc in (src, dst):
        a = ACCOUNTS.get(acc)
        if not a or a["customer_id"] != customer_id:
            return error(404, f"Account {acc} not found for {customer_id}", "ACCOUNT_NOT_FOUND")
        if a["type"] not in ("checking", "savings"):
            return error(
                400,
                f"{acc} is a {a['type']}; transfers are only between checking and savings",
                "UNSUPPORTED_ACCOUNT_TYPE",
            )
    amount = float(amount)
    if amount <= 0:
        return error(400, "amount must be positive", "INVALID_AMOUNT")
    if ACCOUNTS[src]["balance"] < amount:
        return error(400, f"Insufficient funds in {src} (balance {ACCOUNTS[src]['balance']:.2f})", "INSUFFICIENT_FUNDS")

    ACCOUNTS[src]["balance"] = round(ACCOUNTS[src]["balance"] - amount, 2)
    ACCOUNTS[dst]["balance"] = round(ACCOUNTS[dst]["balance"] + amount, 2)
    transfer_id = f"TRF-{uuid.uuid4().hex[:6].upper()}"
    TRANSFERS[transfer_id] = {
        "transfer_id": transfer_id,
        "from_account_id": src,
        "to_account_id": dst,
        "amount": round(amount, 2),
        "status": "completed",
    }
    return response(
        200,
        {
            "success": True,
            **TRANSFERS[transfer_id],
            "from_balance_after": ACCOUNTS[src]["balance"],
            "to_balance_after": ACCOUNTS[dst]["balance"],
        },
    )
