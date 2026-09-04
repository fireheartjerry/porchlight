/**
 * The Porchlight app stack — everything except the AgentCore runtime.
 *
 * ```
 * CloudFront ─┬─ default  ─▶ S3 (web/dist, origin access control)
 *             └─ /api/*   ─▶ Lambda Function URL (FastAPI under the Lambda Web Adapter)
 *                                │
 *                                ├─ DynamoDB "porchlight" (single table, GSI1)
 *                                ├─ S3 "porchlight-sessions-<account>-<region>" (S3SessionManager)
 *                                └─ AgentCore Runtime (when runtimeArn is set) or Bedrock directly
 * EventBridge Scheduler ─ hourly sweep + 06:00 UTC brief ─▶ sweep Lambda (api.scheduled.handler)
 * ```
 *
 * Context (see `cdk.json`, override with `-c key=value`):
 *
 * | key             | default          | meaning                                             |
 * |-----------------|------------------|-----------------------------------------------------|
 * | `tableName`     | `porchlight`     | DynamoDB single-table name                           |
 * | `runtimeArn`    | `''`             | AgentCore Runtime ARN; empty → API runs the graph locally |
 * | `memoryId`      | `''`             | AgentCore Memory id; empty → local SQLite memory      |
 * | `lambdaBundle`  | `../build/lambda`| Output of `scripts/build_lambda.sh`                  |
 * | `webDist`       | `../web/dist`    | Built UI; skipped when it does not exist             |
 * | `fromAddr`      | `''`             | Verified SES sender for the live EmailChannel        |
 *
 * Nothing here needs credentials at synth time: missing bundles fall back to a stub asset so
 * `npx cdk synth` always succeeds.
 */
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';

import {
  Annotations,
  CfnOutput,
  Duration,
  RemovalPolicy,
  Stack,
  type StackProps,
} from 'aws-cdk-lib';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as logs from 'aws-cdk-lib/aws-logs';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3deploy from 'aws-cdk-lib/aws-s3-deployment';
import * as scheduler from 'aws-cdk-lib/aws-scheduler';
import * as schedulerTargets from 'aws-cdk-lib/aws-scheduler-targets';
import type { Construct } from 'constructs';

/** Public account that owns the AWS Lambda Web Adapter layers. */
const DEFAULT_LWA_ACCOUNT = '753240598075';

/** Layer version pinned from the awslabs/aws-lambda-web-adapter README. */
const DEFAULT_LWA_VERSION = '28';

/** The port uvicorn listens on inside the Lambda sandbox, and the port LWA proxies to. */
const APP_PORT = '8000';

export interface PorchlightStackProps extends StackProps {}

export class PorchlightStack extends Stack {
  /** Single-table store, matching `porchlight/store/dynamo_store.py`. */
  public readonly table: dynamodb.Table;

  /** Bucket behind Strands' `S3SessionManager`. */
  public readonly sessionBucket: s3.Bucket;

  /** FastAPI on Lambda, served through the Lambda Web Adapter. */
  public readonly api: lambda.Function;

  /** The API's Function URL (also the CloudFront `/api/*` origin). */
  public readonly apiUrl: lambda.FunctionUrl;

  /** CloudFront distribution serving the UI and proxying the API. */
  public readonly distribution: cloudfront.Distribution;

