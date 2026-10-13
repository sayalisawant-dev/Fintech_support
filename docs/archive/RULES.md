# RULES --- Customer Support Agent

## 1. Core Architecture Rule

**Amazon Bedrock AgentCore Runtime is the application execution layer.**

All implementation decisions must preserve this separation:

``` text
Runtime      = execute agent
Gateway      = expose/control tools
Policy       = authorize tool calls
Lambda       = backend operations
Memory       = persistent context
Cognito      = identity
CloudWatch   = observability
```

Do not bypass AgentCore Runtime with a separate application server
unless the project requirements are explicitly changed.

## 2. AgentCore Runtime Rules

-   The customer-support agent runs inside AgentCore Runtime.
-   The agent is containerized.
-   The Runtime hosts the Strands agent.
-   The Runtime uses the configured DeepSeek V3.2 model.
-   Runtime invocation must use the documented authentication flow.
-   Tool calls from the Runtime-hosted agent must use AgentCore Gateway.
-   Verify Runtime status before testing when deployment already exists.

Use:

``` bash
uv run agentcore status
```

## 3. Authentication Rules

-   Use Cognito.
-   Use JWT bearer authentication.
-   Preserve `email` and `cognito:groups`.
-   Do not replace the documented authentication flow without an
    explicit architecture change.

## 4. Gateway Rules

-   Gateway is the controlled tool boundary.
-   Gateway uses the documented MCP-based tool gateway.
-   Runtime-hosted agent calls tools through Gateway.
-   Do not connect the agent directly to Lambda when the documented flow
    requires Gateway.

## 5. Policy Rules

-   Policy enforcement occurs at the Gateway/Policy Engine layer.
-   Use Cedar policies.
-   Do not rely on the LLM prompt to enforce refund limits.
-   Denied calls must be stopped before Lambda execution.

## 6. Refund Rule

``` text
standard group
+
process_refund
+
amount <= $100
```

Do not silently modify this documented threshold.

## 7. Tool Names

Use the documented names: - `get_customer` - `list_customers` -
`get_order` - `list_orders` - `process_refund`

## 8. Memory Rules

Use AgentCore Memory for: - Facts - Preferences - Summaries - Episodes

Keep memory scoped appropriately to user/session context.

## 9. Observability Rules

Use CloudWatch GenAI Observability and OpenTelemetry.

Do not remove required observability from the Runtime/Gateway flow.

## 10. Deployment Rules

Deploy using:

``` bash
scripts/deploy.sh
```

Check:

``` bash
uv run agentcore status
```

## 11. Security Rules

Never hard-code: - AWS access keys - AWS secret keys - JWT bearer
tokens - Passwords - Other credentials

## 12. Cleanup

Use:

``` bash
scripts/teardown.sh
```
