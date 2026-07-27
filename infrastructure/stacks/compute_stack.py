"""
sentinel-compute stack — TAD Section 4 (Service Design), 7 (Inter-
Service Communication), 10.2 (IAM).

Wires all four Lambdas to their real triggers for the first time:
  - sentinel-intake:              API Gateway
  - sentinel-dispatcher:          DynamoDB Streams (+ on-failure DLQ)
  - sentinel-scenario-generator:  SQS sentinel-stage2-queue
  - sentinel-test-runner:         SQS sentinel-stage3-queue

IAM note: permissions below reflect what each Lambda's code ACTUALLY
does today, not TAD Section 10.2's original text — that section
predates dispatcher absorbing SQS/SNS publishing and the reference-
only secrets decision, and needs a correction pass (tracked in the
TAD-corrections backlog). Each Lambda still gets its own role, no
sharing, matching TAD's least-privilege intent even where the
specific grants have moved.
"""

from aws_cdk import BundlingOptions, Duration, Stack, AssetHashType
from aws_cdk import aws_apigateway as apigw
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as _lambda
from aws_cdk import aws_lambda_event_sources as lambda_event_sources
from constructs import Construct

from lambda_packaging import BUILD_DIR

PYTHON_RUNTIME = _lambda.Runtime.PYTHON_3_12


def _bundled_code(service_name: str) -> _lambda.Code:
    """
    Bundles a pre-staged service folder (see lambda_packaging.py —
    already has shared/ merged in) using the SAM build image matching
    our Lambda runtime. This is what makes compiled dependencies (e.g.
    pydantic-core, a Rust extension used by scenario-generator) build
    correctly for Lambda's actual Linux/x86_64 environment instead of
    whatever OS/architecture the developer's own machine happens to
    be — a real problem if skipped, not a theoretical one. 
    
    platform="linux/arm64" is explicit on purpose, not left to
    whatever Docker defaults to on the host machine. On Day 6 this bit
    us for real: an Apple Silicon Mac's Docker defaulted to building
    ARM64 wheels, while every Lambda function below defaulted to
    x86_64 (CDK's own default when architecture isn't specified) —
    pydantic-core's compiled extension silently mismatched, producing
    "No module named 'pydantic_core._pydantic_core'" at import time.
    PyYAML's C extension has a pure-Python fallback so it didn't fail
    the same way; pydantic has no such fallback. Fix: pin the build
    platform here AND set architecture=ARM_64 on every Function below,
    so the two can never drift apart regardless of which machine
    happens to run `cdk deploy`. REQUIRES Docker running locally at synth/deploy time.
    """
    staged_path = str(BUILD_DIR / service_name)
    return _lambda.Code.from_asset(
        staged_path,
        asset_hash_type=AssetHashType.OUTPUT,
        bundling=BundlingOptions(
            image=PYTHON_RUNTIME.bundling_image,
            platform='linux/arm64',
            command=[
                "bash", "-c",
                "pip install -r requirements.txt -t /asset-output "
                "&& cp -au . /asset-output",
            ],
        ),
    )


class SentinelComputeStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        runs_table,
        artefacts_bucket,
        stage2_queue,
        stage3_queue,
        dispatcher_dlq,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        common_env = {
            "SENTINEL_RUNS_TABLE": runs_table.table_name,
            "SENTINEL_ARTEFACTS_BUCKET": artefacts_bucket.bucket_name,
        }

        # ------------------------------------------------------------------
        # sentinel-intake — HTTP entry point via API Gateway
        # ------------------------------------------------------------------
        self.intake_fn = _lambda.Function(
            self,
            "SentinelIntakeFunction",
            function_name="sentinel-intake",
            runtime=PYTHON_RUNTIME,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=_bundled_code("intake"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment=common_env,
        )
        # Needs read (rerun's get_run_record, GET status) and write
        # (put_run_record for both new runs and re-runs).
        runs_table.grant_read_write_data(self.intake_fn)
        # Needs read only — for generating presigned report URLs on
        # the GET status endpoint (Day 6 addition). Not in TAD's
        # original IAM scoping for intake since that endpoint wasn't
        # implemented when Section 10.2 was written.
        artefacts_bucket.grant_read(self.intake_fn)

        # ------------------------------------------------------------------
        # sentinel-scenario-generator — triggered by stage2 queue
        # ------------------------------------------------------------------
        self.scenario_generator_fn = _lambda.Function(
            self,
            "SentinelScenarioGeneratorFunction",
            function_name="sentinel-scenario-generator",
            runtime=PYTHON_RUNTIME,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=_bundled_code("scenario_generator"),
            timeout=Duration.minutes(12),  # TAD Section 4.2
            memory_size=1024,  # TAD Section 4.2
            environment=common_env,
        )
        runs_table.grant_read_write_data(self.scenario_generator_fn)
        artefacts_bucket.grant_write(self.scenario_generator_fn)  # writes test-plan.json only, never reads
        self.scenario_generator_fn.add_event_source(
            lambda_event_sources.SqsEventSource(stage2_queue, batch_size=1)
        )
        
        # Bedrock permission is broad on purpose for now — the model
        # choice itself is still an open decision (Nova 2 Lite vs.
        # Claude Sonnet, Day 1 tech debt, unresolved as of Day 6).
        # Scope this down to a specific model ARN once that's settled.
        #
        # Two resource types granted, not one: "global." cross-region
        # models (like the Nova 2 Lite variant currently hardcoded in
        # client.py) are invoked through an inference-profile ARN, not
        # a foundation-model ARN — a real gap caught when the first
        # live invocation hit AccessDeniedException against a resource
        # type our original policy never covered at all.
        self.scenario_generator_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel"],
                resources=[
                    "arn:aws:bedrock:*::foundation-model/*",
                    f"arn:aws:bedrock:*:{self.account}:inference-profile/*",
                ],
            )
        )

        # ------------------------------------------------------------------
        # sentinel-test-runner — triggered by stage3 queue
        # ------------------------------------------------------------------
        self.test_runner_fn = _lambda.Function(
            self,
            "SentinelTestRunnerFunction",
            function_name="sentinel-test-runner",
            runtime=PYTHON_RUNTIME,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=_bundled_code("test_runner"),
            # 10 minutes — generous for a test plan with several
            # slow/timing-out scenarios (each up to 60s worst-case: 30s
            # timeout x the one retry), while staying well under
            # Lambda's 15-minute ceiling. See the matching stage3 queue
            # visibility timeout fix in messaging_stack.py (Day 6).
            timeout=Duration.minutes(10),
            memory_size=512,
            environment=common_env,
        )
        runs_table.grant_read_write_data(self.test_runner_fn)
        artefacts_bucket.grant_read_write(self.test_runner_fn)  # reads test-plan.json, writes test-report.csv
        self.test_runner_fn.add_event_source(
            lambda_event_sources.SqsEventSource(stage3_queue, batch_size=1)
        )
        # Broad on purpose: teams name their own secrets, so there's no
        # fixed naming convention to scope this to yet. TODO backlog
        # item (Day 5): enforce a naming convention (e.g. sentinel/*)
        # once there's more than one real team's secret in the account,
        # then narrow this to match.
        self.test_runner_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["secretsmanager:GetSecretValue"],
                resources=["*"],
            )
        )

        # ------------------------------------------------------------------
        # sentinel-dispatcher — triggered by DynamoDB Streams
        # ------------------------------------------------------------------
        self.dispatcher_fn = _lambda.Function(
            self,
            "SentinelDispatcherFunction",
            function_name="sentinel-dispatcher",
            runtime=PYTHON_RUNTIME,
            architecture=_lambda.Architecture.ARM_64,
            handler="handler.lambda_handler",
            code=_bundled_code("dispatcher"),
            timeout=Duration.seconds(30),
            memory_size=256,
            environment={
                **common_env,
                "SENTINEL_STAGE2_QUEUE_URL": stage2_queue.queue_url,
                "SENTINEL_STAGE3_QUEUE_URL": stage3_queue.queue_url,
            },
        )
        stage2_queue.grant_send_messages(self.dispatcher_fn)
        stage3_queue.grant_send_messages(self.dispatcher_fn)
        artefacts_bucket.grant_read(self.dispatcher_fn)  # reads the CSV for pass/fail counts
        # SNS topic ARNs are constructed at runtime, not looked up
        # (shared/aws/sns_client.py) — one topic per team, created at
        # onboarding, so we can't grant against specific topic ARNs
        # for teams that don't exist yet. Scoped by naming convention
        # instead of a wildcard-everything policy.
        self.dispatcher_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sns:Publish"],
                resources=[
                    f"arn:aws:sns:{self.region}:{self.account}:sentinel-notifications-*"
                ],
            )
        )
        # STS GetCallerIdentity doesn't support resource-level scoping —
        # this is the one genuinely unavoidable "*" in this stack.
        self.dispatcher_fn.add_to_role_policy(
            iam.PolicyStatement(
                actions=["sts:GetCallerIdentity"],
                resources=["*"],
            )
        )
        # add_event_source's DynamoEventSource handles the required
        # dynamodb:DescribeStream/GetRecords/GetShardIterator grants
        # automatically — no separate grant_stream_read() call needed.
        self.dispatcher_fn.add_event_source(
            lambda_event_sources.DynamoEventSource(
                runs_table,
                starting_position=_lambda.StartingPosition.LATEST,
                batch_size=1,
                retry_attempts=3,
                on_failure=lambda_event_sources.SqsDlq(dispatcher_dlq),
            )
        )

        # ------------------------------------------------------------------
        # API Gateway — the only Lambda with an HTTP trigger
        # ------------------------------------------------------------------
        api = apigw.RestApi(
            self,
            "SentinelApi",
            rest_api_name="sentinel-api",
            deploy_options=apigw.StageOptions(stage_name="v1"),
        )

        intake_integration = apigw.LambdaIntegration(self.intake_fn)

        runs_resource = api.root.add_resource("runs")
        runs_resource.add_method("POST", intake_integration)  # POST /runs

        run_id_resource = runs_resource.add_resource("{run_id}")
        run_id_resource.add_method("GET", intake_integration)  # GET /runs/{run_id}

        rerun_resource = run_id_resource.add_resource("rerun")
        rerun_resource.add_method("POST", intake_integration)  # POST /runs/{run_id}/rerun

        self.api_url = api.url