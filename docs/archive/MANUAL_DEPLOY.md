# Manual Deployment Guide — Banking Support AgentCore Demo

This guide walks through deploying the **Amazon Bedrock AgentCore Customer Support Agent**
on a Linux machine (or EC2) step by step, incorporating all fixes discovered during live deployment.

---

## Architecture Overview

```
User → Cognito (JWT) → AgentCore Runtime (containerized Strands agent + DeepSeek V3.2)
                                │
                                │ tool call (MCP)
                                ▼
                        AgentCore Gateway
                                │
                                ▼
                        Policy Engine (Cedar)   ← manual setup in console
                                │
                        ALLOW ──┤── DENY (blocked before Lambda)
                                │
                          Lambda Backend
                     (customer_handler / order_handler)

AgentCore Memory ─── Facts / Preferences / Summaries / Episodes
CloudWatch       ─── OpenTelemetry observability (auto-instrumented)
```

---

## Prerequisites

### Required Tools

| Tool | Min Version | Install |
|---|---|---|
| AWS CLI | **2.32.0+** | See Step 1 |
| Node.js | 20.x | via nvm |
| npm | 10+ | comes with Node |
| Docker | latest | `dnf install docker` |
| uv | latest | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |

### AWS Account Requirements

- IAM user/role with **AdministratorAccess** (recommended for demo)
- Bedrock model access enabled for **DeepSeek V3.2** (one-time console step)
- EC2 architecture must be **arm64 (aarch64)** — AgentCore Runtime only accepts arm64 images

> ⚠️  **x86_64 instances will fail at the AgentCore Runtime deploy step.**
> The service returns: `Architecture incompatible. Supported platforms: [arm64]`
> Use `t4g.medium` (Graviton arm64). Verify with `uname -m` → must show `aarch64`.

---

## Phase 1 — Machine Setup

### Step 1: Launch arm64 EC2

In AWS Console → EC2 → Launch Instance:

- **AMI:** Amazon Linux 2023 — select **64-bit (Arm)** architecture
  - Example AMI: `ami-0eb45f74aa8a20238` (Amazon Linux 2023 arm64, us-east-1)
- **Instance type:** `t4g.medium` (2 vCPU, 4 GB RAM)
- **Storage:** **30 GB** gp3 (8 GB default is too small for Docker builds)
- **Key pair:** your existing `.pem` key
- **Security group:** allow SSH (port 22)

> ⚠️  Do NOT use the Deep Learning AMI — it is 50 GB and unnecessary. Use the plain Amazon Linux 2023 Arm AMI.

### Step 2: Connect to EC2

**On Windows PowerShell — fix .pem permissions first:**
```powershell
$file = "C:\Users\Shakti\Downloads\Finance_support001.pem"
icacls $file /inheritance:r
icacls $file /grant:r "$($env:USERNAME):(R)"
```

**Connect using the public IP (not private IP):**
```bash
ssh -i "C:\Users\Shakti\Downloads\Finance_support001.pem" ec2-user@<EC2-PUBLIC-IP>
```

Get the public IP from: **EC2 Console → Instances → Public IPv4 address**

### Step 3: Verify Architecture

```bash
uname -m
# Must output: aarch64
# If it shows x86_64 — stop and launch a t4g.medium arm64 instance
```

### Step 4: Update System and Install Git + Docker

```bash
sudo dnf update -y
sudo dnf install -y git docker unzip

# Start and enable Docker
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER
newgrp docker

# Verify
docker --version
```

### Step 5: Install Node.js 20 via nvm

```bash
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

# Load nvm into current shell (don't skip — source AFTER install completes)
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"

nvm install 20
nvm use 20

# Verify
node --version   # v20.x.x
npm --version    # 10.x.x
```

> ⚠️  `source ~/.bashrc` before the install completes will not pick up nvm.
> Use the explicit `export NVM_DIR` block above to load nvm in the current shell.

### Step 6: Install uv (Python package manager)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source $HOME/.local/bin/env

# Verify
uv --version
```

### Step 7: Install AWS CLI v2.32.0+ for aarch64

```bash
# ⚠️  Use aarch64 URL — NOT x86_64
curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o "awscliv2.zip"
unzip awscliv2.zip
sudo ./aws/install

