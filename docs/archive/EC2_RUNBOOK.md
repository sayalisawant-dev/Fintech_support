# EC2 runbook: deploy, call, evaluate, observe

`commands_ec2` is the short copy-paste version of this runbook. The code fixes are in the repo, so you no longer patch files on the instance.

## What changed and why the earlier deploys failed

| Problem | Effect | Fix (file) |
|---|---|---|
| Model ID was `deepseek.deepseek-v3-2`. The Bedrock ID for DeepSeek V3.2 is `deepseek.v3.2`. | Every model call failed with an invalid model identifier error, which shows up as a "wrong LLM". | `src/model/load.py` (the ID can also be set with `MODEL_ID`) |
| `Dockerfile` started `FROM --platform=linux/amd64` while CDK built for arm64. | The image came out as amd64, which AgentCore Runtime rejects. | `Dockerfile` |
| The MCP client was written for mcp 2.x (httpx2), but `uv.lock` pins mcp 1.26, where its fallback call `streamable_http_client(..., headers=...)` raises `TypeError`. It only worked because the old image ignored the lock and installed the latest mcp. | Builds from the lock would have had no tools. | `src/mcp_client/client.py` now matches the locked mcp 1.x |
| The image installed unpinned "latest" packages (mcp 2.x) instead of `uv.lock`. | Builds were not reproducible. | `Dockerfile` installs from `uv.lock`, and `mcp` is pinned `< 2` |
| Old ADOT 0.12.2 | Thin traces for GenAI Observability and Evaluations. | ADOT 0.21 is in `uv.lock` |
| Memory IAM lacked `GetEvent` and `DeleteEvent`. | Memory session manager calls could fail. | `cdk/lib/stacks/agentcore-stack.ts` |
| Files had Windows (CRLF) line endings. | `bash: ...\r: bad interpreter` on Linux | All files converted to LF, plus `.gitattributes` |

---

## 0. Instance

* Instance type: **t4g.medium** (arm64), OS: Amazon Linux 2023 arm64, disk: 30 GB gp3.
* Region: **us-east-1** (or another Region that serves `deepseek.v3.2`: us-east-2, us-west-2, eu-west-2, ap-northeast-1 and others). DeepSeek V3.2 runs only in-Region, with no `us.` cross-Region profile.
* IAM: an instance role or user with AdministratorAccess (README → AWS Credentials).

```bash
ssh -i Finance_support001.pem ec2-user@34.228.41.24
uname -m          # must print aarch64
```

## 1. System setup (once)

```bash
sudo dnf update -y && sudo dnf install -y git docker unzip
sudo systemctl enable --now docker && sudo usermod -aG docker $USER && newgrp docker

curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash
export NVM_DIR="$HOME/.nvm"; . "$NVM_DIR/nvm.sh"; nvm install 20 && nvm use 20

curl -LsSf https://astral.sh/uv/install.sh | sh && source $HOME/.local/bin/env

curl "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o awscliv2.zip
unzip -q awscliv2.zip && sudo ./aws/install && aws --version
aws configure            # region us-east-1, unless you use an instance role
aws sts get-caller-identity
```

## 2. Get this code onto the instance

Either push this folder to your Git repository and `git clone` it, or copy it from your PC:

```bash
# from your PC (PowerShell), in the folder that contains Fintech_support
scp -i Finance_support001.pem -r Fintech_support ec2-user@34.228.41.24:~/
```

Then on EC2:

```bash
cd ~/Fintech_support
sed -i 's/\r$//' scripts/*.sh scripts/*.py   # harmless; guards against CRLF from Windows copies
chmod +x scripts/*.sh
```

## 3. Confirm the model works with tools (before deploying)

```bash
uv run scripts/check_model.py                   # expects PASS for deepseek.v3.2
```

If it fails:
* **"model identifier is invalid" or "not found"**: you are in a Region without DeepSeek V3.2. Use us-east-1.
* **"access denied"**: open the Bedrock console → Model access in this Region and enable DeepSeek V3.2.
* **The error mentions tools / toolConfig**: this model will not work for the agent. Use a fallback: `export MODEL_ID=us.amazon.nova-pro-v1:0` and run the check again.

