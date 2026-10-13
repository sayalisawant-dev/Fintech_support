# Deploy to EC2 by hand from Git Bash (Windows)

Each block below is labelled with where it runs:

- **PC** means a Git Bash window on your Windows machine.
- **EC2** means the shell you get after you `ssh` into the instance.

Your instance's public IP is `34.228.41.24`. If you stop and start the instance, it gets a new IP, so update the commands then.

---

## Step 1. Launch the instance (AWS console)

1. EC2 → **Launch instance**, in Region **us-east-1**.
2. AMI: **Amazon Linux 2023**, architecture **64-bit (Arm)**.
3. Instance type: **t4g.medium**.
4. Key pair: use your existing `Finance_support001` key pair, or create a new one and download the `.pem`.
5. Network: allow **SSH (22)** from **My IP**. No other inbound ports are needed.
6. Storage: **30 GB gp3**.
7. Launch the instance, then copy its **Public IPv4 address**.

> **Why arm64:** AgentCore Runtime only runs arm64 images. Building on a t4g instance is native and fast.

## Step 2. Connect from Git Bash (PC)

```bash
# PC — Git Bash uses /c/... paths
cd ~/Downloads
chmod 400 Finance_support001.pem
ssh -i Finance_support001.pem ec2-user@34.228.41.24
```

If SSH says the key's permissions are "too open", lock the file down with Windows permissions, then retry:

```bash
# PC
MSYS_NO_PATHCONV=1 icacls "$(cygpath -w ~/Downloads/Finance_support001.pem)" /inheritance:r /grant:r "$USERNAME:(R)"
```

Once connected:

```bash
# EC2
uname -m        # must print: aarch64
```

## Step 3. Install the tools (EC2, once per instance)

```bash
# EC2
sudo dnf update -y
sudo dnf install -y git docker unzip tar

sudo systemctl enable --now docker
sudo usermod -aG docker $USER
exit
```

Log back in so the docker group change takes effect:

```bash
# PC
ssh -i ~/Downloads/Finance_support001.pem ec2-user@34.228.41.24
```

```bash
# EC2
docker ps                                   # must work without sudo

# Node 20
curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
source ~/.bashrc
nvm install 20 && nvm use 20
node --version                              # v20.x

# uv (Python)
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.local/bin/env
uv --version

# AWS CLI v2 for ARM
curl -s "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o awscliv2.zip
unzip -q awscliv2.zip && sudo ./aws/install && rm -rf aws awscliv2.zip
aws --version                               # 2.32.0 or newer
```

## Step 4. Give the instance AWS credentials (EC2)

```bash
# EC2
aws configure
#   AWS Access Key ID:     <your key>
#   AWS Secret Access Key: <your secret>
#   Default region name:   us-east-1
#   Default output format: json

aws sts get-caller-identity                 # shows your account ID
```

The IAM user needs broad permissions (the README suggests AdministratorAccess), because the deployment creates IAM roles, Lambda, Cognito, ECR and AgentCore resources.

## Step 5. Copy the project to EC2

Do this from a **second** Git Bash window on your PC, and leave the SSH session open in the first. Run it in the folder that contains `Fintech_support`:

```bash
# PC
cd /c/path/to/folder/containing/Fintech_support
tar --exclude='node_modules' --exclude='.venv' --exclude='cdk.out' --exclude='.git' \
    -czf fintech.tgz Fintech_support
scp -i ~/Downloads/Finance_support001.pem fintech.tgz ec2-user@34.228.41.24:~/
```

```bash
# EC2
cd ~ && tar -xzf fintech.tgz && cd ~/Fintech_support
find . -type f \( -name '*.sh' -o -name '*.py' -o -name '*.ts' -o -name '*.json' -o -name '*.toml' -o -name '*.lock' \) \
  -not -path './cdk/node_modules/*' -exec sed -i 's/\r$//' {} +    # strip Windows line endings
chmod +x scripts/*.sh
```

Check that the fixes are in place. Each command must print a line:

```bash
# EC2
grep -n '"deepseek.v3.2"' src/model/load.py
grep -n 'platform=linux/arm64' Dockerfile
grep -n 'http_client=http_client' src/mcp_client/client.py
```

> **Prefer git?** Push `Fintech_support` to your own GitHub repo from Git Bash, then run `git clone https://github.com/<you>/<repo>.git ~/Fintech_support` on EC2. Don't clone the old `Banking_support` repo, because it doesn't have the fixes.

## Step 6. Check the model before deploying (EC2)

```bash
# EC2
cd ~/Fintech_support
uv sync
uv run scripts/check_model.py
```

The check must print `PASS`. If it doesn't:

| Message | Fix |
|---|---|
| model identifier invalid / not found | You are in the wrong Region. Run `aws configure set region us-east-1`. |
| AccessDenied | In the Bedrock console (us-east-1), open **Model access** and enable **DeepSeek V3.2**. |
| Mentions tools / toolConfig | Switch to a fallback model: `export MODEL_ID=us.amazon.nova-pro-v1:0`, then run `uv run scripts/check_model.py --model-id $MODEL_ID` |

## Step 7. Deploy (EC2)

If an earlier attempt failed, clear the old stack first. You can skip this on a fresh account:

