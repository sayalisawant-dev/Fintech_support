"""Chat UI for the financial assistant.

Run from the repository root:
    uv run --with-requirements ui/requirements.txt streamlit run ui/app.py \
        --server.address localhost --client.toolbarMode minimal

Sign-in goes through Cognito (port 3000 must reach this machine) and every message calls the deployed
AgentCore Runtime with the user's access token, so Gateway, Policy and Memory all apply as usual.
"""

import itertools
import os
import sys
import uuid
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent_client import (  # noqa: E402
    AuthError,
    LoginBroker,
    asks_for_confirmation,
    decode_claims,
    load_stack,
    logout_url,
    refresh_tokens,
    seconds_left,
    start_callback_server,
    stream_reply,
)

UI_URL = os.getenv("FA_UI_URL", "http://localhost:8501")
EXAMPLES = [
    "Who am I and what accounts do I have?",
    "What are my balances and when is my card payment due?",
    "How much did I spend in February 2025 and what were my top categories?",
    "Is anything on my card a duplicate or suspicious?",
    "Move 200 dollars from checking to savings.",
]

st.set_page_config(page_title="Financial Assistant", page_icon="🏦", layout="centered")


@st.cache_resource
def get_broker() -> tuple[LoginBroker | None, str | None]:
    """Load the stack outputs and start the sign-in callback server once per process."""
    try:
        broker = LoginBroker(load_stack(), UI_URL)
    except (FileNotFoundError, KeyError) as e:
        return None, f"Could not read cdk-outputs.json: {e}"
    try:
        start_callback_server(broker)
    except OSError:
        return broker, (
            "Port 3000 is busy, so Cognito cannot send you back here. Stop the other login "
            "(pkill -f cognito-user.py) and restart the UI. You can still use a token from the terminal."
        )
    return broker, None


def anchor(label: str, url: str) -> None:
    """A link that opens in this tab (st.link_button always opens a new one)."""
    st.markdown(
        f'<a href="{url}" target="_self" style="display:inline-block;padding:0.45rem 1rem;border-radius:0.5rem;'
        f'background:#0f766e;color:white;text-decoration:none;font-weight:600">{label}</a>',
        unsafe_allow_html=True,
    )


def set_tokens(tokens: dict) -> None:
    st.session_state.tokens = tokens
    st.session_state.session_id = str(uuid.uuid4())
    st.session_state.messages = []


def access_token(broker: LoginBroker) -> str | None:
    """The current access token, refreshed first if it is about to expire."""
    tokens = st.session_state.get("tokens")
    if not tokens:
        return None
    if seconds_left(tokens["access_token"]) < 120 and tokens.get("refresh_token"):
        try:
            st.session_state.tokens = tokens = refresh_tokens(broker.stack, tokens["refresh_token"])
        except AuthError:
            st.session_state.tokens = None
            return None
    return tokens["access_token"]


broker, problem = get_broker()

# Coming back from Cognito: /?login=<key> carries the one-time key for the tokens the callback server got.
login_key = st.query_params.get("login")
if login_key and broker:
    tokens = broker.take(login_key)
    st.query_params.clear()
    if tokens:
        set_tokens(tokens)
    st.rerun()

st.session_state.setdefault("messages", [])
st.session_state.setdefault("tokens", None)

# ---------------------------------------------------------------------------
# Signed out
# ---------------------------------------------------------------------------
if not st.session_state.tokens:
    st.title("🏦 Financial Assistant")
    st.caption("Amazon Bedrock AgentCore · Runtime, Gateway, Policy and Memory")
    if broker is None:
        st.error(problem)
        st.stop()
    if problem:
        st.warning(problem)
    st.write("Sign in with your Cognito user (for example `john@example.com` or `jane@example.com`).")
    if not problem:
        anchor("Sign in with Cognito", broker.start_login())
    env_token = os.getenv("BEDROCK_AGENTCORE_BEARER_TOKEN")
    with st.expander("Use a token from the terminal instead"):
        st.caption("From `eval $(uv run scripts/cognito-user.py --login --export)` or `source ~/.agent_token`.")
        pasted = st.text_input("Bearer token", value=env_token or "", type="password")
        if st.button("Use this token", disabled=not pasted):
            if seconds_left(pasted) <= 0:
                st.error("That token has expired (tokens last 1 hour). Log in again.")
            else:
                set_tokens({"access_token": pasted})
                st.rerun()
    st.stop()

# ---------------------------------------------------------------------------
# Signed in
# ---------------------------------------------------------------------------
token = access_token(broker)
if not token:
    st.warning("Your sign-in expired. Please sign in again.")
    st.session_state.tokens = None
    st.stop()

claims = decode_claims(token)
user = claims.get("username") or claims.get("email") or "signed in"
groups = ", ".join(claims.get("cognito:groups", [])) or "none"

with st.sidebar:
    st.subheader("Signed in")
    st.markdown(f"`{user}`")
    st.caption(f"Group: {groups}")
    st.caption(f"Token valid for {max(seconds_left(token), 0) // 60} more minutes")
    if st.button("New conversation", use_container_width=True):
        st.session_state.session_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.rerun()
    anchor("Sign out", logout_url(broker.stack))
    st.divider()
    st.caption("Try asking")
    for example in EXAMPLES:
        if st.button(example, key=f"ex-{example}", use_container_width=True):
            st.session_state.queued = example
    st.divider()
    st.caption(f"Session `{st.session_state.session_id}`")
    st.caption(f"Runtime `{broker.stack.runtime_arn.rsplit('/', 1)[-1]}`")

st.title("🏦 Financial Assistant")

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

last = st.session_state.messages[-1] if st.session_state.messages else None
if last and last["role"] == "assistant" and asks_for_confirmation(last["content"]):
    st.info("The assistant is waiting for your confirmation before it moves money or opens a dispute.")
    yes, no = st.columns(2)
    if yes.button("✅ Yes, confirm", use_container_width=True, type="primary"):
        st.session_state.queued = "Yes"
    if no.button("✖ No, cancel", use_container_width=True):
        st.session_state.queued = "No, cancel that."

prompt = st.chat_input("Ask about your accounts, transactions, disputes or transfers")
prompt = prompt or st.session_state.pop("queued", None)

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    with st.chat_message("assistant"):
        try:
            with st.spinner("Thinking..."):
                chunks = stream_reply(broker.stack, token, st.session_state.session_id, prompt)
                first = next(chunks, "")
            reply = st.write_stream(itertools.chain([first], chunks))
        except AuthError as e:
            st.session_state.tokens = None
            st.error(f"{e} Please sign in again.")
            st.stop()
        except Exception as e:  # show any Runtime failure in the chat rather than a stack trace
            reply = f"⚠️ {e}"
            st.error(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply or ""})
    st.rerun()
