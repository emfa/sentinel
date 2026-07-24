"""
sentinel-messaging stack — TAD Section 7.1 (Inter-Service Communication).

Two work queues, each with its own dead-letter queue:
  - sentinel-stage2-queue -> triggers sentinel-scenario-generator
  - sentinel-stage3-queue -> triggers sentinel-test-runner

Plus one more queue that isn't a "work queue" in the same sense:
  - sentinel-dispatcher-dlq -> the on-failure destination for
    sentinel-dispatcher's DynamoDB Streams event source mapping
    (TAD Section 4.2). Nothing pulls messages from this queue
    automatically — it exists purely so a CloudWatch alarm has
    something concrete to watch, and so the platform team has
    something to inspect when a run gets stuck.

CloudWatch alarms on these DLQs are NOT built here — TAD Section 14.1
puts alarms in a separate SentinelObservabilityStack, so alarm wiring
doesn't get tangled up with resource creation.
"""

from aws_cdk import Duration, Stack
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_sns as sns
from constructs import Construct


class SentinelMessagingStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 14-day retention on every DLQ below is a judgment call, not
        # something TAD Section 7.1 mandates explicitly — it's meant to
        # give the platform team a comfortable window to notice and
        # investigate a stuck message before it's gone for good.

        # ------------------------------------------------------------------
        # Stage 2 — triggers sentinel-scenario-generator
        # ------------------------------------------------------------------
        self.stage2_dlq = sqs.Queue(
            self,
            "SentinelStage2Dlq",
            queue_name="sentinel-stage2-dlq",
            retention_period=Duration.days(14),
        )

        self.stage2_queue = sqs.Queue(
            self,
            "SentinelStage2Queue",
            queue_name="sentinel-stage2-queue",
            # 13 minutes — slightly above scenario-generator's 12-minute
            # Lambda timeout (TAD Section 4.2), so the message doesn't
            # become visible to another consumer while the Lambda is
            # still legitimately working on it.
            visibility_timeout=Duration.minutes(13),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.stage2_dlq,
            ),
        )

        # ------------------------------------------------------------------
        # Stage 3 — triggers sentinel-test-runner
        # ------------------------------------------------------------------
        self.stage3_dlq = sqs.Queue(
            self,
            "SentinelStage3Dlq",
            queue_name="sentinel-stage3-dlq",
            retention_period=Duration.days(14),
        )

        self.stage3_queue = sqs.Queue(
            self,
            "SentinelStage3Queue",
            queue_name="sentinel-stage3-queue",
            visibility_timeout=Duration.minutes(5),
            dead_letter_queue=sqs.DeadLetterQueue(
                max_receive_count=3,
                queue=self.stage3_dlq,
            ),
        )

        # ------------------------------------------------------------------
        # Dispatcher on-failure destination — TAD Section 4.2
        # ------------------------------------------------------------------
        # Configured on the DynamoDB Streams event source mapping itself
        # when we build the compute stack — not consumed by any Lambda.
        self.dispatcher_dlq = sqs.Queue(
            self,
            "SentinelDispatcherDlq",
            queue_name="sentinel-dispatcher-dlq",
            retention_period=Duration.days(14),
        )

        # ------------------------------------------------------------------
        # Notification topic — sandbox stand-in for team onboarding
        # ------------------------------------------------------------------
        self.sandbox_team_topic = sns.Topic(
            self,
            "SentinelSandboxTeamNotifications",
            topic_name="sentinel-notifications-sandbox-team",
        )