```bash
# EC2
aws cloudformation describe-stacks --stack-name supportAgentDemo-AgentCoreStack \
  --query 'Stacks[0].StackStatus' --output text 2>/dev/null
# If it prints ROLLBACK_COMPLETE (or *_FAILED):
aws cloudformation delete-stack --stack-name supportAgentDemo-AgentCoreStack
aws cloudformation wait stack-delete-complete --stack-name supportAgentDemo-AgentCoreStack
rm -rf cdk/cdk.out
```

Run the deploy. It takes a while because it builds the image and creates every resource:

```bash
# EC2
scripts/deploy.sh 2>&1 | tee deploy.log
uv run agentcore status                     # Runtime should be READY
```

`deploy.sh` runs the model check, installs packages, bootstraps CDK, deploys both stacks, and writes `cdk-outputs.json` and `.bedrock_agentcore.yaml`. If it fails, paste the end of `deploy.log` in the thread.

## Step 8. Turn on CloudWatch observability (EC2, once per account)

```bash
# EC2
uv run scripts/observability.py setup
```

This enables Transaction Search and sends Gateway and Memory logs to CloudWatch. Allow about 10 minutes before traces appear.

## Step 9. Create a user and log in

```bash
# EC2
uv run scripts/cognito-user.py --create
#   pick 1 (john@example.com), password e.g. Support@123
```

Cognito redirects the login to `localhost:3000`, so open a tunnel from your PC first. Do this in a **new** Git Bash window and leave it open:

```bash
# PC
ssh -i ~/Downloads/Finance_support001.pem -L 3000:localhost:3000 ec2-user@34.228.41.24
```

Back in your first EC2 session:

```bash
# EC2
eval $(uv run scripts/cognito-user.py --login --export)
```

Copy the `https://...amazoncognito.com/oauth2/authorize?...` URL it prints, open it in your browser on the PC, and log in. The command finishes on its own after the login. Then check the token:

```bash
# EC2
echo "${BEDROCK_AGENTCORE_BEARER_TOKEN:0:20}..."     # must not be empty
```

The token expires after 1 hour. Repeat the `eval $(...)` line whenever calls return 401 or 403.

## Step 10. Call the agent (EC2)

```bash
# EC2
uv run agentcore invoke '{"prompt": "Who am I?"}'
uv run agentcore invoke '{"prompt": "Show me my recent card transactions"}'
uv run agentcore invoke '{"prompt": "Please dispute the duplicate $15.99 StreamFlix charge from Feb 7."}'
```

If a call errors, look at the Runtime logs:

```bash
# EC2
RID=$(python3 -c "import json;print(json.load(open('cdk-outputs.json'))['supportAgentDemo-AgentCoreStack']['RuntimeId'])")
aws logs tail /aws/bedrock-agentcore/runtimes/${RID}-DEFAULT --since 15m
```

## Step 11. Run the AgentCore evaluations (EC2)

```bash
# EC2
uv run scripts/run_eval.py
```

The script runs 5 test conversations and waits about 3 minutes for traces. It then scores each conversation with `Builtin.GoalSuccessRate`, `Builtin.Helpfulness`, `Builtin.Correctness` and `Builtin.ToolSelectionAccuracy`, and writes the results to `eval-results/<time>/report.md`.

To read the report on your PC:

```bash
# PC
scp -i ~/Downloads/Finance_support001.pem -r ec2-user@34.228.41.24:~/Fintech_support/eval-results ./eval-results
```

## Step 12. Check CloudWatch (EC2 and console)

```bash
# EC2
uv run scripts/observability.py check        # should end with "Overall: healthy"
uv run scripts/observability.py dashboard    # dashboard + alarms
```

In the console, go to **CloudWatch → GenAI Observability → Bedrock AgentCore → supportAgentDemo_Agent → Sessions**. Open an `eval-...` session to see the model calls, tool calls through the Gateway, and memory operations.

## Step 13. Policy Engine (optional, console)

Follow README step 5 to create the Policy Engine and attach it to the Gateway. Then confirm that the $399 dispute is blocked:

```bash
# EC2
uv run scripts/run_eval.py --case large_dispute_policy
```

## Step 14. Clean up when you're done (EC2)

```bash
# EC2
uv run scripts/observability.py teardown
scripts/teardown.sh                          # answer y
```

Then terminate the EC2 instance in the console.

---

### Common problems

| Symptom | Cause / fix |
|---|---|
| `bash: scripts/deploy.sh: /usr/bin/env: 'bash\r'` | Windows line endings. Re-run the `sed` line from Step 5. |
| `permission denied ... docker.sock` | You didn't log back in after `usermod`. Run `exit` and then `ssh` again. |
| `nvm: command not found` | Run `source ~/.bashrc`. |
| `Architecture incompatible ... arm64` | You built on an x86 instance. Use a t4g instance. |
| `bind: Address already in use` on port 3000 | An old login is still running. Run `pkill -f cognito-user.py` and try again. |
| `No spans found` in run_eval | Run `observability.py setup`, wait 10 minutes, then run `uv run scripts/run_eval.py --skip-invoke --sessions-file eval-results/<time>/sessions.json` |
