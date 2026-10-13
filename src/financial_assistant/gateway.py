"""MCP client for the AgentCore Gateway, which serves the banking tools."""

from contextlib import nullcontext
from types import SimpleNamespace

import httpx
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from strands.tools.mcp.mcp_client import MCPClient


def get_streamable_http_mcp_client(gateway_url: str | None, user_token: str | None, local_dev: bool = False):
    """
    Return an MCP client for the AgentCore Gateway, usable as a context manager.

    Args:
        gateway_url: The Gateway's MCP endpoint (GATEWAY_URL on the Runtime).
        user_token: The caller's JWT with the gateway:invoke scope. The Gateway is inside our
            trust boundary, so the user's token is forwarded as-is. For third-party APIs, use
            delegation via AgentCore Identity instead:
            https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/identity-getting-started-google.html
        local_dev: When True, return a stub with no tools so the agent runs without a Gateway.

    Note:
        This targets mcp 1.x (pinned < 2 in pyproject.toml to match uv.lock): headers go on
        an httpx.AsyncClient passed as http_client, because streamable_http_client() has no
        headers= argument. (mcp 2.x moved to the httpx2 package instead.)
    """
    if local_dev:
        return nullcontext(SimpleNamespace(list_tools_sync=lambda: []))

    if not gateway_url:
        raise RuntimeError("Missing required environment variable: GATEWAY_URL")

    if not user_token:
        raise RuntimeError("User token is required for Gateway access")

    def _transport():
        http_client = create_mcp_http_client(
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=httpx.Timeout(30, read=300),
        )
        return streamable_http_client(gateway_url, http_client=http_client)

    return MCPClient(_transport)
