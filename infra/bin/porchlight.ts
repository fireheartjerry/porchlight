#!/usr/bin/env node
/**
 * Porchlight app stack entry point.
 *
 * Everything except the AgentCore runtime lives in one stack: the DynamoDB table, the
 * S3SessionManager bucket, the API Lambda behind a Function URL, the hourly scheduler, and
 * the CloudFront distribution that serves the UI and proxies `/api/*` to the Function URL.
 *
 * Account and region resolution, in order:
 *
 *   account   `-c account=...` → CDK_DEFAULT_ACCOUNT → 892077329800 (a placeholder, so that
 *             `npx cdk synth` works on a machine with no AWS credentials at all)
 *   region    `-c region=...` → CDK_DEFAULT_REGION (only when the CLI actually resolved an
 *             account; without credentials its region is a guess) → AWS_REGION →
 *             AWS_DEFAULT_REGION → us-east-1, the region the rest of Porchlight defaults to
 */
import 'source-map-support/register';
import * as cdk from 'aws-cdk-lib';
import { PorchlightStack } from '../lib/porchlight-stack';

/** Placeholder account, used only when no credentials are configured (synth, CI). */
const FALLBACK_ACCOUNT = '892077329800';

/** Porchlight's home region — where Bedrock access and the AgentCore runtime are set up. */
const FALLBACK_REGION = 'us-east-1';

const app = new cdk.App();

const context = (key: string): string | undefined => {
  const value = app.node.tryGetContext(key);
  if (value === undefined || value === null) return undefined;
  const text = String(value).trim();
  return text.length > 0 ? text : undefined;
};

const credentialledRegion = process.env.CDK_DEFAULT_ACCOUNT ? process.env.CDK_DEFAULT_REGION : undefined;

const account = context('account') ?? process.env.CDK_DEFAULT_ACCOUNT ?? FALLBACK_ACCOUNT;
const region =
  context('region') ??
  credentialledRegion ??
  process.env.AWS_REGION ??
  process.env.AWS_DEFAULT_REGION ??
  FALLBACK_REGION;

const stackName = context('stackName') ?? 'PorchlightAppStack';

new PorchlightStack(app, stackName, {
  env: { account, region },
  stackName,
  description:
    'Porchlight app stack: DynamoDB, session bucket, API Lambda (Function URL + Lambda Web Adapter), ' +
    'EventBridge Scheduler sweep/brief, and the CloudFront-fronted web UI.',
  tags: {
    project: 'porchlight',
    'managed-by': 'cdk',
  },
});

app.synth();