# Verify — must be 2.32.0 or higher
aws --version
```

### Step 8: Configure AWS Credentials

```bash
aws configure
# Enter your:
#   AWS Access Key ID
#   AWS Secret Access Key
#   Default region: us-east-1
#   Output format: json

# Verify
aws sts get-caller-identity
```

---

## Phase 2 — Enable Bedrock Model Access (One-Time)

DeepSeek V3.2 requires a one-time subscription before it can be invoked.

1. Open the [AWS Bedrock Console](https://console.aws.amazon.com/bedrock/home?region=us-east-1#/modelaccess)
2. Go to **Model access** in the left nav
3. Click **Modify model access**
4. Find **DeepSeek V3.2** under DeepSeek models
5. Check the box → **Next** → **Submit**
6. Wait for status to show **Access granted** (usually instant)

> ℹ️  Even though Nova Pro is free, model access must be explicitly enabled per account.
> The runtime IAM role also needs Marketplace permissions — see Phase 5.

---

## Phase 3 — Clone and Fix Code

### Step 9: Clone the Repository

```bash
git clone https://github.com/sayalisawant-dev/Banking_support.git
cd Banking_support
```

### Step 10: Fix Docker Image Platform (arm64)

The CDK stack must build an `arm64` image since AgentCore Runtime only accepts arm64:

```bash
cat > cdk/lib/stacks/docker-image-stack.ts << 'EOF'
import * as cdk from 'aws-cdk-lib/core';
import { Construct } from 'constructs/lib/construct';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets'
import { Platform } from 'aws-cdk-lib/aws-ecr-assets'
import { BaseStackProps } from '../types';
import * as path from 'path';

export interface DockerImageStackProps extends BaseStackProps {}

export class DockerImageStack extends cdk.Stack {
    readonly imageUri: string

    constructor(scope: Construct, id: string, props: DockerImageStackProps) {
        super(scope, id, props);

        const asset = new ecr_assets.DockerImageAsset(this, `${props.appName}-AppImage`, {
            directory: path.join(__dirname, "../../../"),
            platform: Platform.LINUX_ARM64,
        });

        this.imageUri = asset.imageUri;
        new cdk.CfnOutput(this, 'ImageUri', { value: this.imageUri });
    }
}
EOF
```

### Step 11: Fix MCP Client for mcp SDK v2

The `mcp` package v2.x renamed `streamablehttp_client` → `streamable_http_client` and moved
the `headers` parameter off the function onto an `httpx2.AsyncClient`:

```bash
cat > src/mcp_client/client.py << 'EOF'
import os
from typing import Optional
from mcp.client.streamable_http import streamable_http_client
from strands.tools.mcp.mcp_client import MCPClient


def get_streamable_http_mcp_client(user_token: Optional[str] = None) -> MCPClient:
    """
    Returns an MCP Client for AgentCore Gateway compatible with Strands.
    """
    gateway_url = os.getenv("GATEWAY_URL")

    if os.getenv("LOCAL_DEV") == "1":
        from contextlib import nullcontext
        from types import SimpleNamespace
        return nullcontext(SimpleNamespace(list_tools_sync=lambda: []))

    if not gateway_url:
        raise RuntimeError("Missing required environment variable: GATEWAY_URL")

    if not user_token:
        raise RuntimeError("User token is required for Gateway access")

    try:
        import httpx2
        http_client = httpx2.AsyncClient(
            headers={"Authorization": f"Bearer {user_token}"},
            timeout=httpx2.Timeout(30, read=300),
        )
        return MCPClient(lambda: streamable_http_client(gateway_url, http_client=http_client))
    except ImportError:
        # Fallback for older mcp versions
        return MCPClient(lambda: streamable_http_client(gateway_url, headers={"Authorization": f"Bearer {user_token}"}))
EOF
```

### Step 12: Set Model to DeepSeek V3.2

```bash
cat > src/model/load.py << 'EOF'
from strands.models import BedrockModel

