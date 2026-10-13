#!/usr/bin/env python3
"""
Run the financial assistant through a fixed set of conversations, then score every
session with Amazon Bedrock AgentCore Evaluations (built-in evaluators).

Flow:
  1. Invoke the deployed Runtime over HTTPS with your Cognito bearer token,
     one Runtime session per case in evals/cases.json.
  2. Wait for the OpenTelemetry spans to land in CloudWatch (aws/spans).
  3. Call AgentCore Evaluations on each session and write a report.

Prerequisites (see docs/runbooks/commands_ec2.txt, STEPS 6, 9 and 10):
  - scripts/deploy.sh finished (cdk-outputs.json exists)
  - CloudWatch Transaction Search enabled:  uv run scripts/observability.py setup
  - eval $(uv run scripts/cognito-user.py --login --export)

Usage:
  uv run evals/run_eval.py
  uv run evals/run_eval.py --case balances --case transfer_to_savings
  uv run evals/run_eval.py -e Builtin.Helpfulness -e Builtin.GoalSuccessRate
  uv run evals/run_eval.py --skip-invoke --sessions-file eval-results/<run>/sessions.json
  uv run evals/run_eval.py --list-evaluators
"""

import argparse
import json
import os
import pathlib
import sys
import time
import urllib.parse
import uuid
from datetime import datetime, timezone

import requests

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
OUTPUTS_FILE = REPO_ROOT / "cdk-outputs.json"
STACK_KEY = "supportAgentDemo-AgentCoreStack"
CASES_FILE = REPO_ROOT / "evals" / "cases.json"
RESULTS_DIR = REPO_ROOT / "eval-results"

# Built-in evaluators, by level:
#   session:   Builtin.GoalSuccessRate        did the conversation reach the user's goal
#   trace:     Builtin.Helpfulness, Builtin.Correctness   quality of each reply
#   tool call: Builtin.ToolSelectionAccuracy  did the agent pick the right tool
# List everything your account offers with --list-evaluators.
DEFAULT_EVALUATORS = [
    "Builtin.GoalSuccessRate",
    "Builtin.Helpfulness",
    "Builtin.Correctness",
    "Builtin.ToolSelectionAccuracy",
]


def load_stack_outputs() -> dict:
    if not OUTPUTS_FILE.exists():
        sys.exit(f"ERROR: {OUTPUTS_FILE} not found. Run scripts/deploy.sh first.")
    return json.loads(OUTPUTS_FILE.read_text())[STACK_KEY]


def invoke(runtime_arn: str, region: str, token: str, session_id: str, prompt: str) -> str:
    """Call the Runtime the same way `agentcore invoke` does with a JWT, and return the streamed text."""
    url = (
        f"https://bedrock-agentcore.{region}.amazonaws.com/runtimes/"
        f"{urllib.parse.quote(runtime_arn, safe='')}/invocations"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream, application/json",
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id": session_id,
    }
    resp = requests.post(
        url, params={"qualifier": "DEFAULT"}, headers=headers, json={"prompt": prompt}, timeout=900, stream=True
    )
    if resp.status_code == 401 or resp.status_code == 403:
        sys.exit(
            f"ERROR: Runtime returned {resp.status_code}. The bearer token is missing, expired (1 hour) or for the "
            "wrong client.\n       Refresh it: eval $(uv run scripts/cognito-user.py --login --export)"
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"Runtime returned {resp.status_code}: {resp.text[:500]}")

    parts = []
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        try:
            value = json.loads(data)
        except json.JSONDecodeError:
            value = data
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, dict) and "error" in value:
            raise RuntimeError(f"Agent error: {value}")
    if not parts and resp.headers.get("content-type", "").startswith("application/json"):
        parts.append(resp.text)
    return "".join(parts)


def run_cases(cases, outputs, token, run_dir):
    sessions = []
    for case in cases:
        session_id = f"eval-{case['name']}-{uuid.uuid4()}"  # Runtime needs 33+ chars
        print(f"\n=== {case['name']}  (session {session_id})")
        replies = []
        for prompt in case["turns"]:
            print(f"  > {prompt}")
            start = time.time()
            try:
                reply = invoke(outputs["RuntimeArn"], outputs["Region"], token, session_id, prompt)
            except Exception as e:  # keep going so one bad case doesn't stop the run
                reply = f"<<invoke failed: {e}>>"
            replies.append({"prompt": prompt, "reply": reply, "seconds": round(time.time() - start, 1)})
            print(f"  < {reply[:300]}{'...' if len(reply) > 300 else ''}")

        final = replies[-1]["reply"].lower() if replies else ""
        expect = [e.lower() for e in case.get("expect_any", [])]
        keyword_pass = (any(e in final for e in expect)) if expect else None
        sessions.append(
            {
                "case": case["name"],
                "session_id": session_id,
                "turns": replies,
                "keyword_check": keyword_pass,
                "note": case.get("note"),
            }
        )
    (run_dir / "sessions.json").write_text(json.dumps(sessions, indent=2))
    return sessions


