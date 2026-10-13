# Container image for the AgentCore Runtime (built and pushed by infra/lib/stacks/docker-image-stack.ts).
# AgentCore Runtime only accepts arm64 images. Build on a Graviton (t4g) EC2
# instance so Docker builds natively; CDK also requests LINUX_ARM64.
FROM --platform=linux/arm64 public.ecr.aws/docker/library/python:3.13-slim-trixie
# Pinned for reproducible builds (uv.lock reads the same in uv 0.11 and 0.12)
COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /uvx /bin/
WORKDIR /app

# All environment variables in one layer
ENV UV_SYSTEM_PYTHON=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_NO_PROGRESS=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DOCKER_CONTAINER=1

# Install the exact versions in uv.lock (not "latest"), without the dev group. The lock includes
# the ADOT distro (aws-opentelemetry-distro), which sends traces to CloudWatch.
COPY pyproject.toml uv.lock ./
RUN uv export --frozen --no-dev --no-emit-project --no-hashes -o /tmp/requirements.txt && \
    uv pip install -r /tmp/requirements.txt && \
    rm /tmp/requirements.txt

# Create non-root user
RUN useradd -m -u 1000 bedrock_agentcore
USER bedrock_agentcore

# 8080: HTTP protocol (used here), 8000: MCP, 9000: A2A
EXPOSE 9000
EXPOSE 8000
EXPOSE 8080

# Only the agent package (see .dockerignore)
COPY src/ ./src/

CMD ["opentelemetry-instrument", "python", "-m", "financial_assistant.main"]
