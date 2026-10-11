#!/usr/bin/env bash
# scripts/redeploy.sh — Redeploy the Banking Support AgentCore Demo from Kiro IDE
#
# Usage:
#   chmod +x scripts/redeploy.sh
#   scripts/redeploy.sh              # full redeploy (force image rebuild)
#   scripts/redeploy.sh --skip-build # redeploy CDK only, reuse existing Docker image
#   scripts/redeploy.sh --tests-only # run tests only, no deploy
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CDK_DIR="$REPO_ROOT/cdk"
OUTPUTS_FILE="$REPO_ROOT/cdk-outputs.json"
YAML_FILE="$REPO_ROOT/.bedrock_agentcore.yaml"
STACK_KEY="supportAgentDemo-AgentCoreStack"
SKIP_BUILD=false
TESTS_ONLY=false

# Parse flags
for arg in "$@"; do
    case $arg in
        --skip-build) SKIP_BUILD=true ;;
        --tests-only) TESTS_ONLY=true ;;
        --help|-h)
            echo "Usage: scripts/redeploy.sh [--skip-build] [--tests-only]"
            echo ""
            echo "  --skip-build   Skip Docker image rebuild, reuse cached image"
            echo "  --tests-only   Run tests only, skip deployment"
            exit 0
            ;;
        *) echo "Unknown flag: $arg  (use --help for usage)" >&2; exit 1 ;;
    esac
done

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log()  { echo ""; echo "==> $*"; }
ok()   { echo "    ✅  $*"; }
warn() { echo "    ⚠️   $*" >&2; }
fail() { echo ""; echo "❌  ERROR: $*" >&2; exit 1; }

check_cmd() {
    command -v "$1" &>/dev/null || fail "$1 is not installed. $2"
}

# ---------------------------------------------------------------------------
# Step 0 — Pre-flight checks
# ---------------------------------------------------------------------------
log "Pre-flight checks"
check_cmd uv    "Install: https://docs.astral.sh/uv/getting-started/installation/"
check_cmd node  "Run: nvm install 20 && nvm use 20"
check_cmd npm   "Comes with Node.js"
check_cmd aws   "Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
check_cmd docker "Start Docker: sudo systemctl start docker"

# Verify AWS credentials
aws sts get-caller-identity &>/dev/null || fail "AWS credentials not configured. Run: aws configure"
ok "AWS credentials valid"

# Verify Docker daemon
docker info &>/dev/null 2>&1 || fail "Docker daemon not running. Run: sudo systemctl start docker"
ok "Docker daemon running"

# Verify arm64 (AgentCore Runtime only accepts arm64 images)
ARCH=$(uname -m)
if [ "$ARCH" != "aarch64" ]; then
    warn "Architecture is $ARCH — expected aarch64 (arm64)."
    warn "If this is an EC2 deploy, you must use a t4g.medium (arm64) instance."
    warn "Continuing — local builds may still work if QEMU binfmt is installed."
fi
ok "All pre-flight checks passed"

# ---------------------------------------------------------------------------
# Step 1 — Run tests
# ---------------------------------------------------------------------------
log "Running unit tests"
cd "$REPO_ROOT"
uv run pytest test/test_main.py -v --tb=short || fail "Tests failed. Fix them before redeploying."
ok "All tests passed"

if [ "$TESTS_ONLY" = true ]; then
    echo ""
    echo "============================================================"
    echo "  Tests passed. Skipping deploy (--tests-only flag set)."
    echo "============================================================"
    exit 0
fi

# ---------------------------------------------------------------------------
# Step 2 — Install / sync dependencies
# ---------------------------------------------------------------------------
log "Syncing Python dependencies (uv sync)"
cd "$REPO_ROOT"
uv sync
ok "Python dependencies up to date"

log "Syncing CDK dependencies (npm install)"
cd "$CDK_DIR"
npm install --silent
cd "$REPO_ROOT"
ok "CDK dependencies up to date"

# ---------------------------------------------------------------------------
# Step 3 — Force Docker image rebuild (unless --skip-build)
# ---------------------------------------------------------------------------
if [ "$SKIP_BUILD" = false ]; then
    log "Clearing CDK Docker cache to force image rebuild"

    # Remove cached CDK Docker images
    CACHED_IMAGES=$(docker images | grep "cdk-hnb659fds" | awk '{print $3}' 2>/dev/null || true)
    if [ -n "$CACHED_IMAGES" ]; then
        echo "$CACHED_IMAGES" | xargs docker rmi -f 2>/dev/null || true
        ok "Removed cached CDK Docker images"
    else
        ok "No cached CDK Docker images found"
    fi

    # Remove CDK assembly cache so synthesis runs fresh
    rm -rf "$CDK_DIR/cdk.out"
    ok "Removed cdk.out assembly cache"

    # Touch a source file to change the Docker build context hash
    touch "$REPO_ROOT/src/__init__.py"
    ok "Invalidated Docker build context hash"
else
    warn "Skipping Docker image rebuild (--skip-build flag set)"
fi

# ---------------------------------------------------------------------------
# Step 4 — Deploy all CDK stacks
# ---------------------------------------------------------------------------
log "Deploying all CDK stacks (this takes 10–15 min on first run)"
cd "$CDK_DIR"
npx cdk deploy --all \
    --outputs-file "$OUTPUTS_FILE" \
    --require-approval never
cd "$REPO_ROOT"

