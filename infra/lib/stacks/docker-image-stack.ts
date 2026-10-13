import * as cdk from 'aws-cdk-lib/core';
import { Construct } from 'constructs/lib/construct';
import * as ecr_assets from 'aws-cdk-lib/aws-ecr-assets'
import { Platform } from 'aws-cdk-lib/aws-ecr-assets'
import { BaseStackProps } from '../types';
import * as path from 'path';

export interface DockerImageStackProps extends BaseStackProps {}

export class DockerImageStack extends cdk.Stack {
    readonly imageUri: string

    constructor(scope: Construct, id: string, props: DockerImageStackProps) {
        super(scope, id, props);

        // ⚠️  LINUX_ARM64 required — AgentCore Runtime only accepts arm64 container images.
        // Deploying an amd64 image will fail with:
        //   "Architecture incompatible. Supported platforms: [arm64]"
        // Run this from a t4g (Graviton arm64) EC2 instance so Docker builds natively.
        const asset = new ecr_assets.DockerImageAsset(this, `${props.appName}-AppImage`, {
            directory: path.join(__dirname, "../../../"), // path to root of the project
            platform: Platform.LINUX_ARM64,
        });

        this.imageUri = asset.imageUri;
        new cdk.CfnOutput(this, 'ImageUri', { value: this.imageUri });
    }
}
