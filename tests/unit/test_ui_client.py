import base64
import json
import time
import urllib.request

import pytest

import agent_client
from agent_client import LoginBroker, Stack, asks_for_confirmation, decode_claims, parse_sse_line, seconds_left

STACK = Stack(
    region="us-east-1",
    client_id="client123",
    cognito_domain="example.auth.us-east-1.amazoncognito.com",
    runtime_arn="arn:aws:bedrock-agentcore:us-east-1:111122223333:runtime/supportAgentDemo_Agent-abc",
)


def make_token(**claims):
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return f"header.{body}.signature"


def test_decode_claims_and_expiry():
    token = make_token(username="john@example.com", exp=time.time() + 600)
    assert decode_claims(token)["username"] == "john@example.com"
    assert 590 < seconds_left(token) <= 600
    assert decode_claims("not-a-jwt") == {}


def test_parse_sse_line():
    assert parse_sse_line('data: "Hello"') == "Hello"
    assert parse_sse_line("data: plain text") == "plain text"
    assert parse_sse_line("") is None
    assert parse_sse_line(": keep-alive") is None
    with pytest.raises(RuntimeError, match="boom"):
        parse_sse_line('data: {"error": "boom"}')


def test_runtime_url_encodes_arn():
    url = agent_client.runtime_url(STACK)
    assert url.startswith("https://bedrock-agentcore.us-east-1.amazonaws.com/runtimes/arn%3Aaws%3A")
    assert url.endswith("/invocations")


@pytest.mark.parametrize(
    "reply, expected",
    [
        ("I'll move $200.00 from ACC-1001 to ACC-1002. Please reply yes to confirm.", True),
        ("Shall I open the dispute for TXN-1007?", True),
        ("Your checking balance is $2,450.30.", False),
    ],
)
def test_asks_for_confirmation(reply, expected):
    assert asks_for_confirmation(reply) is expected


def test_auth_url_has_pkce_state_and_scopes():
    url = agent_client.auth_url(STACK, "st8", "chal")
    assert "state=st8" in url and "code_challenge=chal" in url
    assert "supportAgentDemo-api%2Fgateway%3Ainvoke" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A3000%2Fcallback" in url


def test_callback_server_completes_login_once(monkeypatch):
    calls = []

    def fake_exchange(stack, code, verifier):
        calls.append((code, verifier))
        return {"access_token": "tok", "refresh_token": "ref"}

    monkeypatch.setattr(agent_client, "exchange_code", fake_exchange)
    broker = LoginBroker(STACK, "http://localhost:8501")
    state = dict(p.split("=") for p in broker.start_login().split("?")[1].split("&"))["state"]

    server = agent_client.start_callback_server(broker, port=0)
    port = server.server_address[1]

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None

    opener = urllib.request.build_opener(NoRedirect)
    try:
        with pytest.raises(urllib.error.HTTPError) as redirect:
            opener.open(f"http://localhost:{port}/callback?code=abc&state={state}")
        assert redirect.value.code == 302
        assert redirect.value.headers["Location"] == f"http://localhost:8501/?login={state}"
        assert calls and calls[0][0] == "abc"

        assert broker.take(state) == {"access_token": "tok", "refresh_token": "ref"}
        assert broker.take(state) is None

        with pytest.raises(urllib.error.HTTPError) as reused:
            opener.open(f"http://localhost:{port}/callback?code=abc&state={state}")
        assert reused.value.code == 400
    finally:
        server.shutdown()
