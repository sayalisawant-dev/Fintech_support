# MEMORY --- Customer Support Agent

## Project Identity

**Project:** Amazon Bedrock AgentCore Demo --- Customer Support Agent

## Primary Architecture Memory

**AgentCore Runtime is the central execution layer.**

``` text
Cognito
   |
   | JWT
   v
AgentCore Runtime
   |
   | Strands Agent + DeepSeek V3.2
   v
AgentCore Gateway
   |
   v
AgentCore Policy Engine
   |
   | Allow
   v
Lambda Backend
```

Supporting services:

``` text
AgentCore Memory  -> persistent user/session context
CloudWatch        -> observability
```

## AgentCore Runtime

The Runtime: - Hosts the containerized Strands agent. - Runs the
customer-support agent. - Uses the configured DeepSeek V3.2 model. - Receives
authenticated invocations. - Starts the agent reasoning flow. -
Initiates tool calls through Gateway. - Participates in the observable
request lifecycle.

Documented status check:

``` bash
uv run agentcore status
```

The README says an already deployed agent showing `READY` or `ACTIVE`
can proceed to Step 2.

## Runtime Deployment

Primary deployment command:

``` bash
scripts/deploy.sh
```

The deployment builds the Docker image, pushes/deploys the application
resources, and provisions the documented AgentCore resources.

## Agent

Containerized Strands agent.

Documented default model:

``` text
DeepSeek V3.2
```

Model configuration:

``` text
src/model/load.py
```

## Authentication

Cognito provides: - User authentication - JWT - `email` -
`cognito:groups`

Documented test users: - John Doe --- `john@example.com` - Jane Smith
--- `jane@example.com`

Documented group:

``` text
standard
```

## Gateway

AgentCore Gateway is the MCP-based tool gateway.

Runtime-hosted agent tool calls go through Gateway.

## Policy

AgentCore Policy Engine evaluates Cedar policies.

Refund rule:

``` text
standard group
AND
process_refund
AND
amount <= $100
```

A denied call is blocked at the Gateway before backend execution.

## Tools

``` text
get_customer
list_customers
get_order
list_orders
process_refund
```

## Memory

AgentCore Memory supports: - Facts - Preferences - Summaries - Episodes

Memory is scoped to user/session context.

## Observability

CloudWatch GenAI Observability can expose: - Runtime/request lifecycle -
Tool calls - Policy evaluations - Memory operations - Model inference -
Latency - Token counts - Model ID

## Key Commands

``` bash
scripts/deploy.sh

uv run agentcore status

uv run scripts/cognito-user.py --create

eval $(uv run scripts/cognito-user.py --login --export)

uv run agentcore invoke '{"prompt": "Who am I?"}'

uv run agentcore invoke '{"prompt": "Show me my recent orders"}'

uv run agentcore invoke -s $(uuidgen) '{"prompt": "Show me my recent orders"}'

scripts/teardown.sh
```

## Completion Definition

The project is complete when: 1. AgentCore Runtime is deployed. 2.
Runtime status is usable/active. 3. Cognito authentication works. 4.
Runtime invocation works. 5. Runtime-hosted agent can reach tools
through Gateway. 6. Memory works according to the documented flow. 7.
Policy Engine is associated. 8. Large refund is blocked. 9. CloudWatch
trace shows the policy denial.

## Core Design Rule

``` text
Runtime      = execute
Gateway      = route/control tools
Policy       = authorize
Lambda       = perform backend operation
Memory       = remember
Cognito      = authenticate
CloudWatch   = observe
```
