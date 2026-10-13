# TASKS --- Customer Support Agent

## Phase 1 --- Environment

-   [ ] Verify Git.
-   [ ] Clone repository.
-   [ ] Verify uv.
-   [ ] Verify Node.js 20+.
-   [ ] Verify Docker.
-   [ ] Verify AWS CLI v2.32.0+.
-   [ ] Run `aws sts get-caller-identity`.
-   [ ] Confirm AWS permissions.
-   [ ] Complete documented Anthropic model access requirement.

## Phase 2 --- AgentCore Runtime Deployment

-   [ ] Run `scripts/deploy.sh`.
-   [ ] Confirm Docker image build.
-   [ ] Confirm Runtime deployment.
-   [ ] Confirm Runtime is `READY` or `ACTIVE`.
-   [ ] Run `uv run agentcore status`.
-   [ ] Confirm the Runtime-hosted Strands agent is available.

## Phase 3 --- Supporting AgentCore Services

-   [ ] Confirm AgentCore Gateway.
-   [ ] Confirm AgentCore Memory.
-   [ ] Confirm Cognito User Pool.
-   [ ] Confirm Lambda backend functions.
-   [ ] Confirm CloudWatch observability.

## Phase 4 --- Cognito Authentication

-   [ ] Create a Cognito user.
-   [ ] Use a documented mock customer email.
-   [ ] Assign the user to `standard`.
-   [ ] Log in.
-   [ ] Export the bearer token.

## Phase 5 --- Runtime Invocation

-   [ ] Invoke the Runtime with `Who am I?`.
-   [ ] Confirm the Runtime-hosted agent identifies the authenticated
    user.
-   [ ] Invoke `Show me my recent orders`.
-   [ ] Confirm the Runtime-hosted agent reaches the order tool through
    Gateway.
-   [ ] Test a normal refund.

## Phase 6 --- Pre-Policy Baseline

-   [ ] Test a large refund such as `$399`.
-   [ ] Confirm the documented pre-policy behavior.

## Phase 7 --- Policy Engine

-   [ ] Create Policy Engine.
-   [ ] Select the supportAgentDemo Gateway.
-   [ ] Add read-only tool policy.
-   [ ] Add `standard` + refund amount \<= \$100 policy.
-   [ ] Associate Policy Engine with Gateway.

## Phase 8 --- Policy Validation

-   [ ] Invoke a large refund again through the Runtime.
-   [ ] Confirm Gateway/Policy Engine denies it.
-   [ ] Confirm the Runtime-hosted agent receives the policy violation.
-   [ ] Confirm Lambda does not execute the denied refund.

## Phase 9 --- Observability

-   [ ] Open CloudWatch GenAI Observability.
-   [ ] Open Bedrock AgentCore.
-   [ ] Find the Runtime invocation/session.
-   [ ] Inspect Runtime/model activity.
-   [ ] Inspect Gateway tool calls.
-   [ ] Inspect policy evaluation.
-   [ ] Inspect memory operations.
-   [ ] Verify the denied refund trace.

## Phase 10 --- Session Testing

-   [ ] Start a named session.
-   [ ] Make multiple Runtime invocations.
-   [ ] Confirm earlier conversation context can be referenced.

## Phase 11 --- Cleanup

-   [ ] Run `scripts/teardown.sh`.
-   [ ] Confirm Runtime and supporting resources are removed.
-   [ ] Confirm generated configuration files are removed.
