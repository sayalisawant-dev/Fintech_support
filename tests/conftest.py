import copy
import json
from types import SimpleNamespace

import pytest

from banking_tools import data


@pytest.fixture(autouse=True)
def reset_banking_data():
    """Tools mutate the in-memory store; restore it in place after each test (modules hold references)."""
    stores = (data.CUSTOMERS, data.ACCOUNTS, data.TRANSACTIONS, data.DISPUTES, data.TRANSFERS)
    snapshots = [copy.deepcopy(s) for s in stores]
    yield
    for store, snapshot in zip(stores, snapshots, strict=True):
        store.clear()
        store.update(snapshot)


@pytest.fixture
def call_tool():
    """Invoke the Lambda the way the Gateway does and return (status_code, parsed body)."""
    from banking_tools.handler import lambda_handler

    def _call(tool_name, target="BankingTarget", **event):
        extended = f"supportAgentDemo-{target}___{tool_name}" if tool_name else None
        context = SimpleNamespace(client_context=SimpleNamespace(custom={"bedrockAgentCoreToolName": extended}))
        result = lambda_handler(event, context)
        return result["statusCode"], json.loads(result["body"])

    return _call