[ -f "$OUTPUTS_FILE" ] || fail "Deploy succeeded but cdk-outputs.json was not created."
ok "CDK deploy complete — outputs written to cdk-outputs.json"

# ---------------------------------------------------------------------------
# Step 5 — Fetch AgentCoreStack outputs if missing (CDK no-change deploy)
# ---------------------------------------------------------------------------
STACK_PRESENT=$(python3 -c "
import json, sys
with open('$OUTPUTS_FILE') as f:
    data = json.load(f)
print('yes' if '$STACK_KEY' in data and data['$STACK_KEY'] else 'no')
" 2>/dev/null || echo "no")

if [ "$STACK_PRESENT" = "no" ]; then
    warn "AgentCoreStack outputs missing from cdk-outputs.json (stack had no changes)."
    warn "Fetching outputs directly from CloudFormation..."
    REGION=$(aws configure get region || echo "us-east-1")
    aws cloudformation describe-stacks \
        --stack-name "$STACK_KEY" \
        --region "$REGION" \
        --query "Stacks[0].Outputs" \
        --output json > /tmp/cfn_outputs.json

    python3 - "$OUTPUTS_FILE" "$STACK_KEY" /tmp/cfn_outputs.json << 'PYEOF'
import json, sys
outputs_path, stack_key, raw_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(raw_path) as f:
    raw = json.load(f)
with open(outputs_path) as f:
    existing = json.load(f)
existing[stack_key] = {o["OutputKey"]: o["OutputValue"] for o in raw}
with open(outputs_path, "w") as f:
    json.dump(existing, f, indent=2)
print("Updated cdk-outputs.json with CloudFormation outputs")
PYEOF
    ok "AgentCoreStack outputs fetched from CloudFormation"
fi

# ---------------------------------------------------------------------------
# Step 6 — Regenerate .bedrock_agentcore.yaml
# ---------------------------------------------------------------------------
log "Regenerating .bedrock_agentcore.yaml"
python3 - "$OUTPUTS_FILE" "$YAML_FILE" "$STACK_KEY" << 'PYEOF'
import json, sys, pathlib

outputs_path, yaml_path, stack_key = sys.argv[1], sys.argv[2], sys.argv[3]
with open(outputs_path) as f:
    stack = json.load(f)[stack_key]

agent_id      = stack["RuntimeId"]
agent_arn     = stack["RuntimeArn"]
account       = stack["AccountId"]
region        = stack["Region"]
discovery_url = stack["AuthorizerDiscoveryUrl"]

yaml_content = f"""\
default_agent: supportAgentDemo_Agent
agents:
  supportAgentDemo_Agent:
    name: supportAgentDemo_Agent
    language: python
    entrypoint: ./src/main.py
    deployment_type: container
    platform: linux/arm64
    aws:
      account: '{account}'
      region: {region}
      network_configuration:
        network_mode: PUBLIC
      protocol_configuration:
        server_protocol: HTTP
      observability:
        enabled: true
    bedrock_agentcore:
      agent_id: {agent_id}
      agent_arn: {agent_arn}
    authorizer_configuration:
      customJWTAuthorizer:
        discoveryUrl: {discovery_url}
    request_header_configuration:
      requestHeaderAllowlist:
      - Authorization
"""
pathlib.Path(yaml_path).write_text(yaml_content)
print(f"    Generated {yaml_path}")
PYEOF
ok "Generated .bedrock_agentcore.yaml"

# ---------------------------------------------------------------------------
# Step 7 — Wait for runtime to reach READY
# ---------------------------------------------------------------------------
log "Waiting for AgentCore Runtime to become READY..."
MAX_WAIT=180  # 3 minutes
INTERVAL=15
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
    STATUS=$(uv run agentcore status 2>&1 | grep -oE "READY|ACTIVE|CREATING|FAILED|ERROR" | head -1 || true)
    if [ "$STATUS" = "READY" ] || [ "$STATUS" = "ACTIVE" ]; then
        ok "Runtime is $STATUS"
        break
    elif [ "$STATUS" = "FAILED" ] || [ "$STATUS" = "ERROR" ]; then
        fail "Runtime reached $STATUS state. Check CloudWatch logs:\n  aws logs tail /aws/bedrock-agentcore/runtimes/... --since 30m"
    else
        echo "    Status: ${STATUS:-UNKNOWN} — waiting ${INTERVAL}s (${ELAPSED}/${MAX_WAIT}s elapsed)..."
        sleep $INTERVAL
        ELAPSED=$((ELAPSED + INTERVAL))
    fi
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    warn "Runtime did not reach READY within ${MAX_WAIT}s."
    warn "Check status manually: uv run agentcore status"
fi

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
echo ""
echo "============================================================"
echo "  ✅  Redeploy complete!"
echo "============================================================"
echo ""
echo "Next steps:"
echo ""
echo "  1. Get a fresh bearer token (expires every 1 hour):"
echo "       eval \$(uv run scripts/cognito-user.py --login --export)"
echo ""
echo "  2. Test the agent:"
echo "       uv run agentcore invoke '{\"prompt\": \"Who am I?\"}'"
echo "       uv run agentcore invoke '{\"prompt\": \"Show me my recent orders\"}'"
echo ""
echo "  3. View CloudWatch logs:"
echo "       aws logs tail /aws/bedrock-agentcore/runtimes/\$(grep agent_id .bedrock_agentcore.yaml | awk '{print \$2}')-DEFAULT --since 30m"
echo ""
