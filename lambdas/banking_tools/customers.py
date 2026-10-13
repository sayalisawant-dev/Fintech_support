"""Customer and account tools (CustomerTarget)."""

from typing import Any

from .data import ACCOUNTS, CUSTOMERS
from .responses import error, response


def find_customer(event: dict[str, Any]):
    """Find the customer record for an email address (exact match only — no listing of other customers)."""
    email = (event.get("email") or "").strip().lower()
    if not email:
        return error(400, "email is required", "MISSING_PARAMETER")

    for customer in CUSTOMERS.values():
        if customer["email"] == email:
            return response(200, customer)
    return error(404, f"No customer found for {email}", "CUSTOMER_NOT_FOUND")


def get_customer(event: dict[str, Any]):
    """Look up a customer profile by customer ID."""
    customer_id = event.get("customer_id")
    if not customer_id:
        return error(400, "customer_id is required", "MISSING_PARAMETER")

    customer = CUSTOMERS.get(customer_id)
    if not customer:
        return error(404, f"Customer {customer_id} not found", "CUSTOMER_NOT_FOUND")
    return response(200, customer)


def list_accounts(event: dict[str, Any]):
    """List a customer's accounts with balances."""
    customer_id = event.get("customer_id")
    if not customer_id:
        return error(400, "customer_id is required", "MISSING_PARAMETER")
    if customer_id not in CUSTOMERS:
        return error(404, f"Customer {customer_id} not found", "CUSTOMER_NOT_FOUND")

    accounts = [a for a in ACCOUNTS.values() if a["customer_id"] == customer_id]
    deposits = sum(a["balance"] for a in accounts if a["type"] in ("checking", "savings"))
    card_debt = sum(a["balance"] for a in accounts if a["type"] == "credit_card")
    return response(
        200,
        {
            "customer_id": customer_id,
            "accounts": accounts,
            "total_deposits": round(deposits, 2),
            "total_credit_card_balance": round(card_debt, 2),
        },
    )
