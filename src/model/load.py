from strands.models import BedrockModel

# DeepSeek V3.2 — replaced Claude Sonnet 4.5 (requires Marketplace subscription)
# https://docs.aws.amazon.com/bedrock/latest/userguide/models-supported.html
MODEL_ID = "deepseek.v3.2"


def load_model() -> BedrockModel:
    """
    Get Bedrock model client.
    Uses IAM authentication via the execution role.
    """
    return BedrockModel(model_id=MODEL_ID)
