import * as cdk from 'aws-cdk-lib/core';
import { Construct } from 'constructs/lib/construct';
import * as bedrockagentcore from 'aws-cdk-lib/aws-bedrockagentcore';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda'
import * as cognito from 'aws-cdk-lib/aws-cognito';
import { BaseStackProps } from '../types';
import { BANKING_TOOLS, CUSTOMER_TOOLS } from '../tool-schemas';
import * as path from 'path';

export interface AgentCoreStackProps extends BaseStackProps {
    imageUri: string
}

export class AgentCoreStack extends cdk.Stack {
    readonly agentCoreRuntime: bedrockagentcore.CfnRuntime;
    readonly agentCoreGateway: bedrockagentcore.CfnGateway;
    readonly agentCoreMemory: bedrockagentcore.CfnMemory;
    readonly bankingToolsLambda: lambda.Function;

    constructor(scope: Construct, id: string, props: AgentCoreStackProps) {
        super(scope, id, props);

        const region = cdk.Stack.of(this).region;
        const accountId = cdk.Stack.of(this).account;

        /*****************************
        * AgentCore Gateway
        ******************************/

        // One Lambda serves every banking tool (customers, accounts, transactions, spending,
        // disputes, transfers), so balances stay in sync across tools. Code: lambdas/banking_tools/
        this.bankingToolsLambda = new lambda.Function(this, `${props.appName}-BankingLambda`, {
            runtime: lambda.Runtime.PYTHON_3_12,
            handler: "banking_tools.handler.lambda_handler",
            code: lambda.Code.fromAsset(path.join(__dirname, '../../../lambdas'), {
                exclude: ['**/__pycache__', '**/*.pyc', '*.md'],
            }),
        });

        const agentCoreGatewayRole = new iam.Role(this, `${props.appName}-AgentCoreGatewayRole`, {
            assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
            description: 'IAM role for Bedrock AgentCore Gateway',
        });

        this.bankingToolsLambda.grantInvoke(agentCoreGatewayRole);

        // Add Policy Engine permissions to Gateway role
        // Required for Policy Engine integration (per IAM Service Authorization Reference):
        // - GetPolicyEngine: retrieve policy engine
        // - AuthorizeAction: evaluate Cedar policies for authorization requests
        // - PartiallyAuthorizeActions: partial evaluation for listing allowed tools
        agentCoreGatewayRole.addToPolicy(new iam.PolicyStatement({
            effect: iam.Effect.ALLOW,
            actions: [
                'bedrock-agentcore:GetPolicyEngine',
                'bedrock-agentcore:AuthorizeAction',
                'bedrock-agentcore:PartiallyAuthorizeActions',
            ],
            resources: [
                `arn:aws:bedrock-agentcore:${region}:${accountId}:policy-engine/*`,
                `arn:aws:bedrock-agentcore:${region}:${accountId}:gateway/*`,
            ],
        }));

        // Create gateway resource
        // Cognito resources
        const cognitoUserPool = new cognito.UserPool(this, `${props.appName}-CognitoUserPool`, {
            customAttributes: {
                // Customer tier ("standard", "premium" or "vip"), set by scripts/cognito-user.py.
                // The name is historical; renaming a custom attribute would replace the user pool.
                'refund_tier': new cognito.StringAttribute({
                    mutable: true,
                }),
            },
        });

        // Cognito Groups for tier-based authorization
        // These automatically add 'cognito:groups' claim to access tokens, which the Cedar
        // policies in the Policy Engine use to set dispute and transfer limits (docs/policy-engine.md).
        new cognito.CfnUserPoolGroup(this, `${props.appName}-StandardGroup`, {
            userPoolId: cognitoUserPool.userPoolId,
            groupName: 'standard',
            description: 'Standard tier customers',
            precedence: 3,
        });

        new cognito.CfnUserPoolGroup(this, `${props.appName}-PremiumGroup`, {
            userPoolId: cognitoUserPool.userPoolId,
            groupName: 'premium',
            description: 'Premium tier customers',
            precedence: 2,
        });

        new cognito.CfnUserPoolGroup(this, `${props.appName}-VIPGroup`, {
            userPoolId: cognitoUserPool.userPoolId,
            groupName: 'vip',
            description: 'VIP tier customers',
            precedence: 1,
        });

        // Define granular scopes for Runtime and Gateway
        const runtimeInvokeScope = {
            scopeName: 'runtime:invoke',
            scopeDescription: 'Permission to invoke AgentCore Runtime',
        };

        const gatewayInvokeScope = {
            scopeName: 'gateway:invoke',
            scopeDescription: 'Permission to invoke AgentCore Gateway MCP tools',
        };

        const cognitoResourceServer = cognitoUserPool.addResourceServer(`${props.appName}-CognitoResourceServer`, {
            identifier: `${props.appName}-api`,
            scopes: [runtimeInvokeScope, gatewayInvokeScope],
        });

        // User App Client (for end-user authentication)
        const cognitoUserAppClient = new cognito.UserPoolClient(this, `${props.appName}-CognitoUserAppClient`, {
            userPool: cognitoUserPool,
            generateSecret: false, // Public client for SPA
            authFlows: {
                userPassword: true,  // Enable USER_PASSWORD_AUTH for CLI testing
                userSrp: true,       // Enable SRP auth
            },
            oAuth: {
                flows: {
                    authorizationCodeGrant: true,
                },
                scopes: [
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE,
                    // Both scopes available - user requests what they need
                    cognito.OAuthScope.resourceServer(cognitoResourceServer, runtimeInvokeScope),
                    cognito.OAuthScope.resourceServer(cognitoResourceServer, gatewayInvokeScope),
                ],
                callbackUrls: ['http://localhost:3000/callback'],
                logoutUrls: ['http://localhost:3000/logout'],
            },
            supportedIdentityProviders: [cognito.UserPoolClientIdentityProvider.COGNITO],
            accessTokenValidity: cdk.Duration.hours(1),
            idTokenValidity: cdk.Duration.hours(1),
            refreshTokenValidity: cdk.Duration.days(30),
            readAttributes: new cognito.ClientAttributes()
                .withStandardAttributes({ email: true, emailVerified: true })
                .withCustomAttributes('refund_tier'),
        });

        cognitoUserPool.addDomain(`${props.appName}-CognitoDomain`, {
            cognitoDomain: {
                domainPrefix: `${props.appName.toLowerCase()}-${cdk.Aws.ACCOUNT_ID}-${region}`,
            },
        });

        this.agentCoreGateway = new bedrockagentcore.CfnGateway(this, `${props.appName}-AgentCoreGateway`, {
            name: `${props.appName}-Gateway`,
            protocolType: "MCP",
            roleArn: agentCoreGatewayRole.roleArn,
            authorizerType: "CUSTOM_JWT",
            authorizerConfiguration: {
                customJwtAuthorizer: {
                    discoveryUrl: `https://cognito-idp.${region}.amazonaws.com/${cognitoUserPool.userPoolId}/.well-known/openid-configuration`,
                    allowedClients: [
                        cognitoUserAppClient.userPoolClientId,  // User-facing client only
                    ],
                    allowedScopes: [
                        `${props.appName}-api/${gatewayInvokeScope.scopeName}`,  // Required scope for Gateway
                    ],
                },
            },
        });

        // Both targets point at the same Lambda so every tool shares one copy of the data.
        // Tool schemas: lib/tool-schemas.ts
        const customerTarget = new bedrockagentcore.CfnGatewayTarget(this, `${props.appName}-CustomerTarget`, {
            name: `${props.appName}-CustomerTarget`,
            gatewayIdentifier: this.agentCoreGateway.attrGatewayIdentifier,
            credentialProviderConfigurations: [
                {
                    credentialProviderType: "GATEWAY_IAM_ROLE",
                },
            ],
            targetConfiguration: {
                mcp: {
                    lambda: {
                        lambdaArn: this.bankingToolsLambda.functionArn,
                        toolSchema: {
                            inlinePayload: CUSTOMER_TOOLS,
                        }
                    }
                }
            }
        });

        const bankingTarget = new bedrockagentcore.CfnGatewayTarget(this, `${props.appName}-BankingTarget`, {
            name: `${props.appName}-BankingTarget`,
            gatewayIdentifier: this.agentCoreGateway.attrGatewayIdentifier,
            credentialProviderConfigurations: [
                {
                    credentialProviderType: "GATEWAY_IAM_ROLE",
                },
            ],
            targetConfiguration: {
                mcp: {
                    lambda: {
                        lambdaArn: this.bankingToolsLambda.functionArn,
                        toolSchema: {
                            inlinePayload: BANKING_TOOLS,
                        }
                    }
                }
            }
        });

        // Ensure GatewayTargets wait for the IAM policy (created by grantInvoke) to be attached to the role
        customerTarget.node.addDependency(agentCoreGatewayRole);
        bankingTarget.node.addDependency(agentCoreGatewayRole);

        /*****************************
        * AgentCore Memory
        ******************************/

        this.agentCoreMemory = new bedrockagentcore.CfnMemory(this, `${props.appName}-AgentCoreMemoryV2`, {
            name: "financialAssistant_Memory",
            eventExpiryDuration: 30,
            description: "Memory resource with all built-in strategies",
            memoryStrategies: [
                {
                    semanticMemoryStrategy: {
                        name: "FactExtractor",
                        namespaces: ["/facts/{actorId}/"],
                    }
                },
                {
                    userPreferenceMemoryStrategy: {
                        name: "PreferenceLearner",
                        namespaces: ["/preferences/{actorId}/"],
                    }
                },
                {
                    summaryMemoryStrategy: {
                        name: "SessionSummarizer",
                        namespaces: ["/summaries/{actorId}/{sessionId}/"],
                    }
                },
                {
                    episodicMemoryStrategy: {
                        name: "EpisodeTracker",
                        namespaces: ["/episodes/{actorId}/{sessionId}/"],
                        reflectionConfiguration: {
                            namespaces: ["/episodes/{actorId}/"],
                        }
                    }
                }
            ],
        });
        
        /*****************************
        * AgentCore Runtime
        ******************************/

        // taken from https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-permissions.html#runtime-permissions-execution
        const runtimePolicy = new iam.PolicyDocument({
            statements: [
                new iam.PolicyStatement({
                    sid: 'ECRImageAccess',
                    effect: iam.Effect.ALLOW,
                    actions: ['ecr:BatchGetImage', 'ecr:GetDownloadUrlForLayer'],
                    resources: [
                        `arn:aws:ecr:${region}:${accountId}:repository/*`,
                    ],
                }),
                new iam.PolicyStatement({
                    effect: iam.Effect.ALLOW,
                    actions: ['logs:DescribeLogStreams', 'logs:CreateLogGroup'],
                    resources: [
                        `arn:aws:logs:${region}:${accountId}:log-group:/aws/bedrock-agentcore/runtimes/*`,
                    ],
                }),
                new iam.PolicyStatement({
                    effect: iam.Effect.ALLOW,
                    actions: ['logs:DescribeLogGroups'],
                    resources: [
                        `arn:aws:logs:${region}:${accountId}:log-group:*`,
                    ],
                }),
                new iam.PolicyStatement({
                    effect: iam.Effect.ALLOW,
                    actions: ['logs:CreateLogStream', 'logs:PutLogEvents'],
                    resources: [
                        `arn:aws:logs:${region}:${accountId}:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*`,
                    ],
                }),
                new iam.PolicyStatement({
                    sid: 'ECRTokenAccess',
                    effect: iam.Effect.ALLOW,
                    actions: ['ecr:GetAuthorizationToken'],
                    resources: ['*'],
                }),
                new iam.PolicyStatement({
                    effect: iam.Effect.ALLOW,
                    actions: [
                        'xray:PutTraceSegments',
                        'xray:PutTelemetryRecords',
                        'xray:GetSamplingRules',
                        'xray:GetSamplingTargets',
                    ],
                resources: ['*'],
                }),
                new iam.PolicyStatement({
                    effect: iam.Effect.ALLOW,
                    actions: ['cloudwatch:PutMetricData'],
                    resources: ['*'],
                    conditions: {
                        StringEquals: { 'cloudwatch:namespace': 'bedrock-agentcore' },
                    },
                }),
                new iam.PolicyStatement({
                    sid: 'GetAgentAccessToken',
                    effect: iam.Effect.ALLOW,
                    actions: [
                        'bedrock-agentcore:GetWorkloadAccessToken',
                        'bedrock-agentcore:GetWorkloadAccessTokenForJWT',
                        'bedrock-agentcore:GetWorkloadAccessTokenForUserId',
                    ],
                    resources: [
                        `arn:aws:bedrock-agentcore:${region}:${accountId}:workload-identity-directory/default`,
                        `arn:aws:bedrock-agentcore:${region}:${accountId}:workload-identity-directory/default/workload-identity/agentName-*`,
                    ],
                }),
                new iam.PolicyStatement({
                    sid: 'BedrockModelInvocation',
                    effect: iam.Effect.ALLOW,
                    actions: ['bedrock:InvokeModel', 'bedrock:InvokeModelWithResponseStream'],
                    resources: [
                        `arn:aws:bedrock:*::foundation-model/*`,
                        `arn:aws:bedrock:${region}:${accountId}:*`,
                    ],
                }),
                // Required for Amazon Nova Pro and other models gated behind Marketplace.
                // Without these permissions the runtime role receives:
                //   "AccessDeniedException: aws-marketplace:ViewSubscriptions is not authorized"
                new iam.PolicyStatement({
                    sid: 'MarketplaceModelAccess',
                    effect: iam.Effect.ALLOW,
                    actions: [
                        'aws-marketplace:ViewSubscriptions',
                        'aws-marketplace:Subscribe',
                        'aws-marketplace:Unsubscribe',
                    ],
                    resources: ['*'],
                }),
                new iam.PolicyStatement({
                    sid: 'AgentCoreMemoryAccess',
                    effect: iam.Effect.ALLOW,
                    actions: [
                        'bedrock-agentcore:CreateEvent',
                        'bedrock-agentcore:GetEvent',
                        'bedrock-agentcore:ListEvents',
                        'bedrock-agentcore:DeleteEvent',
                        'bedrock-agentcore:GetMemory',
                        'bedrock-agentcore:RetrieveMemoryRecords',
                    ],
                    resources: [
                        this.agentCoreMemory.attrMemoryArn,
                    ],
                }),
            ],
        });

        const runtimeRole = new iam.Role(this, `${props.appName}-AgentCoreRuntimeRole`, {
            assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com'),
            description: 'IAM role for Bedrock AgentCore Runtime',
            inlinePolicies: {
                RuntimeAccessPolicy: runtimePolicy
            }
        });

        // Ensure role policy waits for memory resource ARN
        runtimeRole.node.addDependency(this.agentCoreMemory);

        this.agentCoreRuntime = new bedrockagentcore.CfnRuntime(this, `${props.appName}-AgentCoreRuntime`, {
            agentRuntimeArtifact: {
                containerConfiguration: {
                    containerUri: props.imageUri
                }
            },
            agentRuntimeName: "supportAgentDemo_Agent",
            protocolConfiguration: "HTTP",
            networkConfiguration: {
                networkMode: "PUBLIC"
            },
            roleArn: runtimeRole.roleArn,

            // JWT Authorizer Configuration
            authorizerConfiguration: {
                customJwtAuthorizer: {
                    discoveryUrl: `https://cognito-idp.${region}.amazonaws.com/${cognitoUserPool.userPoolId}/.well-known/openid-configuration`,
                    allowedClients: [
                        cognitoUserAppClient.userPoolClientId,  // User-facing client
                    ],
                },
            },

            // Pass Authorization header to container
            requestHeaderConfiguration: {
                requestHeaderAllowlist: ['Authorization'],
            },

            environmentVariables: {
                "AWS_REGION": region,
                "GATEWAY_URL": this.agentCoreGateway.attrGatewayUrl,
                "BEDROCK_AGENTCORE_MEMORY_ID": this.agentCoreMemory.attrMemoryId,
                // Bedrock model for the agent. Override with: cdk deploy -c modelId=<id>
                "MODEL_ID": this.node.tryGetContext('modelId') ?? 'deepseek.v3.2',
            }
        });

        // DEFAULT endpoint always points to newest published version. Optionally, can use these versioned endpoints below
        // https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/agent-runtime-versioning.html
        void new bedrockagentcore.CfnRuntimeEndpoint(this, `${props.appName}-AgentCoreRuntimeProdEndpoint`, {
            agentRuntimeId: this.agentCoreRuntime.attrAgentRuntimeId,
            agentRuntimeVersion: "1",
            name: "PROD"
        });

        void new bedrockagentcore.CfnRuntimeEndpoint(this, `${props.appName}-AgentCoreRuntimeDevEndpoint`, {
            agentRuntimeId: this.agentCoreRuntime.attrAgentRuntimeId,
            agentRuntimeVersion: "1",
            name: "DEV"
        });

        /*****************************
        * CfnOutputs — consumed by scripts/deploy.sh via --outputs-file
        ******************************/

        new cdk.CfnOutput(this, 'UserPoolId', { value: cognitoUserPool.userPoolId });
        new cdk.CfnOutput(this, 'ClientId', { value: cognitoUserAppClient.userPoolClientId });
        new cdk.CfnOutput(this, 'CognitoDomain', {
            value: `${props.appName.toLowerCase()}-${accountId}-${region}.auth.${region}.amazoncognito.com`,
        });
        new cdk.CfnOutput(this, 'Region', { value: region });
        new cdk.CfnOutput(this, 'AccountId', { value: accountId });
        new cdk.CfnOutput(this, 'RuntimeArn', { value: this.agentCoreRuntime.attrAgentRuntimeArn });
        new cdk.CfnOutput(this, 'RuntimeId', { value: this.agentCoreRuntime.attrAgentRuntimeId });
        new cdk.CfnOutput(this, 'RuntimeName', { value: 'supportAgentDemo_Agent' });
        new cdk.CfnOutput(this, 'GatewayUrl', { value: this.agentCoreGateway.attrGatewayUrl });
        new cdk.CfnOutput(this, 'GatewayId', { value: this.agentCoreGateway.attrGatewayIdentifier });
        new cdk.CfnOutput(this, 'MemoryId', { value: this.agentCoreMemory.attrMemoryId });
        new cdk.CfnOutput(this, 'MemoryArn', { value: this.agentCoreMemory.attrMemoryArn });
        new cdk.CfnOutput(this, 'AuthorizerDiscoveryUrl', {
            value: `https://cognito-idp.${region}.amazonaws.com/${cognitoUserPool.userPoolId}/.well-known/openid-configuration`,
        });
    }
}