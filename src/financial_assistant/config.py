"""Runtime settings, read from the environment variables the AgentCore Runtime is deployed with.

The CDK stack (infra/lib/stacks/agentcore-stack.ts) sets every variable below on the Runtime.
"""

import os
from dataclasses import dataclass

# DeepSeek V3.2 on Amazon Bedrock. The Bedrock model ID is "deepseek.v3.2"
# (not "deepseek.deepseek-v3-2"). It is in-Region only (no "us." cross-Region
# profile), so the Runtime must run in a Region that serves it, e.g. us-east-1.
# https://docs.aws.amazon.com/bedrock/latest/userguide/model-card-deepseek-deepseek-v3-2.html
#
# Override without code changes by setting MODEL_ID on the Runtime
# (cdk deploy -c modelId=...), e.g. "us.amazon.nova-pro-v1:0" as a fallback.
DEFAULT_MODEL_ID = "deepseek.v3.2"


@dataclass(frozen=True)
class Settings:
    region: str | None
    memory_id: str | None
    gateway_url: str | None
    model_id: str
    local_dev: bool


def load_settings() -> Settings:
    return Settings(
        region=os.getenv("AWS_REGION"),
        memory_id=os.getenv("BEDROCK_AGENTCORE_MEMORY_ID"),
        gateway_url=os.getenv("GATEWAY_URL"),
        model_id=os.getenv("MODEL_ID", DEFAULT_MODEL_ID),
        local_dev=os.getenv("LOCAL_DEV") == "1",
    )