# DeepSeek V3.2 — replaced Claude Sonnet 4.5
MODEL_ID = "deepseek.deepseek-v3-2"


def load_model() -> BedrockModel:
    """
    Get Bedrock model client.
    Uses IAM authentication via the execution role.
    """
    return BedrockModel(model_id=MODEL_ID)
EOF


def load_model() -> BedrockModel:
    """
    Get Bedrock model client.
    Uses IAM authentication via the execution role.
    """
    return BedrockModel(model_id=MODEL_ID)
EOF
```

### Step 13: Install Python Dependencies

```bash
uv sync
```

### Step 14: Install CDK Dependencies

```bash
cd cdk
npm install
cd ..
```

---

## Phase 4 — CDK Bootstrap

CDK bootstrap creates the S3 staging bucket, ECR container repo, and IAM roles.
This is a **one-time setup per account/region**.

### Step 15: Bootstrap CDK

```bash
cd cdk
npx cdk bootstrap aws://<ACCOUNT_ID>/us-east-1
cd ..
```

Replace `<ACCOUNT_ID>` with your 12-digit AWS account ID (from `aws sts get-caller-identity`).

**Expected output:**
```
✅  Environment aws://123456789012/us-east-1 bootstrapped.
```

---

## Phase 5 — Add IAM Permissions to Runtime Role

The AgentCore runtime role needs Marketplace permissions to invoke Bedrock models:

```bash
ROLE_NAME="supportAgentDemo-AgentCor-supportAgentDemoAgentCore-VYaBlqwlVInw"

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "MarketplaceAccess" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:ViewSubscriptions",
        "aws-marketplace:Subscribe",
        "aws-marketplace:Unsubscribe"
      ],
      "Resource": "*"
    }]
  }'
```

> ℹ️  The role name is generated by CDK. Verify it with:
> ```bash
> aws iam list-roles --query "Roles[?contains(RoleName,'AgentCoreRuntime')].RoleName" --output text
> ```

---

## Phase 6 — Deploy All Stacks

### Step 16: Deploy

```bash
cd cdk
npx cdk deploy --all \
  --outputs-file ../cdk-outputs.json \
  --require-approval never
cd ..
```

This deploys two stacks in order:

**Stack 1 — `supportAgentDemo-DockerImageStack`**
- Builds the Docker image locally (`linux/arm64`)
- Pushes it to the CDK ECR staging repo
- Outputs: `ImageUri`

**Stack 2 — `supportAgentDemo-AgentCoreStack`**
- Cognito UserPool + groups (standard / premium / vip) + app client + hosted domain
- Two Lambda functions: `customer_handler` and `order_handler` (Python 3.12)
- AgentCore Gateway (MCP, JWT auth via Cognito OIDC)
- Gateway Targets: CustomerTarget → customer Lambda, OrderTarget → order Lambda
- AgentCore Memory (FactExtractor / PreferenceLearner / SessionSummarizer / EpisodeTracker)
- AgentCore Runtime (container image, JWT authorizer, env vars)
- PROD and DEV runtime endpoints

**Expected total time: 10–15 minutes**

After completion you will see:
```
✅  supportAgentDemo-DockerImageStack
✅  supportAgentDemo-AgentCoreStack
```

And `cdk-outputs.json` will be created in the repo root.

---

## Phase 7 — Generate AgentCore CLI Config

### Step 17: Generate `.bedrock_agentcore.yaml`

```bash
python3 - cdk-outputs.json .bedrock_agentcore.yaml supportAgentDemo-AgentCoreStack << 'PYEOF'
import json, sys, pathlib

outputs_path, yaml_path, stack_key = sys.argv[1], sys.argv[2], sys.argv[3]
with open(outputs_path) as f:
    stack = json.load(f)[stack_key]

