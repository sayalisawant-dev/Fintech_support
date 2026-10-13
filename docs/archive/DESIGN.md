# DESIGN --- Customer Support Agent

## 1. Design Objective

The application is designed around Amazon Bedrock AgentCore Runtime as
the execution layer.

## 2. Runtime-Centered Design

``` text
                     USER
                       |
                       v
                 +-----------+
                 | Cognito   |
                 | JWT       |
                 +-----+-----+
                       |
                       v
        +--------------------------------+
        | AgentCore Runtime              |
        |                                |
        | Container                      |
        |   └── Strands Agent            |
        |       └── DeepSeek V3.2      |
        +---------------+----------------+
                        |
                        | tool request
                        v
        +--------------------------------+
        | AgentCore Gateway              |
        | MCP tools                      |
        +---------------+----------------+
                        |
                        v
        +--------------------------------+
        | Policy Engine / Cedar          |
        +------------+-----------+-------+
                     |           |
                  ALLOW         DENY
                     |           |
                     v           X
                  Lambda       Block
                     |
                     v
             Backend Operations
```

## 3. AgentCore Runtime Design

The Runtime is responsible for running the application agent.

Inside Runtime:

``` text
Container
  |
  +-- Strands Agent
        |
        +-- DeepSeek V3.2 Model
        |
        +-- Customer support reasoning
        |
        +-- Tool invocation
```

The Runtime should not contain the final authorization decision for
sensitive tool calls. That responsibility belongs to the Policy Engine.

## 4. Authentication Design

Cognito authenticates the user and supplies JWT claims.

Important claims: - `email` - `cognito:groups`

The JWT is used when invoking the Runtime and is available to the
downstream authorization flow.

## 5. Tool Design

The Runtime-hosted agent can request:

``` text
Customer:
  get_customer
  list_customers

Orders:
  get_order
  list_orders

Refund:
  process_refund
```

All documented tool calls go through AgentCore Gateway.

## 6. Authorization Design

``` text
Runtime
   |
   v
Gateway
   |
   v
Cedar Policy
   |
   +---- allow ----> Lambda
   |
   +---- deny -----> stop
```

The refund limit is therefore enforced outside the model.

## 7. Memory Design

AgentCore Memory provides persistent context for: - Facts -
Preferences - Summaries - Episodes

Memory is associated with the appropriate user/session.

## 8. Observability Design

CloudWatch GenAI Observability should allow investigation of: - Runtime
invocation - Model inference - Tool calls - Policy evaluation - Memory
operations - Latency - Token counts

## 9. Separation of Responsibilities

  Layer                   Responsibility
  ----------------------- --------------------
  Cognito                 Identity
  **AgentCore Runtime**   Agent execution
  DeepSeek/Strands          Reasoning
  Gateway                 Tool routing
  Policy Engine           Authorization
  Lambda                  Backend execution
  Memory                  Persistent context
  CloudWatch              Observability
