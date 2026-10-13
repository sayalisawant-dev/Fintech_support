"""Everything the chat UI needs that is not Streamlit: Cognito sign-in and calling the AgentCore Runtime.

Sign-in uses the same Cognito app client and PKCE flow as scripts/cognito-user.py. The app client only
allows the redirect http://localhost:3000/callback, so a small server on port 3000 receives the code,
swaps it for tokens and sends the browser back to the UI with a one-time key.
"""

import base64
import hashlib
import http.server
import json
import pathlib
import secrets
import threading
import time
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass

import requests

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUTS_FILE = REPO_ROOT / "cdk-outputs.json"
STACK_KEY = "supportAgentDemo-AgentCoreStack"

CALLBACK_PORT = 3000
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}/callback"
LOGOUT_URI = f"http://localhost:{CALLBACK_PORT}/logout"
SCOPES = ["openid", "email", "supportAgentDemo-api/runtime:invoke", "supportAgentDemo-api/gateway:invoke"]

# Same wording the agent's confirmation gate and system prompt use when asking the customer to reply yes.
_ASKS_TO_CONFIRM = ("confirm", "reply yes", "reply 'yes'", 'reply "yes"', "shall i", "should i proceed")


class AuthError(Exception):
    """The Runtime rejected the bearer token (missing, expired or for the wrong client)."""


@dataclass(frozen=True)
class Stack:
    region: str
    client_id: str
    cognito_domain: str
    runtime_arn: str


