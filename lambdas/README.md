# Lambda functions

## banking_tools

One Lambda (construct `supportAgentDemo-BankingLambda`, Python 3.12, handler
`banking_tools.handler.lambda_handler`) serves all eight tools behind the AgentCore Gateway. Both
Gateway targets invoke it, so every tool reads and writes the same in-memory data.

| Module | Tools |
|---|---|
| `customers.py` | `find_customer`, `get_customer`, `list_accounts` |
| `transactions.py` | `list_transactions`, `get_transaction`, `get_spending_summary` |
| `disputes.py` | `dispute_transaction` |
| `transfers.py` | `transfer_funds` |
| `data.py` | Mock customers, accounts, transactions; disputes and transfers made at runtime |
| `responses.py` | `{"statusCode", "body"}` envelope and error format |
| `handler.py` | Routes the Gateway's `<target>___<tool>` name to a tool |

It uses only the standard library, so the folder is deployed as-is with no build step. The data
resets on every deploy or cold start.

### Adding a tool

1. Write the function in the matching module and add it to `TOOLS` in `handler.py`.
2. Add its schema to `CUSTOMER_TOOLS` or `BANKING_TOOLS` in `infra/lib/tool-schemas.ts`.
3. Add unit tests in `tests/unit/test_banking_tools.py`, then run `make check`.
   The CDK test fails if a schema has no handler or a handler has no schema.
4. If the tool moves money or changes data, add its name to `SENSITIVE_TOOLS` in
   `src/financial_assistant/guardrails.py` and cover it with a Cedar policy.
