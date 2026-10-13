import os
import jwt
from typing import Optional, Dict, Any

from strands import Agent
from bedrock_agentcore import BedrockAgentCoreApp
from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)
from .mcp_client.client import get_streamable_http_mcp_client
from .model.load import load_model

MEMORY_ID = os.getenv("BEDROCK_AGENTCORE_MEMORY_ID")
REGION = os.getenv("AWS_REGION")


def _get_bearer_token(context) -> Optional[str]:
    """Extract Bearer token from the Authorization header."""
    auth = (getattr(context, "request_headers", None) or {}).get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


def _decode_jwt(token: str) -> Dict[str, Any]:
    """Decode JWT claims. Token already validated by Runtime authorizer."""
    try:
        return jwt.decode(token, options={"verify_signature": False})
    except jwt.exceptions.DecodeError:
        return {}


# Integrate with Bedrock AgentCore
app = BedrockAgentCoreApp()
log = app.logger


@app.entrypoint
async def invoke(payload, context):
    session_id = getattr(context, "session_id", "default-session")

    # Extract user identity from JWT claims
    user_token = _get_bearer_token(context)
    claims = _decode_jwt(user_token) if user_token else {}
    email = claims.get("email") or claims.get("username", "")
    groups = claims.get("cognito:groups", [])
    actor_id = claims.get("sub") or email or payload.get("user_id") or "default-user"
    log.info(f"User: {actor_id}, has_token: {user_token is not None}")

    # Configure memory if available
    session_manager = None
    if MEMORY_ID:
        session_manager = AgentCoreMemorySessionManager(
            AgentCoreMemoryConfig(
                memory_id=MEMORY_ID,
                session_id=session_id,
                actor_id=actor_id,
                retrieval_config={
                    "/facts/{actorId}/": RetrievalConfig(top_k=10, relevance_score=0.4),
                    "/preferences/{actorId}/": RetrievalConfig(top_k=5, relevance_score=0.5),
                    "/summaries/{actorId}/{sessionId}/": RetrievalConfig(top_k=5, relevance_score=0.4),
                    "/episodes/{actorId}/{sessionId}/": RetrievalConfig(top_k=5, relevance_score=0.4),
                },
            ),
            REGION,
        )
    else:
        log.warning("MEMORY_ID is not set. Skipping memory session manager initialization.")

    # Get MCP tools from Gateway (get_customer, list_customers, get_order, list_orders, process_refund)
    strands_mcp_client = get_streamable_http_mcp_client(user_token=user_token)

    with strands_mcp_client as client:
        # Get MCP Tools only — no filesystem tools
        tools = client.list_tools_sync()

        # Create agent
        agent = Agent(
            model=load_model(),
            session_manager=session_manager,
            system_prompt=(
                "You are a customer support agent for a banking/e-commerce platform. "
                "You have access to these tools ONLY: get_customer, list_customers, get_order, list_orders, process_refund.\n\n"
                f"Current user:\n"
                f"- Email: {email or 'unknown'}\n"
                f"- Groups: {', '.join(groups) if groups else 'none'}\n\n"
                "Guidelines:\n"
                "- ALWAYS use the customer's email to call get_customer or list_customers first to find their account\n"
                "- Use list_orders with the customer_id to fetch their orders\n"
                "- Use get_order with order_id to get full order details\n"
                "- Use process_refund with order_id, amount, and reason to process refunds\n"
                "- NEVER search the filesystem, run shell commands, or read files — you don't have those tools\n"
                "- If a tool call is denied by a policy, report the exact denial message and do NOT retry\n"
                "- Give direct, concise answers based on what the tools return\n\n"
                "When relevant memories are retrieved from previous sessions:\n"
                "- Use stored preferences to personalize responses\n"
                "- Reference past facts about the customer to provide continuity"
            ),
            tools=tools,
        )

        # Execute and format response
        stream = agent.stream_async(payload.get("prompt"))

        async for event in stream:
            if "data" in event and isinstance(event["data"], str):
                yield event["data"]


def format_response(result) -> str:
    """Extract code from metrics and format with LLM response."""
    parts = []

    # Extract executed code from metrics
    try:
        tool_metrics = result.metrics.tool_metrics.get("code_interpreter")
        if tool_metrics and hasattr(tool_metrics, "tool"):
            action = tool_metrics.tool["input"]["code_interpreter_input"]["action"]
            if "code" in action:
                parts.append(f"## Executed Code:\n```{action.get('language', 'python')}\n{action['code']}\n```\n---\n")
    except (AttributeError, KeyError):
        pass  # No code to extract

    # Add LLM response
    parts.append(f"## 📊 Result:\n{str(result)}")
    return "\n".join(parts)


if __name__ == "__main__":
    app.run()
