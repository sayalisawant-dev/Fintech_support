import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';

/*
 * MCP tool schemas the AgentCore Gateway exposes to the agent.
 * Every tool name must have a handler in lambdas/banking_tools/handler.py (TOOLS);
 * test/agentcore-stack.test.ts fails if the two drift apart.
 */

type ToolDefinition = bedrockagentcore.CfnGatewayTarget.ToolDefinitionProperty;

// Customer and account tools (CustomerTarget)
export const CUSTOMER_TOOLS: ToolDefinition[] = [
    {
        name: "find_customer",
        description: "Find the signed-in customer's profile by their exact email address. Returns customer ID, name, tier and KYC status. Use this first to get the customer_id.",
        inputSchema: {
            type: "object",
            properties: {
                email: { type: 'string', description: "The customer's email address (e.g., john@example.com)" }
            },
            required: ['email']
        }
    },
    {
        name: "get_customer",
        description: "Look up a customer profile by customer ID. Returns name, email, member since date, tier and KYC status.",
        inputSchema: {
            type: "object",
            properties: {
                customer_id: { type: 'string', description: 'The customer ID to look up (e.g., CUST-001)' }
            },
            required: ['customer_id']
        }
    },
    {
        name: "list_accounts",
        description: "List a customer's bank accounts (checking, savings, credit card) with balances, credit limits and payment due dates, plus total deposits and total card balance.",
        inputSchema: {
            type: "object",
            properties: {
                customer_id: { type: 'string', description: 'The customer ID (e.g., CUST-001)' }
            },
            required: ['customer_id']
        }
    }
];

// Transaction, spending, dispute and transfer tools (BankingTarget)
export const BANKING_TOOLS: ToolDefinition[] = [
    {
        name: "list_transactions",
        description: "List a customer's recent transactions (newest first). Negative amounts are charges/money out, positive amounts are deposits/money in. Optionally filter by account or category.",
        inputSchema: {
            type: "object",
            properties: {
                customer_id: { type: 'string', description: 'The customer ID (e.g., CUST-001)' },
                account_id: { type: 'string', description: 'Optional account ID to filter by (e.g., CARD-1003)' },
                category: { type: 'string', description: 'Optional category filter (e.g., dining, groceries, subscriptions, travel, utilities, housing, income)' },
                limit: { type: 'integer', description: 'Maximum number of transactions to return (default: 20)' }
            },
            required: ['customer_id']
        }
    },
    {
        name: "get_transaction",
        description: "Look up a single transaction by ID, including merchant, amount, status and any open dispute.",
        inputSchema: {
            type: "object",
            properties: {
                transaction_id: { type: 'string', description: 'The transaction ID (e.g., TXN-1007)' }
            },
            required: ['transaction_id']
        }
    },
    {
        name: "get_spending_summary",
        description: "Summarise a customer's cash flow: total income, total spend, net cash flow and spend by category. Transfers between the customer's own accounts are excluded.",
        inputSchema: {
            type: "object",
            properties: {
                customer_id: { type: 'string', description: 'The customer ID (e.g., CUST-001)' },
                month: { type: 'string', description: 'Optional month in YYYY-MM format (e.g., 2025-02)' }
            },
            required: ['customer_id']
        }
    },
    {
        name: "dispute_transaction",
        description: "Open a dispute on a posted charge (e.g., unrecognised, duplicate, or wrong amount) and apply a provisional credit. Requires transaction ID, dispute amount and reason.",
        inputSchema: {
            type: "object",
            properties: {
                transaction_id: { type: 'string', description: 'The transaction ID to dispute (e.g., TXN-1006)' },
                amount: { type: 'number', description: 'The amount to dispute in dollars (must include decimal point, e.g., 15.99, 399.0)' },
                reason: { type: 'string', description: 'Reason for the dispute (e.g., duplicate_charge, unrecognised_charge, wrong_amount, goods_not_received)' }
            },
            required: ['transaction_id', 'amount', 'reason']
        }
    },
    {
        name: "transfer_funds",
        description: "Transfer money between two of the same customer's deposit accounts (checking and savings only). Returns the new balances.",
        inputSchema: {
            type: "object",
            properties: {
                customer_id: { type: 'string', description: 'The customer ID who owns both accounts (e.g., CUST-001)' },
                from_account_id: { type: 'string', description: 'Source account ID (e.g., ACC-1001)' },
                to_account_id: { type: 'string', description: 'Destination account ID (e.g., ACC-1002)' },
                amount: { type: 'number', description: 'Amount in dollars (must include decimal point, e.g., 250.0)' }
            },
            required: ['customer_id', 'from_account_id', 'to_account_id', 'amount']
        }
    }
];
