def test_routing_rejects_missing_and_unknown_tools(call_tool):
    assert call_tool(None) == (400, {"error": "Missing tool name"})
    assert call_tool("delete_bank") == (400, {"error": "Unknown tool 'delete_bank'"})


def test_find_customer_matches_exact_email_only(call_tool):
    status, body = call_tool("find_customer", target="CustomerTarget", email=" John@Example.com ")
    assert status == 200 and body["customer_id"] == "CUST-001"

    status, body = call_tool("find_customer", target="CustomerTarget", email="john@")
    assert status == 404 and body["error_code"] == "CUSTOMER_NOT_FOUND"


def test_list_accounts_totals(call_tool):
    status, body = call_tool("list_accounts", target="CustomerTarget", customer_id="CUST-001")
    assert status == 200
    assert [a["account_id"] for a in body["accounts"]] == ["ACC-1001", "ACC-1002", "CARD-1003"]
    assert body["total_deposits"] == 10650.30
    assert body["total_credit_card_balance"] == 640.12


def test_transfer_updates_balances_seen_by_list_accounts(call_tool):
    status, body = call_tool(
        "transfer_funds", customer_id="CUST-002", from_account_id="ACC-2001", to_account_id="ACC-2002", amount=100
    )
    assert status == 200 and body["transfer_id"].startswith("TRF-")
    assert (body["from_balance_after"], body["to_balance_after"]) == (5020.75, 15400.00)

    # Both Gateway targets hit the same Lambda, so the account tool sees the new balances.
    _, accounts = call_tool("list_accounts", target="CustomerTarget", customer_id="CUST-002")
    balances = {a["account_id"]: a["balance"] for a in accounts["accounts"]}
    assert balances["ACC-2001"] == 5020.75 and balances["ACC-2002"] == 15400.00


def test_transfer_rejections(call_tool):
    def transfer(**overrides):
        event = {"customer_id": "CUST-001", "from_account_id": "ACC-1001", "to_account_id": "ACC-1002", "amount": 50}
        event.update(overrides)
        return call_tool("transfer_funds", **event)[1].get("error_code")

    assert transfer(amount=None) == "MISSING_PARAMETER"
    assert transfer(to_account_id="ACC-1001") == "SAME_ACCOUNT"
    assert transfer(to_account_id="ACC-2002") == "ACCOUNT_NOT_FOUND"  # someone else's account
    assert transfer(to_account_id="CARD-1003") == "UNSUPPORTED_ACCOUNT_TYPE"
    assert transfer(amount=-5) == "INVALID_AMOUNT"
    assert transfer(amount=999999) == "INSUFFICIENT_FUNDS"


def test_dispute_lifecycle(call_tool):
    status, body = call_tool("dispute_transaction", transaction_id="TXN-1006", amount=15.99, reason="duplicate_charge")
    assert status == 200 and body["dispute_id"].startswith("DSP-") and body["provisional_credit"] is True

    _, txn = call_tool("get_transaction", transaction_id="TXN-1006")
    assert txn["dispute"]["dispute_id"] == body["dispute_id"]

    status, body = call_tool("dispute_transaction", transaction_id="TXN-1006", amount=15.99, reason="again")
    assert status == 409 and body["error_code"] == "ALREADY_DISPUTED"


def test_dispute_rejections(call_tool):
    def dispute(tid, amount=10.0):
        return call_tool("dispute_transaction", transaction_id=tid, amount=amount, reason="test")[1].get("error_code")

    assert dispute("TXN-9999") == "TRANSACTION_NOT_FOUND"
    assert dispute("TXN-1001") == "NOT_A_CHARGE"  # payroll deposit
    assert dispute("TXN-2009") == "TRANSACTION_PENDING"
    assert dispute("TXN-1005", amount=20.00) == "INVALID_AMOUNT"  # more than the charge


def test_list_transactions_filters_and_orders(call_tool):
    _, body = call_tool("list_transactions", customer_id="CUST-001", account_id="CARD-1003", category="subscriptions")
    assert [t["transaction_id"] for t in body["transactions"]] == ["TXN-1006", "TXN-1005"]

    status, body = call_tool("list_transactions", customer_id="CUST-001", account_id="ACC-2001")
    assert status == 404 and body["error_code"] == "ACCOUNT_NOT_FOUND"


def test_spending_summary_excludes_own_transfers(call_tool):
    _, body = call_tool("get_spending_summary", customer_id="CUST-001", month="2025-02")
    assert body["total_income"] == 3200.00
    assert body["total_spend"] == 2090.12
    assert body["spend_by_category"][0] == {"category": "housing", "total": 1450.00}
    assert "transfer" not in {c["category"] for c in body["spend_by_category"]}
