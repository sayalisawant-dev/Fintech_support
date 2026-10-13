import * as fs from 'fs';
import * as path from 'path';
import * as cdk from 'aws-cdk-lib';
import { Match, Template } from 'aws-cdk-lib/assertions';
import { AgentCoreStack } from '../lib/stacks';

const IMAGE_URI = '123456789012.dkr.ecr.us-east-1.amazonaws.com/agent:latest';

function synth(context: Record<string, string> = {}): Template {
  const app = new cdk.App({ context });
  const stack = new AgentCoreStack(app, 'TestAgentCoreStack', { appName: 'supportAgentDemo', imageUri: IMAGE_URI });
  return Template.fromStack(stack);
}

/** Tool names the Lambda can route, read from the TOOLS dict in lambdas/banking_tools/handler.py. */
function lambdaToolNames(): string[] {
  const source = fs.readFileSync(path.join(__dirname, '../../lambdas/banking_tools/handler.py'), 'utf8');
  const block = source.match(/^TOOLS = \{([\s\S]*?)^\}/m);
  if (!block) throw new Error('TOOLS dict not found in handler.py');
  return [...block[1].matchAll(/"(\w+)":/g)].map(m => m[1]).sort();
}

describe('AgentCoreStack', () => {
  const template = synth();

  test('one Lambda serves every tool', () => {
    template.resourceCountIs('AWS::Lambda::Function', 1);
    template.hasResourceProperties('AWS::Lambda::Function', {
      Handler: 'banking_tools.handler.lambda_handler',
      Runtime: 'python3.12',
    });
  });

  test('both Gateway targets invoke the same Lambda', () => {
    const targets = Object.values(template.findResources('AWS::BedrockAgentCore::GatewayTarget'));
    expect(targets).toHaveLength(2);
    const lambdaArns = targets.map(t => JSON.stringify(t.Properties.TargetConfiguration.Mcp.Lambda.LambdaArn));
    expect(new Set(lambdaArns).size).toBe(1);
  });

  test('Gateway tool schemas match the Lambda handlers', () => {
    const targets = Object.values(template.findResources('AWS::BedrockAgentCore::GatewayTarget'));
    const schemaNames = targets
      .flatMap(t => t.Properties.TargetConfiguration.Mcp.Lambda.ToolSchema.InlinePayload)
      .map((tool: { Name: string }) => tool.Name)
      .sort();
    expect(schemaNames).toEqual(lambdaToolNames());
  });

  test('memory keeps its name and the namespaces the agent reads', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Memory', {
      Name: 'financialAssistant_Memory',
      MemoryStrategies: Match.arrayWith([
        Match.objectLike({ SemanticMemoryStrategy: Match.objectLike({ Namespaces: ['/facts/{actorId}/'] }) }),
        Match.objectLike({ UserPreferenceMemoryStrategy: Match.objectLike({ Namespaces: ['/preferences/{actorId}/'] }) }),
        Match.objectLike({ SummaryMemoryStrategy: Match.objectLike({ Namespaces: ['/summaries/{actorId}/{sessionId}/'] }) }),
        Match.objectLike({ EpisodicMemoryStrategy: Match.objectLike({ Namespaces: ['/episodes/{actorId}/{sessionId}/'] }) }),
      ]),
    });
  });

  test('runtime gets the agent settings and defaults to DeepSeek V3.2', () => {
    template.hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      AgentRuntimeName: 'supportAgentDemo_Agent',
      AgentRuntimeArtifact: { ContainerConfiguration: { ContainerUri: IMAGE_URI } },
      RequestHeaderConfiguration: { RequestHeaderAllowlist: ['Authorization'] },
      EnvironmentVariables: Match.objectLike({
        GATEWAY_URL: Match.anyValue(),
        BEDROCK_AGENTCORE_MEMORY_ID: Match.anyValue(),
        MODEL_ID: 'deepseek.v3.2',
      }),
    });
  });

  test('modelId context overrides the model', () => {
    synth({ modelId: 'us.amazon.nova-pro-v1:0' }).hasResourceProperties('AWS::BedrockAgentCore::Runtime', {
      EnvironmentVariables: Match.objectLike({ MODEL_ID: 'us.amazon.nova-pro-v1:0' }),
    });
  });

  test('Cognito has the tier groups the Cedar policies use', () => {
    for (const group of ['standard', 'premium', 'vip']) {
      template.hasResourceProperties('AWS::Cognito::UserPoolGroup', { GroupName: group });
    }
  });

  test('exports every output the scripts read from cdk-outputs.json', () => {
    const outputs = Object.keys(template.findOutputs('*'));
    for (const key of [
      'UserPoolId', 'ClientId', 'CognitoDomain', 'Region', 'AccountId', 'RuntimeArn', 'RuntimeId',
      'RuntimeName', 'GatewayUrl', 'GatewayId', 'MemoryId', 'MemoryArn', 'AuthorizerDiscoveryUrl',
    ]) {
      expect(outputs).toContain(key);
    }
  });
});