agent_id  = stack["RuntimeId"]
agent_arn = stack["RuntimeArn"]
account   = stack["AccountId"]
region    = stack["Region"]
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
print(f"Generated {yaml_path}")
PYEOF
```

> ⚠️  If `cdk-outputs.json` only contains `DockerImageStack` outputs (AgentCoreStack shows `null`),
> the stack deployed with `(no changes)` and didn't write outputs. Fetch them from CloudFormation:
> ```bash
> aws cloudformation describe-stacks \
>   --stack-name supportAgentDemo-AgentCoreStack \
>   --region us-east-1 \
>   --query "Stacks[0].Outputs" \
>   --output json > /tmp/raw.json
> python3 -c "
> import json
> with open('/tmp/raw.json') as f: outputs = json.load(f)
> with open('cdk-outputs.json') as f: existing = json.load(f)
> existing['supportAgentDemo-AgentCoreStack'] = {o['OutputKey']: o['OutputValue'] for o in outputs}
> with open('cdk-outputs.json', 'w') as f: json.dump(existing, f, indent=2)
> print('Updated')
> "
> ```

### Step 18: Verify Agent Status

```bash
uv run agentcore status
# Look for: READY or ACTIVE
# If CREATING — wait 1–2 minutes and re-run
```

---

## Phase 8 — Create a Cognito User

### Step 19: Create Test User

```bash
uv run scripts/cognito-user.py --create
```

When prompted, choose one of these emails (they match mock customer data):
- `john@example.com` → customer CUST-001
- `jane@example.com` → customer CUST-002

Set a password that meets Cognito requirements:
- 8+ characters, uppercase + lowercase, number, special character
- Example: `Support@123`

---

## Phase 9 — Authenticate and Get Bearer Token

The agent requires a Cognito access token with custom scopes (`runtime:invoke`, `gateway:invoke`).
The `USER_PASSWORD_AUTH` flow does NOT include custom scopes — you must use the PKCE browser flow.

### Step 20: Set Up SSH Tunnel (headless EC2)

**On your LOCAL Windows machine, open a NEW PowerShell window:**
```powershell
ssh -i "C:\Users\Shakti\Downloads\Finance_support001.pem" -L 3000:localhost:3000 ec2-user@<EC2-PUBLIC-IP>
```

Keep this terminal open — it tunnels port 3000 from your Windows machine to EC2.

### Step 21: Login via Browser

**On EC2 (in your main SSH session):**
```bash
eval $(uv run scripts/cognito-user.py --login --export)
```

The script will print a Cognito URL starting with `https://supportagentdemo-...amazoncognito.com/oauth2/authorize?...`

**Copy that full URL** and open it in your **local Windows browser**.
Log in with your email and password.
The browser redirects to `http://localhost:3000/callback` → the SSH tunnel forwards it to EC2 → token is set.

**Verify the token is set:**
```bash
echo "Token: ${BEDROCK_AGENTCORE_BEARER_TOKEN:0:20}..."
# Should show: Token: eyJraWQi...
```

**If the token wasn't exported** (background job issue), set it manually:
```bash
export BEDROCK_AGENTCORE_BEARER_TOKEN="<paste full token here>"
```

> ℹ️  The token expires after **1 hour**. Re-run Step 21 when it expires.
> The token must have scopes: `supportAgentDemo-api/runtime:invoke supportAgentDemo-api/gateway:invoke`

---

## Phase 10 — Invoke the Agent

### Step 22: Test Invocations

```bash
# Verify identity
uv run agentcore invoke '{"prompt": "Who am I?"}'

# List customers
uv run agentcore invoke '{"prompt": "Show me all customers"}'

# List orders
uv run agentcore invoke '{"prompt": "Show me my recent orders"}'

# Small refund (succeeds — within policy limit)
uv run agentcore invoke '{"prompt": "I need a refund for order ORD-12420. The phone case was damaged."}'

# Large refund (blocked after policy engine is added)
uv run agentcore invoke '{"prompt": "I need a refund of $399 for order ORD-12430. The monitor has dead pixels."}'
```

---

## Phase 11 — Add Cedar Policy Engine (Manual — Console Only)

The Policy Engine is not CDK-managed. It must be created manually in the console.

### Step 23: Create Policy Engine

1. Go to **AWS Console → Amazon Bedrock → AgentCore → Policy Engine**
2. Click **Create policy engine**
3. Name it `supportAgentDemo-PolicyEngine`

### Step 24: Add Policy 1 — Read-Only Tools

