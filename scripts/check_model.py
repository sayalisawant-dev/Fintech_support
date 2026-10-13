#!/usr/bin/env python3
"""
Pre-flight check: can this account call the agent's Bedrock model the way
Strands does (ConverseStream with a tool definition)?

The agent always sends tools, so a model that answers plain text but rejects
toolConfig still breaks every invocation. This runs the same kind of request.

Usage:
    uv run scripts/check_model.py                      # uses MODEL_ID or deepseek.v3.2
    uv run scripts/check_model.py --model-id us.amazon.nova-pro-v1:0
    uv run scripts/check_model.py --region us-east-1
Exit code 0 = model works with tools, 1 = it does not.
"""

import argparse
import os
import sys

import boto3
from botocore.exceptions import ClientError

DEFAULT_MODEL_ID = os.getenv("MODEL_ID", "deepseek.v3.2")

TOOL_CONFIG = {
    "tools": [
        {
            "toolSpec": {
                "name": "get_order",
                "description": "Look up an order by its ID.",
                "inputSchema": {
                    "json": {
                        "type": "object",
                        "properties": {"order_id": {"type": "string"}},
                        "required": ["order_id"],
                    }
                },
            }
        }
    ]
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    parser.add_argument("--region", default=os.getenv("AWS_REGION") or boto3.Session().region_name or "us-east-1")
    args = parser.parse_args()

    print(f"Model:  {args.model_id}")
    print(f"Region: {args.region}")
    client = boto3.client("bedrock-runtime", region_name=args.region)

    try:
        resp = client.converse_stream(
            modelId=args.model_id,
            system=[{"text": "You are a support agent. Use tools when they help."}],
            messages=[{"role": "user", "content": [{"text": "What is the status of order ORD-12420?"}]}],
            toolConfig=TOOL_CONFIG,
            inferenceConfig={"maxTokens": 256, "temperature": 0},
        )
        used_tool, text = False, []
        for event in resp["stream"]:
            start = event.get("contentBlockStart", {}).get("start", {})
            if "toolUse" in start:
                used_tool = True
            delta = event.get("contentBlockDelta", {}).get("delta", {})
            if "text" in delta:
                text.append(delta["text"])
    except ClientError as e:
        err = e.response.get("Error", {})
        print(f"\nFAIL: {err.get('Code')}: {err.get('Message')}")
        msg = (err.get("Message") or "").lower()
        if "tool" in msg:
            print("  This model rejects tool definitions, so the agent cannot use it.")
            print("  Try: --model-id us.amazon.nova-pro-v1:0 (then deploy with MODEL_ID set to it).")
        elif "identifier" in msg or "not found" in msg or "invalid" in msg:
            print("  The model ID is wrong or the model is not offered in this Region.")
            print("  DeepSeek V3.2 is 'deepseek.v3.2' and runs in-Region only (e.g. us-east-1, us-west-2).")
        elif "access" in msg or "authoriz" in msg:
            print("  Your identity cannot invoke this model. Check IAM bedrock:InvokeModel* and")
            print("  that model access is granted in the Bedrock console for this Region.")
        return 1

    print(f"\nPASS: ConverseStream with tools works (model {'called the tool' if used_tool else 'answered in text'}).")
    if text:
        print("Reply:", "".join(text)[:200])
    return 0


if __name__ == "__main__":
    sys.exit(main())
