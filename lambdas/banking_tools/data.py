"""In-memory mock data store.

Every tool reads and writes these dicts, so a transfer shows up in list_accounts straight away.
The data lives in the Lambda's memory: a redeploy or a cold start resets it to the values below.
"""

from typing import Any

# Retail banking customers and their accounts
CUSTOMERS = {
    "CUST-001": {
        "customer_id": "CUST-001",
        "name": "John Doe",
        "email": "john@example.com",
        "member_since": "2023-06-01",
        "tier": "standard",
        "kyc_status": "verified",
    },
    "CUST-002": {
        "customer_id": "CUST-002",
        "name": "Jane Smith",
        "email": "jane@example.com",
        "member_since": "2024-01-15",
        "tier": "premium",
        "kyc_status": "verified",
    },
}

# fmt: off
ACCOUNTS = {
    # --- CUST-001 (John Doe) ---
    "ACC-1001": {"account_id": "ACC-1001", "customer_id": "CUST-001", "type": "checking",
                 "nickname": "Everyday Checking", "balance": 2450.30, "currency": "USD", "status": "active"},
    "ACC-1002": {"account_id": "ACC-1002", "customer_id": "CUST-001", "type": "savings",
                 "nickname": "Rainy Day Savings", "balance": 8200.00, "currency": "USD", "status": "active",
                 "interest_rate_apy": 4.10},
    "CARD-1003": {"account_id": "CARD-1003", "customer_id": "CUST-001", "type": "credit_card",
                  "nickname": "Cashback Visa", "balance": 640.12, "credit_limit": 5000.00, "currency": "USD",
                  "status": "active", "payment_due_date": "2025-03-05", "minimum_payment": 35.00},
    # --- CUST-002 (Jane Smith) ---
    "ACC-2001": {"account_id": "ACC-2001", "customer_id": "CUST-002", "type": "checking",
                 "nickname": "Primary Checking", "balance": 5120.75, "currency": "USD", "status": "active"},
    "ACC-2002": {"account_id": "ACC-2002", "customer_id": "CUST-002", "type": "savings",
                 "nickname": "House Fund", "balance": 15300.00, "currency": "USD", "status": "active",
                 "interest_rate_apy": 4.25},
    "CARD-2003": {"account_id": "CARD-2003", "customer_id": "CUST-002", "type": "credit_card",
                  "nickname": "Travel Rewards Mastercard", "balance": 1845.60, "credit_limit": 10000.00,
                  "currency": "USD", "status": "active", "payment_due_date": "2025-03-12", "minimum_payment": 55.00},
}
# fmt: on


def _txn(tid, account_id, date, merchant, category, amount, status="posted", note=None):
    t = {
        "transaction_id": tid,
        "account_id": account_id,
        "customer_id": ACCOUNTS[account_id]["customer_id"],
        "date": date,
        "merchant": merchant,
        "category": category,
        "amount": amount,
        "currency": "USD",
        "status": status,
    }
    if note:
        t["note"] = note
    return t


# Negative amount = money out (debit/charge), positive = money in (credit/deposit).
# fmt: off
TRANSACTIONS = {t["transaction_id"]: t for t in [
    # --- CUST-001 (John Doe) ---
    _txn("TXN-1001", "ACC-1001", "2025-02-01", "Acme Corp Payroll", "income", 3200.00),
    _txn("TXN-1002", "ACC-1001", "2025-02-01", "Oakwood Apartments", "housing", -1450.00),
    _txn("TXN-1003", "CARD-1003", "2025-02-03", "FreshMart Groceries", "groceries", -86.42),
    _txn("TXN-1004", "CARD-1003", "2025-02-05", "City Power & Light", "utilities", -112.30),
    _txn("TXN-1005", "CARD-1003", "2025-02-07", "StreamFlix", "subscriptions", -15.99),
    _txn("TXN-1006", "CARD-1003", "2025-02-07", "StreamFlix", "subscriptions", -15.99,
         note="Second identical charge on the same day"),
    _txn("TXN-1007", "CARD-1003", "2025-02-09", "QUICKPAY*XZ ONLINE", "shopping", -399.00,
         note="Merchant not recognised by many customers"),
    _txn("TXN-1008", "CARD-1003", "2025-02-10", "Bean There Cafe", "dining", -10.42),
    _txn("TXN-1009", "ACC-1001", "2025-02-11", "Transfer to Rainy Day Savings", "transfer", -300.00),
    _txn("TXN-1010", "ACC-1002", "2025-02-11", "Transfer from Everyday Checking", "transfer", 300.00),
    # --- CUST-002 (Jane Smith) ---
    _txn("TXN-2001", "ACC-2001", "2025-02-01", "Globex Payroll", "income", 5400.00),
    _txn("TXN-2002", "ACC-2001", "2025-02-02", "Northside Mortgage", "housing", -2100.00),
    _txn("TXN-2003", "CARD-2003", "2025-02-03", "SkyHigh Airlines", "travel", -642.80),
    _txn("TXN-2004", "CARD-2003", "2025-02-04", "Harbor Grill", "dining", -89.99),
    _txn("TXN-2005", "CARD-2003", "2025-02-04", "Harbor Grill", "dining", -89.99,
         note="Second identical charge on the same day"),
    _txn("TXN-2006", "CARD-2003", "2025-02-06", "ElectroMart", "shopping", -1299.00),
    _txn("TXN-2007", "CARD-2003", "2025-02-08", "FitLife Gym", "health", -45.00),
    _txn("TXN-2008", "ACC-2001", "2025-02-10", "Water Utility Co", "utilities", -64.25),
    _txn("TXN-2009", "CARD-2003", "2025-02-12", "Corner Pharmacy", "health", -23.57, status="pending"),
]}
# fmt: on

DISPUTES: dict[str, dict[str, Any]] = {}
TRANSFERS: dict[str, dict[str, Any]] = {}
