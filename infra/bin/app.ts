#!/usr/bin/env node
import * as cdk from 'aws-cdk-lib';
import { BaseStackProps } from '../lib/types';
import {
  DockerImageStack,
  AgentCoreStack
} from '../lib/stacks';

// The app name prefixes every construct ID and the stack names. Changing it would create a
// second, separate deployment instead of updating the existing one.
const APP_NAME = "supportAgentDemo";

const app = new cdk.App();
const deploymentProps: BaseStackProps = {
  appName: APP_NAME,
  /* If you don't specify 'env', this stack will be environment-agnostic.
   * Account/Region-dependent features and context lookups will not work,
   * but a single synthesized template can be deployed anywhere. */

  /* Uncomment the next line to specialize this stack for the AWS Account
   * and Region that are implied by the current CLI configuration. */
  // env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION },

  /* For more information, see https://docs.aws.amazon.com/cdk/latest/guide/environments.html */
}
const dockerImageStack = new DockerImageStack(app, `${APP_NAME}-DockerImageStack`, deploymentProps);
const agentCoreStack = new AgentCoreStack(app, `${APP_NAME}-AgentCoreStack`, {
  ...deploymentProps,
  imageUri: dockerImageStack.imageUri
});
agentCoreStack.addDependency(dockerImageStack);
