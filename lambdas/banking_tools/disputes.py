"""Dispute tool (BankingTarget). The agent's confirmation gate and the Cedar policies run before this."""

import uuid
from typing import Any

from .data import DISPUTES, TRANSACTIONS
from .responses import error, response


def dispute_transaction(event: dict[str, Any]):
    """Open a dispute on a charge and issue a provisional credit."""
    tid = event.get("transaction_id")
    amount = event.get("amount")
    reason = event.get("reason")

    if not tid:
        return error(400, "transaction_id is required", "MISSING_PARAMETER")
    if amount is None:
        return error(400, "amount is required", "MISSING_PARAMETER")
    if not reason:
        return error(400, "reason is required", "MISSING_PARAMETER")

    txn = TRANSACTIONS.get(tid)
    if not txn:
        return error(404, f"Transaction {tid} not found", "TRANSACTION_NOT_FOUND")
    if txn["amount"] >= 0:
        return error(400, "Only charges (money out) can be disputed", "NOT_A_CHARGE")
    if txn["status"] != "posted":
        return error(400, "Pending transactions cannot be disputed until they post", "TRANSACTION_PENDING")
    if any(d["transaction_id"] == tid for d in DISPUTES.values()):
        return error(409, f"Transaction {tid} already has an open dispute", "ALREADY_DISPUTED")
    amount = float(amount)
    if amount <= 0 or amount > -txn["amount"]:
        return error(400, f"Dispute amount must be between 0 and {-txn['amount']:.2f}", "INVALID_AMOUNT")

    dispute_id = f"DSP-{uuid.uuid4().hex[:6].upper()}"
    DISPUTES[dispute_id] = {
        "dispute_id": dispute_id,
        "transaction_id": tid,
        "account_id": txn["account_id"],
        "amount": round(amount, 2),
        "reason": reason,
        "status": "open",
        "provisional_credit": True,
        "expected_resolution_days": 10,
    }
    return response(
        200,
        {
            "success": True,
            **DISPUTES[dispute_id],
            "message": "Dispute opened. A provisional credit has been applied while the claim is reviewed.",
        },
    )