```
Allow all authenticated users to call get_customer, list_customers, get_order, and list_orders
```

Click **Generate Cedar** → review → **Create**.

### Step 25: Add Policy 2 — Refund Limit

```
Allow users in the standard cognito:groups to call process_refund only when the amount is less than or equal to 100
```

Click **Generate Cedar** → review → **Create**.

### Step 26: Associate Policy Engine with Gateway

1. In the Policy Engine page, click **Associate gateway**
2. Select `supportAgentDemo-Gateway`
3. Confirm

### Step 27: Validate Policy Enforcement

```bash
# Large refund — should now be BLOCKED
uv run agentcore invoke '{"prompt": "I need a full refund of $399 for order ORD-12300."}'

# Small refund — still works
uv run agentcore invoke '{"prompt": "I need a $50 refund for order ORD-12420. Wrong item received."}'
```

---

## Phase 12 — Named Sessions (Memory)

```bash
SESSION_ID=$(uuidgen)
uv run agentcore invoke -s $SESSION_ID '{"prompt": "Show me my recent orders"}'
uv run agentcore invoke -s $SESSION_ID '{"prompt": "Refund the most recent one"}'
```

---

## Cleanup

```bash
chmod +x scripts/teardown.sh
scripts/teardown.sh
rm -f cdk-outputs.json .bedrock_agentcore.yaml
```

---

## Troubleshooting

### 🔧 Architecture incompatible — Supported platforms: [arm64]

AgentCore Runtime only accepts arm64 Docker images. Ensure you:
1. Launched a `t4g.medium` (arm64) EC2 instance
2. Set `platform: Platform.LINUX_ARM64` in `docker-image-stack.ts`

---

### 🔧 ImportError: cannot import name 'streamablehttp_client'

The `mcp` SDK v2 renamed the function. Apply Fix in Step 11 above.

---

### 🔧 streamable_http_client() got an unexpected keyword argument 'headers'

The `mcp` SDK v2 moved `headers` onto `httpx2.AsyncClient`. Apply Fix in Step 11 above.

---

### 🔧 AgentCoreStack outputs are null / KeyError: 'supportAgentDemo-AgentCoreStack'

The stack deployed with `(no changes)` and didn't write outputs. Fetch them from CloudFormation — see note in Step 17.

---

### 🔧 AgentCoreStack in ROLLBACK_COMPLETE state

```bash
aws cloudformation delete-stack --stack-name supportAgentDemo-AgentCoreStack --region us-east-1
aws cloudformation wait stack-delete-complete --stack-name supportAgentDemo-AgentCoreStack --region us-east-1
echo "✅ Stack deleted"
rm -rf cdk/cdk.out
cd cdk && npx cdk deploy --all --outputs-file ../cdk-outputs.json --require-approval never && cd ..
```

---

### 🔧 CDK caching — deploy exits instantly, image not rebuilt

CDK reuses the local Docker image if the tag exists. Force a rebuild:

```bash
# Delete all local cached images
docker rmi $(docker images | grep cdk-hnb659fds | awk '{print $3}') 2>/dev/null || true

# Delete ECR images
aws ecr batch-delete-image \
  --repository-name cdk-hnb659fds-container-assets-<ACCOUNT_ID>-us-east-1 \
  --region us-east-1 \
  --image-ids $(aws ecr list-images \
    --repository-name cdk-hnb659fds-container-assets-<ACCOUNT_ID>-us-east-1 \
    --region us-east-1 --query "imageIds" --output json)

rm -rf cdk/cdk.out
touch src/__init__.py   # Force hash change
cd cdk && npx cdk deploy --all --outputs-file ../cdk-outputs.json --require-approval never && cd ..
```

**Alternative — push image manually and update runtime via Python SDK:**

