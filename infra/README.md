# Infrastructure (AWS CDK, TypeScript)

Two stacks, deployed together:

| Stack | What it creates |
|---|---|
| `supportAgentDemo-DockerImageStack` | The agent's arm64 container image, built from the repo root `Dockerfile` and pushed to ECR |
| `supportAgentDemo-AgentCoreStack` | AgentCore Runtime (+ PROD/DEV endpoints), Gateway with CustomerTarget and BankingTarget, the banking-tools Lambda, AgentCore Memory, Cognito user pool, groups and app client, IAM roles |

The stack names and construct IDs are kept stable on purpose: a deploy updates the resources in
place. Changing `APP_NAME` in `bin/app.ts` would create a second deployment.

## Layout

```
infra/
├── bin/app.ts                    # CDK app: both stacks and their dependency
├── lib/
│   ├── stacks/
│   │   ├── docker-image-stack.ts # container image asset (LINUX_ARM64)
│   │   └── agentcore-stack.ts    # Runtime, Gateway, Lambda, Memory, Cognito, IAM, outputs
│   ├── tool-schemas.ts           # MCP tool schemas served by the Gateway targets
│   └── types.ts
├── test/agentcore-stack.test.ts  # template assertions + Gateway/Lambda tool contract
└── cdk.json, package.json, tsconfig.json, jest.config.js
```

## Commands

Run from this folder:

```bash
npm ci                      # install the locked dependencies
npm run typecheck           # tsc --noEmit
npm test                    # jest
npm run synth               # cdk synth (no Docker needed)
npx cdk diff --all          # compare with what is deployed
npx cdk deploy --all --outputs-file ../cdk-outputs.json --require-approval never
```

`scripts/deploy.sh` at the repo root wraps the first deploy (pre-flight checks, bootstrap, deploy,
and generating `.bedrock_agentcore.yaml`).

Override the agent's model without code changes: `npx cdk deploy --all -c modelId=us.amazon.nova-pro-v1:0`.
