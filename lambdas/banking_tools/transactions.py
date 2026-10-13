"""Transaction and spending tools (BankingTarget)."""

from collections import defaultdict
from typing import Any

from .data import ACCOUNTS, DISPUTES, TRANSACTIONS
from .responses import error, response


def list_transactions(event: dict[str, Any]):
    """List recent transactions for a customer, optionally for one account or category."""
    customer_id = event.get("customer_id")
    account_id = event.get("account_id")
    category = (event.get("category") or "").lower()
    limit = int(event.get("limit") or 20)

    if not customer_id:
        return error(400, "customer_id is required", "MISSING_PARAMETER")
    if account_id and ACCOUNTS.get(account_id, {}).get("customer_id") != customer_id:
        return error(404, f"Account {account_id} not found for {customer_id}", "ACCOUNT_NOT_FOUND")

    txns = [
        t
        for t in TRANSACTIONS.values()
        if t["customer_id"] == customer_id
        and (not account_id or t["account_id"] == account_id)
        and (not category or t["category"] == category)
    ]
    txns.sort(key=lambda t: (t["date"], t["transaction_id"]), reverse=True)
    return response(200, {"customer_id": customer_id, "count": len(txns[:limit]), "transactions": txns[:limit]})


def get_transaction(event: dict[str, Any]):
    """Look up one transaction, including any dispute on it."""
    tid = event.get("transaction_id")
    if not tid:
        return error(400, "transaction_id is required", "MISSING_PARAMETER")
    txn = TRANSACTIONS.get(tid)
    if not txn:
        return error(404, f"Transaction {tid} not found", "TRANSACTION_NOT_FOUND")
    result = dict(txn)
    dispute = next((d for d in DISPUTES.values() if d["transaction_id"] == tid), None)
    if dispute:
        result["dispute"] = dispute
    return response(200, result)


def get_spending_summary(event: dict[str, Any]):
    """Total money in/out and spending by category for a customer (transfers between own accounts excluded)."""
    customer_id = event.get("customer_id")
    month = event.get("month")  # YYYY-MM, optional
    if not customer_id:
        return error(400, "customer_id is required", "MISSING_PARAMETER")

    by_category = defaultdict(float)
    income = spend = 0.0
    for t in TRANSACTIONS.values():
        if t["customer_id"] != customer_id or t["category"] == "transfer":
            continue
        if month and not t["date"].startswith(month):
            continue
        if t["amount"] >= 0:
            income += t["amount"]
        else:
            spend += -t["amount"]
            by_category[t["category"]] += -t["amount"]

    categories = sorted(
        ({"category": c, "total": round(v, 2)} for c, v in by_category.items()),
        key=lambda x: x["total"],
        reverse=True,
    )
    return response(
        200,
        {
            "customer_id": customer_id,
            "period": month or "all",
            "total_income": round(income, 2),
            "total_spend": round(spend, 2),
            "net_cash_flow": round(income - spend, 2),
            "spend_by_category": categories,
        },
    )
