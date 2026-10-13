# Troubleshooting

## Which window am I in?

| Prompt | Machine |
|---|---|
| `Shakti@LAPTOP-... MINGW64 ~` | Your Windows PC (Git Bash) |
| `[ec2-user@ip-172-31-... ~]$` | The EC2 instance |

Most "No such file or directory" errors for `~/Banking_support` or `scripts/...` mean an EC2 command
ran in the PC window. `ssh ... ec2-user@<ip>` goes from PC to EC2; `exit` goes back.

## Login and tokens

| Problem | Fix |
|---|---|
| `Authorization method mismatch` / `no bearer token provided` | The shell has no token. Log in again (`eval $(uv run scripts/cognito-user.py --login --export)`) or `source ~/.agent_token` |
| `Unauthorized` / 401 / 403 from the Runtime | The token expired (1 hour). Log in again |
| Browser says `localhost refused to connect` | The SSH session has no tunnel. Reconnect with `ssh -i <key> -L 3000:localhost:3000 ec2-user@<ip>` |
| `Port 3000 is already in use` | `pkill -f cognito-user.py; sudo fuser -k 3000/tcp` |
| Login times out | Open the printed URL and sign in within 2 minutes; don't press Ctrl+C while it waits for the callback |

## Deploy

| Problem | Fix |
|---|---|
| `bash: ...\r: bad interpreter` | Windows line endings: `find . \( -name "*.py" -o -name "*.sh" -o -name "*.ts" \) -not -path "*/node_modules/*" -print0 \| xargs -0 sed -i 's/\r$//'` |
| `Architecture incompatible. Supported platforms: [arm64]` | Build on an arm64 (t4g) instance; the Dockerfile and CDK both request linux/arm64 |
| `invalid model identifier` | Wrong model ID or Region. DeepSeek V3.2 is `deepseek.v3.2`, in-Region only (us-east-1 works) |
| `AccessDeniedException` from Bedrock | Enable DeepSeek V3.2 in Bedrock → Model access |
| Stack in `ROLLBACK_COMPLETE` | `aws cloudformation delete-stack --stack-name supportAgentDemo-AgentCoreStack`, wait, `rm -rf infra/cdk.out`, deploy again |
| `npm ci` fails with EACCES | A past `sudo npm install` left root-owned files: `sudo chown -R $(whoami) ~/.npm` |
| `agentcore: command not found` | Use `uv run agentcore ...` from the repo root (installed by `uv sync`) |

## Agent behaviour

| Symptom | Cause / fix |
|---|---|
| Dispute or transfer asks for confirmation again after "yes" | The amount or accounts changed between turns, or "yes" came in a different session. Use the same `-s <session-id>` and confirm the same values |
| Balances reset to the starting values | The mock data lives in Lambda memory; a redeploy or cold start resets it |
| A stray `function_calls` word in a reply | DeepSeek markup leak; `streaming.py` removes the known forms |
| Policy denials for premium users | No policy allows the premium group yet; add policy 4 in [../policy-engine.md](../policy-engine.md) |

## Observability and evaluations

| Problem | Fix |
|---|---|
| `No spans found` from `agentcore eval run` | Wrong session ID, spans not there yet (wait ~5 minutes), or Transaction Search is off (`uv run scripts/observability.py setup`) |
| No Gateway or Memory logs | Vended log delivery is not set up, or the Memory was recreated: re-run `uv run scripts/observability.py setup` |
| `uv run scripts/observability.py check` | Reports Transaction Search, Runtime logs, spans, deliveries and recent errors in one go |
