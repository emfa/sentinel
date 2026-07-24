"""
Local test runner for sentinel-test-runner — tests against REAL
infrastructure: real DynamoDB, real S3, a real AWS Secrets Manager
secret, and real network calls to httpbin.org.

Before running, create a dummy secret once (only needs to happen once
ever, not per-run):
    aws secretsmanager create-secret \\
        --name sentinel-test-runner-sandbox-token \\
        --secret-string "dummy-test-token-abc123"

Usage (from the sentinel/ repo root, in myenv):
    export SENTINEL_ARTEFACTS_BUCKET=sentinel-artefacts-<account>-<region>
    python -m services.test_runner.local_dev.run_local
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import boto3  # noqa: E402

from services.test_runner.handler import lambda_handler  # noqa: E402
from shared.aws.dynamodb_client import TABLE_NAME, now_iso  # noqa: E402
from shared.aws.s3_client import BUCKET_NAME, test_plan_key  # noqa: E402

TEAM_ID = "sandbox-team"
SECRET_REFERENCE = "aws:sentinel-test-runner-sandbox-token"

SAMPLE_TEST_PLAN_PATH = Path(__file__).parent / "sample_test_plan.json"


def main():
    if not BUCKET_NAME:
        raise SystemExit(
            "Set SENTINEL_ARTEFACTS_BUCKET before running this script:\n"
            "  export SENTINEL_ARTEFACTS_BUCKET=sentinel-artefacts-<account>-<region>"
        )

    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    s3 = boto3.client("s3")

    run_id = str(uuid.uuid4())
    test_plan_s3_key = test_plan_key(TEAM_ID, run_id)

    with open(SAMPLE_TEST_PLAN_PATH) as f:
        test_plan = json.load(f)
    test_plan["run_id"] = run_id

    s3.put_object(
        Bucket=BUCKET_NAME,
        Key=test_plan_s3_key,
        Body=json.dumps(test_plan, indent=2).encode("utf-8"),
        ContentType="application/json",
    )
    print(f"Uploaded test plan to s3://{BUCKET_NAME}/{test_plan_s3_key}")

    timestamp = now_iso()
    item = {
        "team_id": TEAM_ID,
        "run_id": run_id,
        "status": "SCENARIOS_READY",
        "created_at": timestamp,
        "updated_at": timestamp,
        "ttl_timestamp": int(time.time()) + (365 * 24 * 60 * 60),
        "openapi_spec": "{}",
        "auth_type": "bearer",
        "auth_header_name": "Authorization",
        "vault_secret_reference": SECRET_REFERENCE,
        "test_env_urls": ["https://httpbin.org"],
        "documentation": "x" * 100,
        "timeout_ms": 1000,  # deliberately short — TC-006 is designed to time out against this
        "test_plan_s3_key": test_plan_s3_key,
    }
    table.put_item(Item=item)
    print(f"Run {run_id} created at SCENARIOS_READY, timeout_ms={item['timeout_ms']}")

    fake_sqs_event = {
        "Records": [{"body": json.dumps({"run_id": run_id, "team_id": TEAM_ID})}]
    }

    print("\nInvoking lambda_handler — this will make real HTTP calls to httpbin.org...\n")
    lambda_handler(fake_sqs_event, None)

    updated = table.get_item(Key={"team_id": TEAM_ID, "run_id": run_id})["Item"]
    print(f"Final status: {updated.get('status')}")

    if updated.get("status") == "FAILED":
        print(f"error_detail: {updated.get('error_detail')}")
        return

    report_key = updated["report_s3_key"]
    report_obj = s3.get_object(Bucket=BUCKET_NAME, Key=report_key)
    report_csv = report_obj["Body"].read().decode("utf-8")

    print(f"\nReport downloaded from s3://{BUCKET_NAME}/{report_key}\n")

    import csv
    import io

    reader = csv.DictReader(io.StringIO(report_csv))
    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
    for row in reader:
        counts[row["Result"]] = counts.get(row["Result"], 0) + 1
        print(
            f"  [{row['Result']:5s}] {row['Scenario ID']} - {row['Scenario Name']} "
            f"(expected {row['Expected Status']}, got {row['Actual Status'] or 'n/a'}, "
            f"{row['Response Time (ms)']}ms)"
        )

    print(f"\nTotals: {counts['PASS']} passed, {counts['FAIL']} failed, {counts['ERROR']} errored")


if __name__ == "__main__":
    main()