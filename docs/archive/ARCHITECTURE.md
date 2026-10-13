# ARCHITECTURE --- Amazon Bedrock AgentCore Customer Support Agent

## 1. Architecture Overview

**Amazon Bedrock AgentCore Runtime is the central execution layer of the
application.**

``` text
                         +------------------+
                         |       USER       |
                         +--------+---------+
                                  |
                                  v
                         +------------------+
                         | Amazon Cognito   |
                         | Authentication   |
                         | JWT              |
                         +--------+---------+
                                  |
                                  | JWT
                                  v
              +------------------------------------------+
              | Amazon Bedrock AgentCore Runtime         |
              |                                          |
              | Containerized Strands Customer Agent     |
              | DeepSeek V3.2                            |
              |                                          |
              | Agent execution / inference / sessions   |
              +--------------------+---------------------+
                                   |
                                   | Tool call
                                   v
              +------------------------------------------+
              | Amazon Bedrock AgentCore Gateway         |
              | MCP Tool Gateway                         |
              +--------------------+---------------------+
                                   |
                                   v
              +------------------------------------------+
              | AgentCore Policy Engine                  |
              | Cedar authorization                      |
              |                                          |
              | ALLOW / DENY                             |
              +--------------------+---------------------+
                                   |
                                   | ALLOW
                                   v
              +------------------------------------------+
              | AWS Lambda Backend APIs                  |
              |                                          |
              | Customer | Orders | Refund               |
              +------------------------------------------+

              +------------------------------------------+
              | AgentCore Memory                         |
              | User/session facts, preferences,         |
              | summaries and episodes                    |
              +------------------------------------------+

              +------------------------------------------+
              | Amazon CloudWatch                         |
              | GenAI Observability / OpenTelemetry       |
              +------------------------------------------+
```

## 2. AgentCore Runtime --- Primary Execution Component

### Responsibility

Amazon Bedrock AgentCore Runtime hosts the **containerized Strands
agent**.

It is responsible for: - Running the customer-support agent. - Receiving
authenticated agent invocations. - Executing the agent's reasoning
loop. - Using the configured DeepSeek V3.2 model. - Initiating tool calls when
the agent needs customer/order/refund information. - Connecting the
running agent to AgentCore Gateway. - Participating in the observable
request lifecycle.

### Runtime Deployment

The project uses:

``` bash
scripts/deploy.sh
```

The deployment builds the Docker image and provisions the documented
AgentCore resources.

The README identifies the Runtime as:

``` text
AgentCore Runtime — containerized agent running DeepSeek V3.2
```

### Runtime Verification

Use:

``` bash
uv run agentcore status
```

The README instructs that an already deployed agent showing `READY` or
`ACTIVE` can proceed to invocation.

## 3. Runtime Request Flow

``` text
User
 |
 | authenticated request + JWT
 v
AgentCore Runtime
 |
 | Strands agent receives prompt
 |
 v
DeepSeek V3.2 Model
 |
 | decides a tool is required
 v
AgentCore Gateway
 |
 v
Policy Engine
 |
 +------ DENY ------> Runtime receives policy violation
 |
 +------ ALLOW -----> Lambda backend
                         |
                         v
                    Tool result
                         |
                         v
                    AgentCore Runtime
                         |
                         v
                       User
```

## 4. Component Responsibilities

  Component                     Responsibility
  ----------------------------- ------------------------------------------
  **AgentCore Runtime**         Execute the containerized Strands agent
  **AgentCore Gateway**         Provide MCP-based controlled tool access
  **AgentCore Policy Engine**   Evaluate Cedar authorization
  **AgentCore Memory**          Persist user/session memory
  **Cognito**                   Authenticate users and issue JWTs
  **Lambda**                    Customer/order/refund backend APIs
  **CloudWatch**                Runtime and tool observability

## 5. Gateway and Tool Flow

The Runtime-hosted agent does not directly call the backend Lambda
functions.

The documented flow is:

``` text
AgentCore Runtime
       |
       v
AgentCore Gateway
       |
       v
Policy Engine
       |
       +---- Allow ----> Lambda
       |
       +---- Deny -----> Block
```

## 6. Policy Example

Read-only tools:

``` text
get_customer
list_customers
get_order
list_orders
```

Refund:

``` text
standard Cognito group
        AND
process_refund
        AND
amount <= 100
        |
        v
      ALLOW
```

Otherwise:

``` text
DENY
```

## 7. Memory

AgentCore Memory maintains per-user/session: - Facts - Preferences -
Summaries - Episodes

## 8. Observability

CloudWatch GenAI Observability can expose: - Full request lifecycle -
Runtime/model activity - Gateway tool calls - Policy evaluations -
Memory operations - Model inference - Latency - Token counts - Model ID

## 9. Model Configuration

The README states that the model is configured in:

``` text
src/model/load.py
```

The documented default is DeepSeek V3.2.

## 10. Architecture Principle

**Runtime executes the agent. Gateway controls tool access. Policy
Engine controls authorization. Lambda performs backend operations.
Memory maintains context. CloudWatch provides observability.**
