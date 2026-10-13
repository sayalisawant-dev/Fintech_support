"""AgentCore Runtime entrypoint for the financial assistant.

Run in the container with:  python -m financial_assistant.main
"""

from bedrock_agentcore import BedrockAgentCoreApp
from strands import Agent
from strands.hooks import BeforeToolCallEvent

from financial_assistant.auth import resolve_identity
from financial_assistant.config import load_settings
from financial_assistant.gateway import get_streamable_http_mcp_client
from financial_assistant.guardrails import confirmation_gate
from financial_assistant.memory import build_session_manager
from financial_assistant.model import load_model
from financial_assistant.prompts import build_system_prompt
from financial_assistant.streaming import text_chunks

settings = load_settings()
app = BedrockAgentCoreApp()
log = app.logger


@app.entrypoint
async def invoke(payload, context):
    session_id = getattr(context, "session_id", "default-session")
    prompt = payload.get("prompt")

    user = resolve_identity(context, payload)
    log.info("User: %s, has_token: %s", user.actor_id, user.token is not None)

    session_manager = build_session_manager(settings.memory_id, session_id, user.actor_id, settings.region)
    if session_manager is None:
        log.warning("MEMORY_ID is not set. Skipping memory session manager initialization.")

    mcp_client = get_streamable_http_mcp_client(settings.gateway_url, user.token, local_dev=settings.local_dev)
    with mcp_client as client:
        agent = Agent(
            model=load_model(settings.model_id, settings.region),
            session_manager=session_manager,
            system_prompt=build_system_prompt(user.email, user.groups),
            tools=client.list_tools_sync(),
        )
        agent.hooks.add_callback(BeforeToolCallEvent, confirmation_gate(session_id, prompt or ""))

        async for chunk in text_chunks(agent.stream_async(prompt)):
            yield chunk


if __name__ == "__main__":
    app.run()
