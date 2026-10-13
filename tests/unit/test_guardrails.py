from types import SimpleNamespace

import pytest

from financial_assistant import guardrails
from financial_assistant.guardrails import CONFIRMATION_REQUIRED, confirmation_gate

TRANSFER = {"customer_id": "CUST-001", "from_account_id": "ACC-1001", "to_account_id": "ACC-1002", "amount": 200}


@pytest.fixture(autouse=True)
def clear_pending():
    guardrails._PENDING.clear()
    yield
    guardrails._PENDING.clear()


def tool_call(name, args, messages=()):
    """A stand-in for strands' BeforeToolCallEvent with the attributes the gate uses."""
    return SimpleNamespace(
        tool_use={"name": name, "input": args}, agent=SimpleNamespace(messages=list(messages)), cancel_tool=False
    )


def run_gate(prompt, name="transfer_funds", args=TRANSFER, messages=(), session="s1"):
    event = tool_call(name, args, messages)
    confirmation_gate(session, prompt)(event)
    return event.cancel_tool


def text(role, value):
    return {"role": role, "content": [{"text": value}]}


def test_read_only_tools_pass_through():
    assert run_gate("show my balances", name="list_accounts", args={"customer_id": "CUST-001"}) is False


def test_transfer_needs_a_separate_yes_turn():
    assert run_gate("Move $200 from checking to savings") == CONFIRMATION_REQUIRED
    # Same transfer after the customer says yes; 200 and "200.0" are the same amount.
    assert run_gate("Yes", args={**TRANSFER, "amount": "200.0"}) is False
    # The confirmation is used up.
    assert run_gate("yes") == CONFIRMATION_REQUIRED


def test_yes_does_not_cover_a_different_transfer():
    run_gate("Move $200 from checking to savings")
    assert run_gate("yes", args={**TRANSFER, "amount": 2000}) == CONFIRMATION_REQUIRED


def test_negative_reply_keeps_blocking():
    run_gate("Move $200 from checking to savings")
    assert run_gate("no, cancel that") == CONFIRMATION_REQUIRED


def test_yes_after_the_assistant_asked_to_confirm():
    # e.g. the request and the confirmation landed on different microVMs, so nothing is pending here
    messages = [
        text("user", "Dispute the duplicate StreamFlix charge"),
        text("assistant", "I'll dispute $15.99 on TXN-1006. Please reply yes to confirm."),
        text("user", "yes"),
        {"role": "assistant", "content": [{"toolUse": {"name": "dispute_transaction"}}]},
    ]
    args = {"transaction_id": "TXN-1006", "amount": 15.99, "reason": "duplicate_charge"}
    assert run_gate("yes", name="dispute_transaction", args=args, messages=messages) is False


def test_gateway_prefixed_tool_names_are_gated():
    name = "supportAgentDemo-BankingTarget___dispute_transaction"
    assert run_gate("dispute it", name=name, args={"transaction_id": "TXN-1007", "amount": 399}) == (
        CONFIRMATION_REQUIRED
    )


def test_sessions_do_not_share_pending_confirmations():
    run_gate("Move $200 from checking to savings", session="john")
    assert run_gate("yes", session="someone-else") == CONFIRMATION_REQUIRED
