# Developer shortcuts. Every target is a plain command you can also run by hand
# (docs/runbooks/commands_ec2.txt lists them step by step).

INFRA := infra
OUTPUTS := $(CURDIR)/cdk-outputs.json

.PHONY: help install lint format test test-infra check synth deploy update eval ui observability teardown clean

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-14s %s\n", $$1, $$2}'

install: ## Install Python (uv) and CDK (npm) dependencies from the lockfiles
	uv sync --locked
	cd $(INFRA) && npm ci

lint: ## Lint and format-check Python, typecheck the CDK app
	uv run ruff check .
	uv run ruff format --check .
	cd $(INFRA) && npm run typecheck

format: ## Auto-format Python
	uv run ruff format .
	uv run ruff check --fix .

test: ## Python unit tests (agent + Lambda tools)
	uv run pytest

test-infra: ## CDK template tests
	cd $(INFRA) && npm test

check: lint test test-infra ## Everything CI runs

synth: ## Synthesize the CloudFormation templates (no Docker needed)
	cd $(INFRA) && npm run synth

deploy: ## First deploy: pre-flight checks, bootstrap, deploy, agentcore config
	scripts/deploy.sh

update: ## Redeploy after a code change
	cd $(INFRA) && npx cdk deploy --all --outputs-file $(OUTPUTS) --require-approval never

eval: ## Run the evaluation conversations and score them (needs a bearer token)
	uv run evals/run_eval.py

ui: ## Start the chat UI on http://localhost:8501 (sign-in needs port 3000 forwarded)
	uv run --with-requirements ui/requirements.txt streamlit run ui/app.py \
		--server.address localhost --server.port 8501 --client.toolbarMode minimal

observability: ## Turn on Transaction Search and Gateway/Memory log and trace delivery
	uv run scripts/observability.py setup

teardown: ## Destroy every deployed resource
	scripts/teardown.sh

clean: ## Remove local build and test artifacts
	rm -rf $(INFRA)/cdk.out .pytest_cache .ruff_cache
	find . -name __pycache__ -type d -prune -not -path './.venv/*' -exec rm -rf {} +
