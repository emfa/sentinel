"""
sentinel-storage stack — TAD Section 6 (Data Design).

Two resources:

  1. sentinel-runs DynamoDB table
     The single source of truth for every run. Streams enabled —
     this is what sentinel-dispatcher will watch (built in a later
     session) to route work between stages. TTL enabled so old runs
     purge themselves automatically after a year, at no cost.

  2. sentinel-artefacts S3 bucket
     Holds only the two large pipeline outputs: Test Plan JSON and
     Test Report CSV. The OpenAPI spec and all run metadata live in
     DynamoDB, not here — see Gap 2 from architecture review.
"""

from aws_cdk import Duration, RemovalPolicy, Stack
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_s3 as s3
from constructs import Construct


class SentinelStorageStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------
        # DynamoDB — sentinel-runs
        # ------------------------------------------------------------------
        self.runs_table = dynamodb.Table(
            self,
            "SentinelRunsTable",
            table_name="sentinel-runs",
            partition_key=dynamodb.Attribute(
                name="team_id", type=dynamodb.AttributeType.STRING
            ),
            sort_key=dynamodb.Attribute(
                name="run_id", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            time_to_live_attribute="ttl_timestamp",
            # DEV-ONLY. This means `cdk destroy` actually deletes the
            # table and all its data. Change to RemovalPolicy.RETAIN
            # before this stack ever touches staging or prod — TAD
            # Section 13.2, three-account plan.
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------
        # S3 — sentinel-artefacts-{account}-{region}
        # ------------------------------------------------------------------
        self.artefacts_bucket = s3.Bucket(
            self,
            "SentinelArtefactsBucket",
            bucket_name=f"sentinel-artefacts-{self.account}-{self.region}",
            encryption=s3.BucketEncryption.S3_MANAGED,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-run-artefacts-after-90-days",
                    prefix="runs/",
                    expiration=Duration.days(90),
                )
            ],
            # DEV-ONLY, same caveat as the table above. auto_delete_objects
            # empties the bucket before deleting it — convenient while
            # iterating, dangerous anywhere real data lives.
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )