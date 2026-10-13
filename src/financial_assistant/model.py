"""Bedrock model used by the agent."""

from strands.models import BedrockModel


def load_model(model_id: str, region: str | None) -> BedrockModel:
    """Get a Bedrock model client. Uses IAM authentication via the Runtime's execution role."""
    return BedrockModel(
        model_id=model_id,
        region_name=region,
        temperature=0.2,
        max_tokens=4096,
    )
