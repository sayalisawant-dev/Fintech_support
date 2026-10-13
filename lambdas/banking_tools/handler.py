"""Lambda entry point for every banking tool behind the AgentCore Gateway.

Both Gateway targets (CustomerTarget and BankingTarget) invoke this one function, so all tools
share the in-memory data in data.py. The tool names here must match the tool schemas in
infra/lib/tool-schemas.ts; infra/test/agentcore-stack.test.ts checks that they do.
"""

import logging

from .customers import find_customer, get_customer, list_accounts
from .disputes import dispute_transaction
from .responses import response
from .transactions import get_spending_summary, get_transaction, list_transactions
from .transfers import transfer_funds

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TOOLS = {
    "find_customer": find_customer,
    "get_customer": get_customer,
    "list_accounts": list_accounts,
    "list_transactions": list_transactions,
    "get_transaction": get_transaction,
    "get_spending_summary": get_spending_summary,
    "dispute_transaction": dispute_transaction,
    "transfer_funds": transfer_funds,
}


def lambda_handler(event, context):
    """Route a Gateway tool call. The Gateway passes the tool name as "<target>___<tool>"."""
    try:
        extended_name = context.client_context.custom.get("bedrockAgentCoreToolName")
        tool_name = None

        if extended_name and "___" in extended_name:
            tool_name = extended_name.split("___", 1)[1]

        if not tool_name:
            return response(400, {"error": "Missing tool name"})

        tool = TOOLS.get(tool_name)
        if not tool:
            return response(400, {"error": f"Unknown tool '{tool_name}'"})

        result = tool(event)
        logger.info("tool=%s status=%s", tool_name, result["statusCode"])
        return result

    except Exception as e:
        logger.exception("Tool call failed")
        return response(500, {"system_error": str(e)})
