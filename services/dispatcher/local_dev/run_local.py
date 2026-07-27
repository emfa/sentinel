"""
Local test runner for sentinel-dispatcher — hand-builds DynamoDB
Streams event records using boto3's own TypeSerializer (so the wire
format exactly matches what a real Stream would send) and calls the
handler directly against real SQS queues, real S3, and the real
sandbox-team SNS topic.

Usage (from the sentinel/ repo root, in myenv):
    export SENTINEL_STAGE2_QUEUE_URL=<from `aws sqs get-queue-url --queue-name sentinel-stage2-queue`>
    export SENTINEL_STAGE3_QUEUE_URL=<from `aws sqs get-queue-url --queue-name sentinel-stage3-queue`>
    export SENTINEL_ARTEFACTS_BUCKET=sentinel-artefacts-<account>-<region>
    python -m services.dispatcher.local_dev.run_local
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import boto3  # noqa: E402
from boto3.dynamodb.types import TypeSerializer  # noqa: E402

from services.dispatcher.handler import lambda_handler  # noqa: E402
from shared.aws.dynamodb_client import TABLE_NAME, now_iso  # noqa: E402
from shared.aws.s3_client import BUCKET_NAME  # noqa: E402

TEAM_ID = "sandbox-team"
_serializer = TypeSerializer()
_table = boto3.resource("dynamodb").Table(TABLE_NAME)
_s3 = boto3.client("s3")
_sqs = boto3.client("sqs")


def _serialize(item: dict) -> dict:
    return {k: _serializer.serialize(v) for k, v in item.items()}


def _stream_event(new_item: dict, old_item: dict = None) -> dict:
    dynamodb_data = {"NewImage": _serialize(new_item)}
    if old_item is not None:
        dynamodb_data["OldImage"] = _serialize(old_item)
    return {"Records": [{"dynamodb": dynamodb_data}]}


def _drain_and_show(queue_url: str, label: str):
    resp = _sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=2)
    messages = resp.get("Messages", [])
    if messages:
        body = json.loads(messages[0]["Body"])
        print(f"  {label}: message received -> {body}")
        _sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=messages[0]["ReceiptHandle"])
    else:
        print(f"  {label}: NO message found (unexpected if this stage should have routed)")


def main():
    stage2_url = os.environ.get("SENTINEL_STAGE2_QUEUE_URL")
    stage3_url = os.environ.get("SENTINEL_STAGE3_QUEUE_URL")
    if not stage2_url or not stage3_url or not BUCKET_NAME:
        raise SystemExit(
            "Set SENTINEL_STAGE2_QUEUE_URL, SENTINEL_STAGE3_QUEUE_URL, and "
            "SENTINEL_ARTEFACTS_BUCKET before running this script."
        )

    run_id = str(uuid.uuid4())
    timestamp = now_iso()

    # --- 1. Fresh run at INTAKE_COMPLETE -> should route to stage2 ---
    base_item = {
        "team_id": TEAM_ID,
        "run_id": run_id,
        "status": "INTAKE_COMPLETE",
        "created_at": timestamp,
        "updated_at": timestamp,
        "ttl_timestamp": int(time.time()) + (365 * 24 * 60 * 60),
        "openapi_spec": "{}",
        "auth_type": "bearer",
        "auth_header_name": "Authorization",
        "vault_secret_reference": "aws:sandbox-team/dispatcher-test/token",
        "test_env_urls": ["https://example.com"],
        "documentation": "x" * 100,
        "timeout_ms": 10000,
    }
    _table.put_item(Item=base_item)
    print(f"Run {run_id} created at INTAKE_COMPLETE")

    event = _stream_event(new_item=base_item)  # no OldImage -> simulates a fresh INSERT
    lambda_handler(event, None)
    _drain_and_show(stage2_url, "stage2 queue")

    # --- 2. Transition to SCENARIOS_READY -> should route to stage3 ---
    scenarios_ready_item = dict(base_item)
    scenarios_ready_item["status"] = "SCENARIOS_READY"
    scenarios_ready_item["test_plan_s3_key"] = f"runs/{TEAM_ID}/{run_id}/test-plan.json"
    _table.put_item(Item=scenarios_ready_item)
    print(f"\nRun {run_id} transitioned to SCENARIOS_READY")

    event = _stream_event(new_item=scenarios_ready_item, old_item=base_item)
    lambda_handler(event, None)
    _drain_and_show(stage3_url, "stage3 queue")

    # --- 3. A same-status update (e.g. just adding a field) -> should be IGNORED ---
    noop_item = dict(scenarios_ready_item)
    noop_item["stage2_completed_at"] = now_iso()
    event = _stream_event(new_item=noop_item, old_item=scenarios_ready_item)
    lambda_handler(event, None)  # should do nothing, no exception
    print("\nSame-status update processed with no action (correct)")

    # --- 4. Transition to COMPLETED -> should send a real SNS notification ---
    report_key = f"runs/{TEAM_ID}/{run_id}/test-report.csv"
    sample_csv = Path(__file__).parent / "sample_test_report.csv"
    _s3.put_object(
        Bucket=BUCKET_NAME, Key=report_key, Body=sample_csv.read_bytes(), ContentType="text/csv"
    )
    print(f"\nUploaded sample test report to s3://{BUCKET_NAME}/{report_key}")

    completed_item = dict(noop_item)
    completed_item["status"] = "COMPLETED"
    completed_item["report_s3_key"] = report_key
    _table.put_item(Item=completed_item)

    event = _stream_event(new_item=completed_item, old_item=noop_item)
    lambda_handler(event, None)
    print("COMPLETED notification sent to SNS topic sentinel-notifications-sandbox-team")
    print("(subscribe your own email to that topic in the AWS Console to see it arrive for real)")

    # --- 5. A second run, transitioned straight to FAILED ---
    failed_run_id = str(uuid.uuid4())
    failed_item = dict(base_item)
    failed_item["run_id"] = failed_run_id
    failed_item["status"] = "SCENARIOS_READY"
    _table.put_item(Item=failed_item)

    failed_final = dict(failed_item)
    failed_final["status"] = "FAILED"
    failed_final["error_detail"] = "Scenario generation failed after 3 attempts (simulated for local test)"
    _table.put_item(Item=failed_final)

    event = _stream_event(new_item=failed_final, old_item=failed_item)
    lambda_handler(event, None)
    print(f"\nFAILED notification sent for run_id={failed_run_id}")


if __name__ == "__main__":
    main()