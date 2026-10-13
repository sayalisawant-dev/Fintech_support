# PRD --- Amazon Bedrock AgentCore Customer Support Agent

## 1. Product Overview

### Product

Amazon Bedrock AgentCore Demo --- Customer Support Agent

### Goal

Build an AI customer support agent whose core runtime is **Amazon
Bedrock AgentCore Runtime**. The agent authenticates users with Amazon
Cognito, runs a containerized Strands agent, invokes
customer/order/refund tools through AgentCore Gateway, stores
user-scoped memory with AgentCore Memory, enforces refund authorization
with AgentCore Policy Engine/Cedar, and exposes observability through
CloudWatch/OpenTelemetry.

## 2. Core Product Components

  -----------------------------------------------------------------------
  Component                           Responsibility
  ----------------------------------- -----------------------------------
  **Amazon Bedrock AgentCore          Hosts and runs the containerized
  Runtime**                           Strands customer-support agent and
                                      provides the runtime invocation
                                      boundary

  **Amazon Bedrock AgentCore          MCP-based gateway that routes agent
  Gateway**                           tool calls to backend tools

  **Amazon Bedrock AgentCore Policy   Evaluates Cedar policies and
  Engine**                            allows/denies Gateway tool calls

  **Amazon Bedrock AgentCore Memory** Maintains persistent user/session
                                      memory

  **Amazon Cognito**                  Authenticates users and issues JWT
                                      claims

  **AWS Lambda**                      Implements mock customer, order and
                                      refund backend APIs

  **Amazon CloudWatch**               Provides GenAI observability and
                                      OpenTelemetry traces
  -----------------------------------------------------------------------

## 3. Primary Request Flow

``` text
User
  |
  v
Cognito Authentication
  |
  | JWT
  v
+--------------------------------+
| Amazon Bedrock AgentCore       |
| Runtime                        |
|                                |
| Containerized Strands Agent    |
| DeepSeek V3.2              |
+---------------+----------------+
                |
                | Tool request
                v
+--------------------------------+
| AgentCore Gateway              |
| MCP Tool Gateway               |
+---------------+----------------+
                |
                v
+--------------------------------+
| AgentCore Policy Engine        |
| Cedar allow / deny             |
+---------------+----------------+
                |
                | allowed
                v
        Lambda Backend APIs
```

AgentCore Memory provides persistent user/session context, while
CloudWatch provides observability.

## 4. Functional Requirements

### AgentCore Runtime

-   Deploy the customer-support agent to AgentCore Runtime.
-   Run the agent as a containerized Strands agent.
-   Use the configured DeepSeek V3.2 model.
-   Support authenticated invocation.
-   Expose the agent through the AgentCore runtime invocation flow.
-   Allow the agent to call tools through AgentCore Gateway.

### Authentication

-   Create a Cognito user.
-   Assign the user to the `standard` group.
-   Obtain a bearer JWT.
-   Preserve `email` and `cognito:groups` claims.

### Customer and Order Operations

Support: - `get_customer` - `list_customers` - `get_order` -
`list_orders`

### Refund

Support: - `process_refund`

Before Policy Engine enforcement, the demo permits unrestricted refund
processing.

After policy enforcement: - Authenticated users can access the approved
read-only tools. - Users in `standard` can call `process_refund` only
when the amount is \<= \$100.

### Memory

Use AgentCore Memory for: - Facts - Preferences - Summaries - Episodes

### Observability

Capture: - Request lifecycle - Tool calls - Policy evaluations - Memory
operations - Model inference - Latency - Token counts - Model ID

## 5. Security Requirements

The final authorization boundary must be the AgentCore Gateway + Policy
Engine, not the LLM prompt.

A denied tool request must be stopped before reaching the Lambda
backend.

## 6. Success Criteria

-   AgentCore Runtime deploys successfully.
-   Runtime reports a usable/active state.
-   Cognito authentication succeeds.
-   An authenticated user can invoke the Runtime.
-   The Runtime-hosted agent can call Gateway tools.
-   Customer/order operations work.
-   A large refund works before policy enforcement.
-   Policy Engine is associated with Gateway.
-   Refunds above \$100 are blocked.
-   CloudWatch shows the policy evaluation and denial.

## 7. Out of Scope

The supplied project README does not define a production frontend, real
payment processor, production CRM, multi-region architecture, or
disaster recovery design.
