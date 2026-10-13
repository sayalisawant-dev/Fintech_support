# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `ui/`: Streamlit chat UI. Signs in through the existing Cognito app client (PKCE, callback on
  port 3000), streams replies from the deployed AgentCore Runtime with the user's token, refreshes
  the token before it expires, and shows Yes/No buttons when the confirmation gate asks for a "yes".
  Start it with `make ui`; guide in `docs/runbooks/ui_guide.txt`.

## [0.2.0] - 2026-10-07

Restructured to a production layout. Agent behaviour, tool schemas, stack names and construct IDs
are unchanged, so a deploy updates the existing resources in place.

### Changed
- Agent code moved from `src/main.py` to the `src/financial_assistant/` package, split into
  `main`, `auth`, `prompts`, `guardrails`, `streaming`, `memory`, `gateway`, `model` and `config`.
  The container now runs `python -m financial_assistant.main`.
- Lambda code moved from `mcp/lambda/` to the `lambdas/banking_tools/` package (handler
  `banking_tools.handler.lambda_handler`), split by domain.
- CDK app moved from `cdk/` to `infra/` (`bin/cdk.ts` is now `bin/app.ts`); tool schemas moved to
  `infra/lib/tool-schemas.ts`.
- Evaluations moved from `scripts/run_eval.py` and `scripts/eval_cases.json` to `evals/`. Dispute and
  transfer cases now include the "yes" turn the confirmation gate needs.
- `commands_ec2` moved to `docs/runbooks/commands_ec2.txt`; images to `docs/images/`.
- Cognito group descriptions no longer mention refunds.
- `.dockerignore` is an allowlist: the image gets `pyproject.toml`, `uv.lock` and `src/` only.
- The Dockerfile pins uv 0.12.23 instead of `latest`, for reproducible image builds.
- `pytest` moved to the dev dependency group; `scripts/deploy.sh` uses `npm ci`.

### Added
- Unit tests for the agent modules and every Lambda tool (`tests/unit/`), and CDK template tests,
  including a check that the Gateway tool schemas and the Lambda handlers match (`infra/test/`).
- Ruff lint and format configuration, `Makefile`, GitHub Actions CI, `.gitignore`, `.editorconfig`.
- `README.md`, `docs/architecture.md`, `docs/policy-engine.md`, `docs/runbooks/troubleshooting.md`,
  `infra/README.md`, `lambdas/README.md`.

### Removed
- The unused customer Lambda: both Gateway targets already used the banking Lambda.
- Unused dependencies `strands-agents-tools` and `pytest-asyncio` (22 fewer packages in the lock and
  the image).
- Dead code (`format_response`), the old customer-support Lambda handlers (`handler.py`,
  `order_handler.py`), the Brazil `Config` file, the commented-out tests and build artefacts.
- Outdated customer-support documents moved to `docs/archive/`.

## [0.1.0] - 2026-10-06

### Added
- Financial assistant: accounts, balances, transactions, spending summary, disputes and transfers
  for two mock customers, served by the Gateway from Lambda.
- Confirmation gate: disputes and transfers run only after a "yes" in a separate turn.
- Filter for DeepSeek's leaked tool-call markup in streamed replies.

### Fixed
- DeepSeek V3.2 model ID (`deepseek.v3.2`), arm64 image, mcp 1.x client, dependencies from `uv.lock`.
- Stale balances after a transfer: both Gateway targets now invoke the same Lambda.
- Invented dispute dates: the prompt forbids made-up IDs, dates and statuses.
- Memory renamed to `financialAssistant_Memory`.