def evaluate_sessions(sessions, agent_id, region, evaluators, wait, retries):
    from bedrock_agentcore_starter_toolkit import Evaluation

    client = Evaluation(region=region)
    if wait:
        print(f"\nWaiting {wait}s for spans to reach CloudWatch...")
        time.sleep(wait)

    for s in sessions:
        print(f"\n=== Evaluating {s['case']}")
        for attempt in range(retries + 1):
            try:
                results = client.run(agent_id=agent_id, session_id=s["session_id"], evaluators=evaluators)
                s["evaluation"] = results.to_dict()
                s["evaluation"].pop("input_data", None)
                break
            except Exception as e:
                msg = str(e)
                if "No spans found" in msg and attempt < retries:
                    print(f"  spans not there yet, retrying in 60s ({attempt + 1}/{retries})")
                    time.sleep(60)
                    continue
                s["evaluation"] = {"error": msg}
                print(f"  ERROR: {msg}")
                if "No spans found" in msg:
                    print("  Check: Transaction Search is on (uv run scripts/observability.py setup) and the")
                    print("  Runtime has written spans (uv run scripts/observability.py check).")
                break
        for r in s.get("evaluation", {}).get("results", []):
            score = "error" if r.get("error") else f"{r.get('value')} ({r.get('label')})"
            print(f"  {r['evaluator_name']:<32} {score}")
    return sessions


def write_report(sessions, evaluators, run_dir):
    lines = ["# Agent evaluation report\n", f"Run: {run_dir.name}\n"]
    header = "| Case | Keyword check | " + " | ".join(e.replace("Builtin.", "") for e in evaluators) + " |"
    lines += [header, "|" + "---|" * (2 + len(evaluators))]
    for s in sessions:
        by_eval = {}
        for r in s.get("evaluation", {}).get("results", []):
            if r.get("error") or r.get("value") is None:
                continue
            by_eval.setdefault(r["evaluator_id"] or r["evaluator_name"], []).append(r["value"])
        cells = []
        for e in evaluators:
            vals = by_eval.get(e)
            cells.append(f"{sum(vals) / len(vals):.2f}" if vals else "n/a")
        kc = {True: "pass", False: "FAIL", None: "-"}[s.get("keyword_check")]
        lines.append(f"| {s['case']} | {kc} | " + " | ".join(cells) + " |")

    lines.append("\nScores are 0 to 1 (higher is better); trace and tool-call evaluators are averaged per session.\n")
    for s in sessions:
        lines.append(f"## {s['case']}\n\nSession `{s['session_id']}`" + (f"  \n_{s['note']}_" if s.get("note") else ""))
        for t in s.get("turns", []):
            lines.append(f"\n**User:** {t['prompt']}\n\n**Agent ({t['seconds']}s):** {t['reply'][:1500]}")
        ev = s.get("evaluation", {})
        if ev.get("error"):
            lines.append(f"\nEvaluation error: `{ev['error']}`")
        for r in ev.get("results", []):
            if r.get("error"):
                lines.append(f"\n- {r['evaluator_name']}: error `{r['error']}`")
            else:
                lines.append(
                    f"\n- {r['evaluator_name']}: **{r.get('value')}** ({r.get('label')}). {(r.get('explanation') or '')[:400]}"
                )
        lines.append("")
    (run_dir / "report.md").write_text("\n".join(lines))
    (run_dir / "results.json").write_text(json.dumps(sessions, indent=2, default=str))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-e", "--evaluator", action="append", help="Evaluator ID (repeatable). Default: 4 built-ins")
    p.add_argument("--case", action="append", help="Run only these case names (repeatable)")
    p.add_argument("--cases-file", default=str(CASES_FILE))
    p.add_argument("--wait", type=int, default=180, help="Seconds to wait for spans before evaluating (default 180)")
    p.add_argument("--retries", type=int, default=3, help="Retries per session if spans are not there yet")
    p.add_argument("--skip-invoke", action="store_true", help="Only evaluate sessions from --sessions-file")
    p.add_argument("--sessions-file", help="sessions.json from an earlier run (with --skip-invoke)")
    p.add_argument("--list-evaluators", action="store_true", help="Print evaluators available in this account")
    args = p.parse_args()

    outputs = load_stack_outputs()
    region, agent_id = outputs["Region"], outputs["RuntimeId"]

    if args.list_evaluators:
        from bedrock_agentcore_starter_toolkit import Evaluation

        print(json.dumps(Evaluation(region=region).list_evaluators(), indent=2, default=str))
        return

    evaluators = args.evaluator or DEFAULT_EVALUATORS
    run_dir = RESULTS_DIR / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.skip_invoke:
        if not args.sessions_file:
            sys.exit("ERROR: --skip-invoke needs --sessions-file")
        sessions = json.loads(pathlib.Path(args.sessions_file).read_text())
        wait = 0
    else:
        token = os.getenv("BEDROCK_AGENTCORE_BEARER_TOKEN")
        if not token:
            sys.exit(
                "ERROR: BEDROCK_AGENTCORE_BEARER_TOKEN is not set.\n"
                "       Run: eval $(uv run scripts/cognito-user.py --login --export)"
            )
        cases = json.loads(pathlib.Path(args.cases_file).read_text())["cases"]
        if args.case:
            cases = [c for c in cases if c["name"] in args.case]
        sessions = run_cases(cases, outputs, token, run_dir)
        wait = args.wait

    sessions = evaluate_sessions(sessions, agent_id, region, evaluators, wait, args.retries)
    write_report(sessions, evaluators, run_dir)
    print(f"\nReport: {run_dir / 'report.md'}\nRaw:    {run_dir / 'results.json'}")


if __name__ == "__main__":
    main()
