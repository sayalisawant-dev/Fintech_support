"""Code-level guardrails that run before tool calls.

Money-moving tools run only after the customer confirms in a separate turn. The prompt asks the
model to confirm first, but models sometimes skip it, so this gate enforces it in code.
"""

import re

from strands.hooks import BeforeToolCallEvent

SENSITIVE_TOOLS = ("dispute_transaction", "transfer_funds")

CONFIRMATION_REQUIRED = (
    "CONFIRMATION_REQUIRED: not executed. Restate exactly what will happen (transaction or accounts and "
    "the amount) and ask the customer to reply 'yes' to confirm. Do not call this tool again until they do, "
    "and do not say it was completed."
)

_CONFIRM = re.compile(r"^\W*(yes|yep|yeah|confirm(ed)?|go ahead|proceed|do it|ok(ay)?|sure|please do)\b", re.I)
_ASKED = re.compile(r"confirm|reply .{0,3}yes|shall I|should I proceed|would you like me to proceed", re.I)

# session_id -> (tool, input) awaiting confirmation; sessions are sticky to one microVM
_PENDING: dict[str, tuple] = {}


def _asked_to_confirm(messages) -> bool:
    """True if the assistant's last text reply before the current user message asked for confirmation."""
    seen_user = False
    for m in reversed(messages or []):
        texts = [c["text"] for c in m.get("content", []) if isinstance(c, dict) and "text" in c]
        if m.get("role") == "user" and texts:
            if seen_user:
                return False
            seen_user = True
        elif m.get("role") == "assistant" and texts and seen_user:
            return bool(_ASKED.search(" ".join(texts)))
    return False


def _amount(value) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def confirmation_gate(session_id: str, prompt: str):
    """Build a BeforeToolCallEvent hook that cancels sensitive tool calls until the customer confirms."""
    confirmed = bool(_CONFIRM.match(prompt or ""))

    def gate(event: BeforeToolCallEvent):
        name = event.tool_use.get("name", "")
        tool = next((t for t in SENSITIVE_TOOLS if name.endswith(t)), None)
        if not tool:
            return
        args = event.tool_use.get("input") or {}
        key = (
            tool,
            args.get("transaction_id"),
            args.get("from_account_id"),
            args.get("to_account_id"),
            _amount(args.get("amount")),
        )
        if confirmed and (_PENDING.get(session_id) == key or _asked_to_confirm(event.agent.messages)):
            _PENDING.pop(session_id, None)
            return
        _PENDING[session_id] = key
        event.cancel_tool = CONFIRMATION_REQUIRED

    return gate