  constructor(scope: Construct, id: string, props: PorchlightStackProps = {}) {
    super(scope, id, props);

    const tableName = this.contextString('tableName', 'porchlight');
    const runtimeArn = this.contextString('runtimeArn', '');
    const memoryId = this.contextString('memoryId', '');
    const bundleDir = this.resolvePath(this.contextString('lambdaBundle', '../build/lambda'));
    const webDist = this.resolvePath(this.contextString('webDist', '../web/dist'));

    // --- storage ------------------------------------------------------------------------
    this.table = new dynamodb.Table(this, 'Table', {
      tableName,
      partitionKey: { name: 'pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'sk', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      timeToLiveAttribute: 'ttl',
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: RemovalPolicy.DESTROY,
    });
    this.table.addGlobalSecondaryIndex({
      indexName: 'GSI1',
      partitionKey: { name: 'gsi1pk', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'gsi1sk', type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.ALL,
    });

    this.sessionBucket = new s3.Bucket(this, 'SessionBucket', {
      bucketName: `porchlight-sessions-${this.account}-${this.region}`,
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: false,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      lifecycleRules: [{ id: 'expire-sessions', expiration: Duration.days(30) }],
    });

    // --- the Lambda bundle ---------------------------------------------------------------
    const code = this.bundleCode(bundleDir);
    const environment = this.lambdaEnvironment(runtimeArn, memoryId);

    // --- API Lambda (FastAPI behind the Lambda Web Adapter) -------------------------------
    const lwaLayer = lambda.LayerVersion.fromLayerVersionArn(
      this,
      'LambdaWebAdapter',
      `arn:${this.partition}:lambda:${this.region}:${this.contextString(
        'lwaLayerAccount',
        DEFAULT_LWA_ACCOUNT,
      )}:layer:LambdaAdapterLayerArm64:${this.contextString('lwaLayerVersion', DEFAULT_LWA_VERSION)}`,
    );

    this.api = new lambda.Function(this, 'ApiFunction', {
      description: 'Porchlight API — FastAPI served by uvicorn under the AWS Lambda Web Adapter.',
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      code,
      // The LWA layer's /opt/bootstrap execs this script; `run.sh` starts uvicorn.
      handler: 'run.sh',
      layers: [lwaLayer],
      memorySize: this.contextNumber('apiMemoryMb', 1536),
      timeout: Duration.minutes(15),
      environment: {
        ...environment,
        AWS_LAMBDA_EXEC_WRAPPER: '/opt/bootstrap',
        AWS_LWA_INVOKE_MODE: 'response_stream',
        AWS_LWA_PORT: APP_PORT,
        AWS_LWA_READINESS_CHECK_PATH: '/api/health',
        AWS_LWA_ASYNC_INIT: 'true',
        PORT: APP_PORT,
      },
      logGroup: new logs.LogGroup(this, 'ApiLogs', {
        retention: logs.RetentionDays.TWO_WEEKS,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });

    this.apiUrl = this.api.addFunctionUrl({
      authType: lambda.FunctionUrlAuthType.NONE,
      invokeMode: lambda.InvokeMode.RESPONSE_STREAM,
      cors: {
        allowedOrigins: ['*'],
        allowedMethods: [lambda.HttpMethod.ALL],
        allowedHeaders: ['*'],
        maxAge: Duration.days(1),
      },
    });

    // --- scheduled sweep / brief ----------------------------------------------------------
    const sweep = new lambda.Function(this, 'SweepFunction', {
      description: 'Porchlight scheduled work — hourly sweep and the nightly brief.',
      runtime: lambda.Runtime.PYTHON_3_12,
      architecture: lambda.Architecture.ARM_64,
      code,
      handler: 'api.scheduled.handler',
      memorySize: this.contextNumber('sweepMemoryMb', 1024),
      timeout: Duration.minutes(15),
      environment,
      logGroup: new logs.LogGroup(this, 'SweepLogs', {
        retention: logs.RetentionDays.TWO_WEEKS,
        removalPolicy: RemovalPolicy.DESTROY,
      }),
    });

    for (const fn of [this.api, sweep]) {
      this.grantRuntimeAccess(fn, runtimeArn, memoryId);
    }

    new scheduler.Schedule(this, 'SweepSchedule', {
      description: 'Porchlight: send due messages, escalate stale outreach, time out silent volunteers.',
      schedule: scheduler.ScheduleExpression.rate(
        Duration.minutes(this.contextNumber('sweepRateMinutes', 60)),
      ),
      target: new schedulerTargets.LambdaInvoke(sweep, {
        input: scheduler.ScheduleTargetInput.fromObject({ action: 'sweep' }),
        retryAttempts: 2,
        maxEventAge: Duration.minutes(30),
      }),
    });

    new scheduler.Schedule(this, 'BriefSchedule', {
      description: "Porchlight: the coordinator's nightly brief (06:00 UTC).",
      schedule: scheduler.ScheduleExpression.expression(
        this.contextString('briefCron', 'cron(0 6 * * ? *)'),
      ),
      target: new schedulerTargets.LambdaInvoke(sweep, {
        input: scheduler.ScheduleTargetInput.fromObject({ action: 'brief' }),
        retryAttempts: 1,
        maxEventAge: Duration.hours(1),
      }),
    });

    // --- web: S3 + CloudFront, same-origin /api/* -----------------------------------------
    const webBucket = new s3.Bucket(this, 'WebBucket', {
      encryption: s3.BucketEncryption.S3_MANAGED,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      removalPolicy: RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
    });

    this.distribution = new cloudfront.Distribution(this, 'Distribution', {
      comment: 'Porchlight — the Porch UI and its same-origin API.',
      defaultRootObject: 'index.html',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      httpVersion: cloudfront.HttpVersion.HTTP2_AND_3,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(webBucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_GET_HEAD_OPTIONS,
        cachePolicy: cloudfront.CachePolicy.CACHING_OPTIMIZED,
        compress: true,
      },
      // A single-page app: unknown paths are routes, not missing files.
      errorResponses: [
        { httpStatus: 403, responseHttpStatus: 200, responsePagePath: '/index.html', ttl: Duration.minutes(1) },
        { httpStatus: 404, responseHttpStatus: 200, responsePagePath: '/index.html', ttl: Duration.minutes(1) },
      ],
    });

    this.distribution.addBehavior(
      '/api/*',
      new origins.FunctionUrlOrigin(this.apiUrl, {
        // SSE (`/api/events`) and a slow first graph run both need the longest read CloudFront allows.
        readTimeout: Duration.seconds(60),
        keepaliveTimeout: Duration.seconds(60),
      }),
      {
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
        cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
        // Everything but Host: a Function URL origin rejects a forwarded viewer Host header.
        originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
        compress: false,
      },
    );

    if (fs.existsSync(webDist) && fs.existsSync(path.join(webDist, 'index.html'))) {
      new s3deploy.BucketDeployment(this, 'WebDeployment', {
        sources: [s3deploy.Source.asset(webDist)],
        destinationBucket: webBucket,
        distribution: this.distribution,
        distributionPaths: ['/*'],
        prune: true,
        memoryLimit: 512,
      });
    } else {
      Annotations.of(this).addWarningV2(
        'porchlight:no-web-dist',
        `web/dist not found at ${webDist}; the CloudFront bucket deploys empty. Run "make build-web" first.`,
      );
    }

    // --- outputs ---------------------------------------------------------------------------
    new CfnOutput(this, 'CloudFrontUrl', {
      value: `https://${this.distribution.distributionDomainName}`,
      description: 'The Porch — UI and same-origin API.',
    });
    new CfnOutput(this, 'FunctionUrl', {
      value: this.apiUrl.url,
      description: 'API Function URL (direct, bypassing CloudFront).',
    });
    new CfnOutput(this, 'TableName', { value: this.table.tableName, description: 'DynamoDB single table.' });
    new CfnOutput(this, 'SessionBucketName', {
      value: this.sessionBucket.bucketName,
      description: 'S3SessionManager bucket.',
    });
    new CfnOutput(this, 'WebBucketName', { value: webBucket.bucketName, description: 'Static UI bucket.' });
    new CfnOutput(this, 'ApiFunctionName', { value: this.api.functionName, description: 'API Lambda.' });
    new CfnOutput(this, 'SweepFunctionName', { value: sweep.functionName, description: 'Scheduled Lambda.' });
    new CfnOutput(this, 'DistributionId', {
      value: this.distribution.distributionId,
      description: 'CloudFront distribution id (for invalidations).',
    });
  }

  // --- helpers ------------------------------------------------------------------------------

  /** A string from CDK context, falling back to `fallback` when unset or blank. */
  private contextString(key: string, fallback: string): string {
    const value = this.node.tryGetContext(key);
    if (value === undefined || value === null) return fallback;
    const text = String(value).trim();
    return text.length > 0 ? text : fallback;
  }

  /** A number from CDK context (context values arrive as strings from `-c key=value`). */
  private contextNumber(key: string, fallback: number): number {
    const value = Number(this.contextString(key, String(fallback)));
    return Number.isFinite(value) ? value : fallback;
  }

  /** Resolve a context path relative to the CDK app directory. */
  private resolvePath(value: string): string {
    return path.isAbsolute(value) ? value : path.resolve(process.cwd(), value);
  }

  /**
   * The Lambda code asset.
   *
   * `scripts/build_lambda.sh` writes `build/lambda/`. When it has not run yet a stub asset keeps
   * `cdk synth` working — the deploy would start and fail loudly, which beats a synth that cannot
   * run at all on a machine with no build.
   */
  private bundleCode(bundleDir: string): lambda.Code {
    if (fs.existsSync(path.join(bundleDir, 'run.sh'))) {
      return lambda.Code.fromAsset(bundleDir);
    }
    Annotations.of(this).addWarningV2(
      'porchlight:no-lambda-bundle',
      `No Lambda bundle at ${bundleDir}; synthesising a stub. Run "make build-lambda" before deploying.`,
    );
    const stub = fs.mkdtempSync(path.join(os.tmpdir(), 'porchlight-stub-'));
    fs.writeFileSync(
      path.join(stub, 'run.sh'),
      '#!/bin/sh\necho "porchlight: lambda bundle was not built; run make build-lambda" >&2\nexit 1\n',
      { mode: 0o755 },
    );
    fs.writeFileSync(
      path.join(stub, 'api_stub.py'),
      '"""Placeholder: the real bundle comes from scripts/build_lambda.sh."""\n',
    );
    return lambda.Code.fromAsset(stub);
  }

  /** The `PORCHLIGHT_*` wiring both Lambdas share. */
  private lambdaEnvironment(runtimeArn: string, memoryId: string): Record<string, string> {
    const environment: Record<string, string> = {
      PORCHLIGHT_MODE: 'live',
      PORCHLIGHT_STORE: 'dynamo',
      PORCHLIGHT_DYNAMO_TABLE: this.table.tableName,
      PORCHLIGHT_SESSION_BUCKET: this.sessionBucket.bucketName,
      PORCHLIGHT_EVENTS_SOURCE: 'store',
      PORCHLIGHT_AGENT_RUNTIME_ARN: runtimeArn,
      PORCHLIGHT_MEMORY_ID: memoryId,
      PORCHLIGHT_AWS_REGION: this.region,
      PYTHONUNBUFFERED: '1',
    };
    // Live mode sends through SES; only set the sender when one was configured.
    const fromAddr = this.contextString('fromAddr', '');
    if (fromAddr) environment.PORCHLIGHT_FROM_ADDR = fromAddr;
    return environment;
  }

  /**
   * Everything a Porchlight Lambda is allowed to touch: its table, its session bucket, the
   * AgentCore runtime and memory, and Bedrock models for the in-process fallback.
   */
  private grantRuntimeAccess(fn: lambda.Function, runtimeArn: string, memoryId: string): void {
    this.table.grantReadWriteData(fn);
    this.sessionBucket.grantReadWrite(fn);

    fn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'InvokeAgentRuntime',
        actions: ['bedrock-agentcore:InvokeAgentRuntime'],
        resources: runtimeArn ? [runtimeArn, `${runtimeArn}/*`] : ['*'],
      }),
    );

    fn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'AgentCoreMemory',
        actions: [
          'bedrock-agentcore:CreateEvent',
          'bedrock-agentcore:ListEvents',
          'bedrock-agentcore:GetEvent',
          'bedrock-agentcore:RetrieveMemoryRecords',
          'bedrock-agentcore:ListMemoryRecords',
          'bedrock-agentcore:GetMemoryRecord',
          'bedrock-agentcore:GetMemory',
        ],
        resources: memoryId
          ? [
              `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:memory/${memoryId}`,
              `arn:${this.partition}:bedrock-agentcore:${this.region}:${this.account}:memory/${memoryId}/*`,
            ]
          : ['*'],
      }),
    );

    // `PORCHLIGHT_MODE=live` wires EmailChannel, which sends through SES.
    fn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'SendMail',
        actions: ['ses:SendEmail', 'ses:SendRawEmail'],
        resources: ['*'],
      }),
    );

    // The API falls back to running the Strands graph in-process when no runtime ARN is set.
    // Converse/ConverseStream authorise against InvokeModel — there is no `bedrock:Converse`
    // IAM action — so this mirrors runtime/iam-policy.json rather than inventing one.
    fn.addToRolePolicy(
      new iam.PolicyStatement({
        sid: 'InvokeBedrockModels',
        actions: [
          'bedrock:InvokeModel',
          'bedrock:InvokeModelWithResponseStream',
          'bedrock:CountTokens',
          'bedrock:GetInferenceProfile',
          'bedrock:ListInferenceProfiles',
          'bedrock:ListFoundationModels',
          'bedrock:GetFoundationModel',
        ],
        resources: ['*'],
      }),
    );
  }
}
