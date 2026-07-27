"""
sentinel-dispatcher Lambda handler.

Trigger: DynamoDB Streams on the sentinel-runs table
(NEW_AND_OLD_IMAGES view type) — TAD Section 4.2.

The sole routing component in the pipeline. Watches EVERY write to
the table and acts only when status actually transitions to a value
it cares about. All other writes (S3 key updates, timestamp bumps,
error_detail writes) are deliberately ignored. This means no other
Lambda ever publishes to SQS or SNS directly — intake,
scenario-generator, and test-runner stay completely unaware of what
happens after they finish their own work.

Failure handling note: retries on a failing dispatcher invocation and
the on-failure DLQ destination are both configured at the CDK/event
source mapping level (TAD Section 4.2), not in this file — there's no
code-level retry logic here on purpose.
"""

import json
import logging
import os

import boto3
from boto3.dynamodb.types import TypeDeserializer

from shared.aws.s3_client import generate_presigned_url, read_csv_result_counts
from shared.aws.sns_client import publish as sns_publish

logger = logging.getLogger()
logger.setLevel(logging.INFO)

_sqs = boto3.client("sqs")
_deserializer = TypeDeserializer()

STAGE2_QUEUE_URL = os.environ.get("SENTINEL_STAGE2_QUEUE_URL")
STAGE3_QUEUE_URL = os.environ.get("SENTINEL_STAGE3_QUEUE_URL")

REPORT_URL_EXPIRY_SECONDS = 7 * 24 * 60 * 60  # 7 days — TAD Section 4.4


def lambda_handler(event, context):
    for record in event.get("Records", []):
        _handle_stream_record(record)
    return {"statusCode": 200}


def _handle_stream_record(record: dict):
    dynamodb_data = record.get("dynamodb", {})
    new_image_raw = dynamodb_data.get("NewImage")
    if not new_image_raw:
        return  # e.g. a REMOVE event — nothing to route on

    new_image = _deserialize(new_image_raw)

    old_image_raw = dynamodb_data.get("OldImage")
    old_status = _deserialize(old_image_raw).get("status") if old_image_raw else None
    new_status = new_image.get("status")

    if old_status == new_status:
        return  # not a status transition — ignore

    run_id = new_image["run_id"]
    team_id = new_image["team_id"]

    if new_status == "INTAKE_COMPLETE":
        _publish_to_queue(STAGE2_QUEUE_URL, run_id, team_id)
        logger.info("run_id=%s -> stage2 queue (scenario generation)", run_id)

    elif new_status == "SCENARIOS_READY":
        _publish_to_queue(STAGE3_QUEUE_URL, run_id, team_id)
        logger.info("run_id=%s -> stage3 queue (test execution)", run_id)

    elif new_status in ("COMPLETED", "FAILED"):
        _send_notification(new_status, run_id, team_id, new_image)
        logger.info("run_id=%s -> notification sent (status=%s)", run_id, new_status)

    # Any other status value: ignored on purpose. This includes the
    # first write of a brand-new item (old_status is None, new_status
    # might be anything) as well as every non-terminal intermediate
    # update that isn't one of the three values above.


def _publish_to_queue(queue_url: str, run_id: str, team_id: str):
    if not queue_url:
        raise RuntimeError(
            "Queue URL environment variable is not set — check "
            "SENTINEL_STAGE2_QUEUE_URL / SENTINEL_STAGE3_QUEUE_URL"
        )
    _sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=json.dumps({"run_id": run_id, "team_id": team_id}),
    )


def _send_notification(status: str, run_id: str, team_id: str, new_image: dict):
    if status == "COMPLETED":
        report_key = new_image.get("report_s3_key")
        counts = read_csv_result_counts(report_key) if report_key else {}
        url = (
            generate_presigned_url(report_key, REPORT_URL_EXPIRY_SECONDS)
            if report_key
            else None
        )
        subject = f"Sentinel run {run_id[:8]} completed"
        message = (
            f"Run ID: {run_id}\n"
            f"Status: COMPLETED\n"
            f"Results: {counts.get('PASS', 0)} passed, "
            f"{counts.get('FAIL', 0)} failed, {counts.get('ERROR', 0)} errored\n"
            f"Download report (link expires in 7 days): {url}\n"
        )
    else:
        error_detail = new_image.get("error_detail", "No details available")
        subject = f"Sentinel run {run_id[:8]} failed"
        message = f"Run ID: {run_id}\nStatus: FAILED\nReason: {error_detail}\n"

    sns_publish(team_id, subject, message)


def _deserialize(dynamodb_image: dict) -> dict:
    """
    DynamoDB Stream records use the wire format {"S": "value"},
    {"N": "123"}, {"L": [...]} etc, not plain Python types. boto3's
    own TypeDeserializer handles every attribute type correctly —
    hand-rolling this for a run record with strings, numbers, and a
    list (test_env_urls) is exactly the kind of thing worth using the
    library for instead of reinventing.
    """
    return {k: _deserializer.deserialize(v) for k, v in dynamodb_image.items()}