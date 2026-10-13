import asyncio
from contextlib import nullcontext
from types import SimpleNamespace

import jwt
from strands.hooks import BeforeToolCallEvent

import financial_assistant.main as main


class FakeAgent:
    """Records how the entrypoint builds the agent and streams canned events back."""

    instances = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.callbacks = []
        self.hooks = SimpleNamespace(add_callback=lambda event, cb: self.callbacks.append((event, cb)))
        FakeAgent.instances.append(self)

    async def stream_async(self, prompt):
        self.prompt = prompt
        for event in ({"data": "Your balance is "}, {"data": "<｜DSML｜function_calls>"}, {"data": "$2,450.30"}):
            yield event


def test_invoke_wires_identity_tools_memory_and_guardrail(monkeypatch):
    FakeAgent.instances.clear()
    memory_calls = []
    monkeypatch.setattr(main, "Agent", FakeAgent)
    monkeypatch.setattr(main, "load_model", lambda model_id, region: f"model:{model_id}")
    monkeypatch.setattr(
        main,
        "get_streamable_http_mcp_client",
        lambda url, token, local_dev=False: nullcontext(SimpleNamespace(list_tools_sync=lambda: ["list_accounts"])),
    )
    monkeypatch.setattr(main, "build_session_manager", lambda *args: memory_calls.append(args) or "memory")

    user_token = jwt.encode(
        {"sub": "u-1", "email": "john@example.com", "cognito:groups": ["standard"]},
        "unit-test-signing-key-that-is-long-enough",
        algorithm="HS256",
    )
    context = SimpleNamespace(session_id="session-123", request_headers={"Authorization": f"Bearer {user_token}"})

    async def run():
        return [chunk async for chunk in main.invoke({"prompt": "What is my balance?"}, context)]

    assert "".join(asyncio.run(run())) == "Your balance is $2,450.30"

    agent = FakeAgent.instances[-1]
    assert agent.prompt == "What is my balance?"
    assert agent.kwargs["tools"] == ["list_accounts"]
    assert agent.kwargs["session_manager"] == "memory"
    assert agent.kwargs["model"] == f"model:{main.settings.model_id}"
    assert "- Email: john@example.com" in agent.kwargs["system_prompt"]
    assert memory_calls == [(main.settings.memory_id, "session-123", "u-1", main.settings.region)]
    assert [event for event, _ in agent.callbacks] == [BeforeToolCallEvent]