## 4. Deploy

If an earlier attempt left the stack in `ROLLBACK_COMPLETE`, delete it first:

```bash
aws cloudformation delete-stack --stack-name supportAgentDemo-AgentCoreStack
aws cloudformation wait stack-delete-complete --stack-name supportAgentDemo-AgentCoreStack
rm -rf cdk/cdk.out
```

Then:

```bash
scripts/deploy.sh                     # uses MODEL_ID if you exported it, else deepseek.v3.2
uv run agentcore status               # Runtime READY
```

`deploy.sh` stops early if the model check fails. To bypass the check, set `SKIP_MODEL_CHECK=1`.

## 5. Turn on observability (once per account and Region)

```bash
uv run scripts/observability.py setup
```

This enables CloudWatch Transaction Search, which both GenAI Observability and AgentCore Evaluations need. It also sends Gateway and Memory logs and traces to CloudWatch. Allow about 10 minutes after the first run before spans appear.

## 6. Log in and call the agent

Keep an SSH tunnel open from your PC so the Cognito login can call back to EC2:

```powershell
ssh -i Finance_support001.pem -L 3000:localhost:3000 ec2-user@34.228.41.24
```

On EC2:

```bash
uv run scripts/cognito-user.py --create            # john@example.com, group standard
eval $(uv run scripts/cognito-user.py --login --export)   # open the printed URL in your PC browser
uv run agentcore invoke '{"prompt": "Who am I?"}'
uv run agentcore invoke '{"prompt": "Show me my recent card transactions"}'
```

The token lasts 1 hour. Repeat the `eval $(...)` line when calls start returning 401 or 403.

## 7. Evaluate with AgentCore built-in evaluators

```bash
uv run scripts/run_eval.py
```

The script:
1. runs each conversation in `scripts/eval_cases.json` in its own Runtime session (balances, spending, duplicate-charge dispute, transfer, $399 dispute, privacy and advice guardrails),
2. waits for spans to reach CloudWatch,
3. scores every session with `Builtin.GoalSuccessRate`, `Builtin.Helpfulness`, `Builtin.Correctness` and `Builtin.ToolSelectionAccuracy`,
4. writes `eval-results/<time>/report.md` (a score table plus each reply and the evaluator's explanation) and `results.json`.

Useful variants:

```bash
uv run scripts/run_eval.py --list-evaluators                     # every evaluator your account offers
uv run scripts/run_eval.py --case large_dispute_policy            # one case
uv run scripts/run_eval.py -e Builtin.Helpfulness -e Builtin.Correctness
uv run scripts/run_eval.py --skip-invoke --sessions-file eval-results/<time>/sessions.json   # re-score only
```

For continuous scoring of live traffic (online evaluation), add a 10% sample:

```bash
uv run agentcore eval online create -n supportAgentDemo-online --sampling-rate 10 \
  -e Builtin.GoalSuccessRate -e Builtin.Helpfulness -e Builtin.ToolSelectionAccuracy
```

**Policy check:** before you attach the Policy Engine (README step 5), the $399 dispute goes through. Run `--case large_dispute_policy` after attaching it. The keyword check should pass, and the trace should show the denial.

## 8. Check CloudWatch

```bash
uv run scripts/observability.py check          # Transaction Search, runtime logs, spans, deliveries, metrics
uv run scripts/observability.py dashboard      # dashboard + error and p90 latency alarms
```

In the console: **CloudWatch → GenAI Observability → Bedrock AgentCore** → `supportAgentDemo_Agent` → Sessions. Open an `eval-...` session to see the model calls, Gateway tool calls, policy decisions and memory operations. The `check` command also prints direct links.

## 9. Teardown

```bash
uv run agentcore eval online list                    # then, if you created one:
uv run agentcore eval online delete --config-id <id> --force --delete-role
uv run scripts/observability.py teardown            # dashboard, alarms, log deliveries
scripts/teardown.sh                                 # all CDK stacks
```