```bash
REPO="<ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com/cdk-hnb659fds-container-assets-<ACCOUNT_ID>-us-east-1"
NEW_TAG="fix-$(date +%s)"

aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin <ACCOUNT_ID>.dkr.ecr.us-east-1.amazonaws.com
docker build -t $REPO:$NEW_TAG --platform linux/arm64 .
docker push $REPO:$NEW_TAG

uv run python3 << PYEOF
import boto3
client = boto3.client("bedrock-agentcore-control", region_name="us-east-1")
resp = client.update_agent_runtime(
    agentRuntimeId="<RUNTIME_ID>",
    agentRuntimeArtifact={"containerConfiguration": {"containerUri": "$REPO:$NEW_TAG"}},
    roleArn="<ROLE_ARN>",
    networkConfiguration={"networkMode": "PUBLIC"},
    protocolConfiguration={"serverProtocol": "HTTP"},
    authorizerConfiguration={
        "customJWTAuthorizer": {
            "discoveryUrl": "<DISCOVERY_URL>",
            "allowedClients": ["<CLIENT_ID>"]
        }
    },
    requestHeaderConfiguration={"requestHeaderAllowlist": ["Authorization"]},
    environmentVariables={
        "AWS_REGION": "us-east-1",
        "BEDROCK_AGENTCORE_MEMORY_ID": "<MEMORY_ID>",
        "GATEWAY_URL": "<GATEWAY_URL>"
    }
)
print("Status:", resp.get("status"))
PYEOF
```

> ⚠️  Always include `authorizerConfiguration` in `update_agent_runtime` calls.
> Omitting it resets the runtime to SigV4 auth, causing 403 "Authorization method mismatch" errors.

---

### 🔧 403 Forbidden — Authorization method mismatch

The runtime was updated without `authorizerConfiguration`, resetting it to SigV4.
Re-run the `update_agent_runtime` call with `authorizerConfiguration` included (see above).

---

### 🔧 Bearer token missing required scopes (only has aws.cognito.signin.user.admin)

The `USER_PASSWORD_AUTH` Cognito flow does not return custom resource server scopes.
You must use the PKCE browser flow via SSH tunnel — see Phase 9.

---

### 🔧 AccessDeniedException — aws-marketplace:Subscribe

The runtime IAM role is missing Marketplace permissions. Add them:

```bash
aws iam put-role-policy \
  --role-name "<RUNTIME_ROLE_NAME>" \
  --policy-name "MarketplaceAccess" \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [{
      "Effect": "Allow",
      "Action": [
        "aws-marketplace:ViewSubscriptions",
        "aws-marketplace:Subscribe",
        "aws-marketplace:Unsubscribe"
      ],
      "Resource": "*"
    }]
  }'
```

Also ensure model access is enabled in the Bedrock console for DeepSeek V3.2.

---

### 🔧 nvm: command not found after install

The nvm install script writes to `~/.bashrc` after you sourced it. Load it manually:

```bash
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm install 20
```

---

## Quick Reference

| Command | Purpose |
|---|---|
| `uv sync` | Install Python deps |
| `cd cdk && npm install` | Install CDK deps |
| `npx cdk bootstrap aws://ACCOUNT/REGION` | One-time CDK setup |
| `npx cdk deploy --all --outputs-file ../cdk-outputs.json --require-approval never` | Deploy all stacks |
| `uv run agentcore status` | Check runtime status |
| `uv run scripts/cognito-user.py --create` | Create test user |
| `eval $(uv run scripts/cognito-user.py --login --export)` | Get bearer token (needs SSH tunnel) |
| `uv run agentcore invoke '{"prompt": "..."}'` | Invoke agent |
| `scripts/teardown.sh` | Destroy all resources |

---

## AWS Services Deployed

| Service | Resource Name | Purpose |
|---|---|---|
| Cognito | `supportAgentDemo-CognitoUserPool` | User auth + JWT |
| Lambda | `supportAgentDemo-CustomerLambda` | Customer data API |
| Lambda | `supportAgentDemo-OrderLambda` | Orders + refund API |
| AgentCore Gateway | `supportAgentDemo-Gateway` | MCP tool router |
| AgentCore Memory | `supportAgentDemo_Memory_v2` | Persistent context |
| AgentCore Runtime | `supportAgentDemo_Agent` | Containerized agent (arm64, DeepSeek V3.2) |
| ECR | CDK staging repo | Docker image storage |
| CloudWatch | Auto-created | OpenTelemetry traces |
