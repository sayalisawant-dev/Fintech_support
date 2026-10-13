# Architecture

![Architecture](images/architecture.jpeg)

## Request flow

```
Customer ──login──> Amazon Cognito ──JWT (sub, email, cognito:groups)──┐
                                                                       v
                      AgentCore Runtime (JWT authorizer, arm64 container)
                      └── financial_assistant.main  (Strands agent, DeepSeek V3.2 on Bedrock)
                            │  ├── AgentCore Memory: retrieve/store per-user context
                            │  └── confirmation gate: disputes/transfers wait for "yes"
                            │ MCP over HTTPS, the user's own token
                            v
                      AgentCore Gateway (CUSTOM_JWT: client + gateway:invoke scope)
                            │
                      AgentCore Policy Engine (Cedar: allow / deny per tool call)
                            │ allow
                            v
                      Lambda  banking_tools.handler  (CustomerTarget + BankingTarget)

Traces, logs and metrics from every hop ──> CloudWatch (aws/spans) ──> AgentCore Evaluations
```

1. The customer signs in with Cognito and calls the Runtime with the access token.
2. The Runtime validates the token and passes the `Authorization` header to the container.
3. The agent decodes the claims (already validated) to learn who is calling, loads that user's
   memories, and builds the system prompt with their email and groups.
4. Tool calls go to the Gateway with the same token. The Gateway checks the client and scope, asks
   the Policy Engine about the call, and only then invokes the Lambda.
5. The reply streams back, with DeepSeek's leaked tool-call markup removed.

## Code map

| Path | Responsibility |
|---|---|
| `src/financial_assistant/main.py` | Runtime entrypoint: wires identity, memory, tools, model, guardrail and streaming |
| `src/financial_assistant/auth.py` | Bearer token and JWT claims → `UserIdentity` (actor ID, email, groups) |
| `src/financial_assistant/prompts.py` | System prompt: own data only, tool-backed numbers, confirm before acting, no advice |
| `src/financial_assistant/guardrails.py` | `BeforeToolCallEvent` hook that cancels `dispute_transaction` / `transfer_funds` until a separate "yes" |
| `src/financial_assistant/streaming.py` | Removes `<｜DSML｜...>` markup, holding back partial tags split across chunks |
| `src/financial_assistant/memory.py` | AgentCore Memory session manager and retrieval namespaces |
| `src/financial_assistant/gateway.py` | MCP client (mcp 1.x streamable HTTP) with the user's bearer token |
| `src/financial_assistant/model.py` | `BedrockModel` (temperature 0.2, 4096 max tokens) |
| `src/financial_assistant/config.py` | Settings from the Runtime environment |
| `lambdas/banking_tools/handler.py` | Routes `<target>___<tool>` names to the tool functions |
| `lambdas/banking_tools/{customers,transactions,disputes,transfers}.py` | The tools |
| `lambdas/banking_tools/data.py` | In-memory mock customers, accounts and transactions |
| `infra/lib/stacks/agentcore-stack.ts` | Runtime, Gateway + targets, Lambda, Memory, Cognito, IAM, outputs |
| `infra/lib/tool-schemas.ts` | MCP tool schemas for the two Gateway targets |
| `infra/lib/stacks/docker-image-stack.ts` | arm64 image asset pushed to ECR |

## Tools

| Tool | Target | What it does |
|---|---|---|
| `find_customer` | CustomerTarget | Exact email → customer ID, tier, KYC status |
| `get_customer` | CustomerTarget | Profile by customer ID |
| `list_accounts` | CustomerTarget | Accounts with balances, total deposits and card balance |
| `list_transactions` | BankingTarget | Newest first, filter by account or category |
| `get_transaction` | BankingTarget | One transaction and any dispute on it |
| `get_spending_summary` | BankingTarget | Income, spend, net cash flow, spend by category (own transfers excluded) |
| `dispute_transaction` | BankingTarget | Opens a dispute (`DSP-…`) with a provisional credit |
| `transfer_funds` | BankingTarget | Moves money between the customer's checking and savings (`TRF-…`) |

Mock data: John Doe (CUST-001, standard) has a duplicate StreamFlix charge (TXN-1005/1006) and an
unrecognised $399 QUICKPAY charge (TXN-1007). Jane Smith (CUST-002, premium) has a duplicate Harbor
Grill charge (TXN-2004/2005) and a pending pharmacy charge (TXN-2009).

## Safety layers

| Layer | Where | What it stops |
|---|---|---|
| System prompt | `prompts.py` | Other customers' data, invented figures or IDs, investment/tax/legal advice, asking for card numbers or PINs |
| Confirmation gate | `guardrails.py` | A dispute or transfer the customer has not confirmed in a separate turn, even if the model skips asking |
| Gateway authorizer | Gateway `CUSTOM_JWT` | Calls without a token from the app client with the `gateway:invoke` scope |
| Policy Engine | Cedar policies on the Gateway | Calls outside a group's limits (for example standard: disputes ≤ $100, transfers ≤ $1,000), whatever the model decides |
| Lambda checks | `banking_tools` | Wrong owner, wrong account type, insufficient funds, pending or already-disputed charges |

## Memory

Memory `financialAssistant_Memory` keeps events for 30 days and runs four strategies. The agent
retrieves from these namespaces on each turn:

| Strategy | Namespace | Retrieval |
|---|---|---|
| Semantic (facts) | `/facts/{actorId}/` | top 10, score ≥ 0.4 |
| User preferences | `/preferences/{actorId}/` | top 5, score ≥ 0.5 |
| Session summaries | `/summaries/{actorId}/{sessionId}/` | top 5, score ≥ 0.4 |
| Episodes | `/episodes/{actorId}/{sessionId}/` | top 5, score ≥ 0.4 |

The actor ID is the Cognito `sub`, so memories never cross users.

## Observability and evaluations

The container runs under `opentelemetry-instrument` (AWS Distro for OpenTelemetry), so every model
call, tool call and memory call is a span in CloudWatch (`aws/spans`, via Transaction Search).
Gateway and Memory send their own logs and traces once vended log delivery is set up
(`scripts/observability.py setup`). AgentCore built-in evaluators (GoalSuccessRate, Helpfulness,
Correctness, ToolSelectionAccuracy) score sessions from those traces.

## Design decisions

- **One Lambda for both Gateway targets.** The mock data lives in Lambda memory; two functions had
  two copies, so balances shown after a transfer were stale. Both targets now invoke the same
  function.
- **Confirmation enforced in code, not only in the prompt.** The model sometimes acted on the first
  request. The gate cancels the tool call with `CONFIRMATION_REQUIRED` until the next turn says yes.
- **The user's token is forwarded to the Gateway.** The Gateway is inside the same trust boundary, and
  forwarding lets the Policy Engine see the user's groups. Third-party APIs should use AgentCore
  Identity delegation instead.
- **Stable construct IDs.** `supportAgentDemo` prefixes the stacks and construct IDs from the first
  deployment; keeping them means deploys update resources in place.
- **arm64 only.** AgentCore Runtime rejects amd64 images, so the image is built on Graviton.
- **Dependencies from `uv.lock`.** The image installs exact locked versions (`uv export --frozen`)
  with a pinned uv version, so the same commit always builds the same image.