def load_stack(path: pathlib.Path = OUTPUTS_FILE) -> Stack:
    """Read the deployed stack's outputs (written by scripts/deploy.sh)."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Deploy first (scripts/deploy.sh) or copy it from EC2.")
    outputs = json.loads(path.read_text())[STACK_KEY]
    return Stack(
        region=outputs["Region"],
        client_id=outputs["ClientId"],
        cognito_domain=outputs["CognitoDomain"],
        runtime_arn=outputs["RuntimeArn"],
    )


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def decode_claims(token: str) -> dict:
    """Read a JWT's claims for display. The Runtime's authorizer does the real validation."""
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def seconds_left(token: str) -> int:
    return int(decode_claims(token).get("exp", 0) - time.time())


def generate_pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def auth_url(stack: Stack, state: str, challenge: str) -> str:
    params = {
        "response_type": "code",
        "client_id": stack.client_id,
        "redirect_uri": REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "code_challenge_method": "S256",
        "code_challenge": challenge,
    }
    return f"https://{stack.cognito_domain}/oauth2/authorize?{urllib.parse.urlencode(params)}"


def logout_url(stack: Stack) -> str:
    params = {"client_id": stack.client_id, "logout_uri": LOGOUT_URI}
    return f"https://{stack.cognito_domain}/logout?{urllib.parse.urlencode(params)}"


def _token_request(stack: Stack, form: dict) -> dict:
    resp = requests.post(
        f"https://{stack.cognito_domain}/oauth2/token",
        data={"client_id": stack.client_id, **form},
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=30,
    )
    tokens = resp.json()
    if "error" in tokens:
        raise AuthError(tokens.get("error_description", tokens["error"]))
    return tokens


def exchange_code(stack: Stack, code: str, verifier: str) -> dict:
    return _token_request(
        stack,
        {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI, "code_verifier": verifier},
    )


def refresh_tokens(stack: Stack, refresh_token: str) -> dict:
    """New access token from the 30-day refresh token, so the 1-hour expiry does not end the chat."""
    tokens = _token_request(stack, {"grant_type": "refresh_token", "refresh_token": refresh_token})
    tokens.setdefault("refresh_token", refresh_token)
    return tokens


# ---------------------------------------------------------------------------
# Callback server on port 3000
# ---------------------------------------------------------------------------


class LoginBroker:
    """Holds pending sign-ins (state -> PKCE verifier) and finished ones (state -> tokens).

    Lives at module level so it survives Streamlit reruns and is shared by every browser tab.
    """

    def __init__(self, stack: Stack, ui_url: str):
        self.stack = stack
        self.ui_url = ui_url.rstrip("/")
        self._pending: dict[str, str] = {}
        self._done: dict[str, dict] = {}
        self._lock = threading.Lock()

    def start_login(self) -> str:
        state = secrets.token_urlsafe(16)
        verifier, challenge = generate_pkce()
        with self._lock:
            self._pending[state] = verifier
        return auth_url(self.stack, state, challenge)

    def complete(self, state: str, code: str) -> None:
        with self._lock:
            verifier = self._pending.pop(state, None)
        if verifier is None:
            raise AuthError("Unknown or already used sign-in link. Click Sign in again.")
        tokens = exchange_code(self.stack, code, verifier)
        with self._lock:
            self._done[state] = tokens

    def take(self, state: str) -> dict | None:
        """Hand the tokens to the UI once; a second call with the same key gets nothing."""
        with self._lock:
            return self._done.pop(state, None)


def _handler_for(broker: LoginBroker):
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _redirect(self, url: str):
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()

        def _page(self, status: int, text: str):
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            body = f'<html><body style="font-family:sans-serif;text-align:center;padding:50px">{text}</body></html>'
            self.wfile.write(body.encode())

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = {k: v[0] for k, v in urllib.parse.parse_qs(parsed.query).items()}
            if parsed.path == "/logout":
                self._redirect(broker.ui_url)
            elif parsed.path == "/callback" and "code" in params and "state" in params:
                try:
                    broker.complete(params["state"], params["code"])
                except (AuthError, requests.RequestException) as e:
                    self._page(400, f"<h2>Sign-in failed</h2><p>{e}</p><a href='{broker.ui_url}'>Back</a>")
                    return
                self._redirect(f"{broker.ui_url}/?login={urllib.parse.quote(params['state'])}")
            elif parsed.path == "/callback":
                error = params.get("error_description", params.get("error", "no code returned"))
                self._page(400, f"<h2>Sign-in failed</h2><p>{error}</p><a href='{broker.ui_url}'>Back</a>")
            else:
                self.send_response(404)
                self.end_headers()

    return Handler


def start_callback_server(broker: LoginBroker, port: int = CALLBACK_PORT) -> http.server.ThreadingHTTPServer:
    """Serve /callback and /logout on localhost:3000 in a background thread. Raises OSError if the port is busy."""
    server = http.server.ThreadingHTTPServer(("localhost", port), _handler_for(broker))
    threading.Thread(target=server.serve_forever, daemon=True, name="cognito-callback").start()
    return server


# ---------------------------------------------------------------------------
# Calling the agent
# ---------------------------------------------------------------------------


def runtime_url(stack: Stack) -> str:
    arn = urllib.parse.quote(stack.runtime_arn, safe="")
    return f"https://bedrock-agentcore.{stack.region}.amazonaws.com/runtimes/{arn}/invocations"


def parse_sse_line(line: str) -> str | None:
    """Return the text in one 'data:' line of the Runtime's event stream, or None for other lines."""
    if not line or not line.startswith("data:"):
        return None
    data = line[5:].strip()
    try:
        value = json.loads(data)
    except json.JSONDecodeError:
        return data
    if isinstance(value, str):
        return value
    if isinstance(value, dict) and "error" in value:
        raise RuntimeError(f"Agent error: {value['error']}")
    return None


def stream_reply(stack: Stack, token: str, session_id: str, prompt: str) -> Iterator[str]:
    """Invoke the deployed Runtime (same call as `agentcore invoke` with a JWT) and yield the reply as it streams."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    with requests.post(
        runtime_url(stack),
        params={"qualifier": "DEFAULT"},
        headers=headers,
        json={"prompt": prompt},
        timeout=900,
        stream=True,
    ) as resp:
        if resp.status_code in (401, 403):
            raise AuthError(f"Runtime returned {resp.status_code}: the sign-in expired or is for another client.")
        if resp.status_code >= 400:
            raise RuntimeError(f"Runtime returned {resp.status_code}: {resp.text[:500]}")
        if resp.headers.get("content-type", "").startswith("application/json"):
            yield resp.text
            return
        for line in resp.iter_lines(decode_unicode=True):
            text = parse_sse_line(line)
            if text:
                yield text


def asks_for_confirmation(reply: str) -> bool:
    """True when the agent is waiting for a yes before a dispute or transfer (the confirmation gate)."""
    text = reply.lower()
    return any(phrase in text for phrase in _ASKS_TO_CONFIRM)
