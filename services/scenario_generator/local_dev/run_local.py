"""
Local test runner for sentinel-scenario-generator — now wired
against the REAL DynamoDB table and S3 bucket deployed on Day 2.

This script does two things sentinel-intake and SQS will eventually
do for us:
  1. Writes a run record to DynamoDB (stands in for sentinel-intake)
  2. Builds a fake SQS event and calls the handler directly (stands
     in for the SQS trigger sentinel-dispatcher will eventually fire)

Then it reads back the DynamoDB record and the S3 object to confirm
the whole round trip actually happened for real.

Usage (from the sentinel/ repo root):
    export SENTINEL_ARTEFACTS_BUCKET=sentinel-artefacts-<account>-<region>
    python -m services.scenario_generator.local_dev.run_local
"""

import json
import os
import sys
import time
import logging
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import boto3  # noqa: E402

from services.scenario_generator.handler import lambda_handler  # noqa: E402
from shared.aws.dynamodb_client import TABLE_NAME  # noqa: E402

SAMPLE_PATH = Path(__file__).parent / "sample_run_record.json"


def main():
    logging.basicConfig(level=logging.INFO)
    if not os.environ.get("SENTINEL_ARTEFACTS_BUCKET"):
        raise SystemExit(
            "Set SENTINEL_ARTEFACTS_BUCKET to your deployed bucket name first:\n"
            "  export SENTINEL_ARTEFACTS_BUCKET=sentinel-artefacts-<account>-<region>"
        )

    with open(SAMPLE_PATH) as f:
        run_record_data = json.load(f)

    # sentinel-intake will compute this at write-time per TAD Section 6.1;
    # we do the same here since this script stands in for intake.
    run_record_data["ttl_timestamp"] = int(time.time()) + (365 * 24 * 60 * 60)

    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    table.put_item(Item=run_record_data)
    print(f"Wrote run record '{run_record_data['run_id']}' to DynamoDB table '{TABLE_NAME}'")

    # Stands in for the SQS message sentinel-dispatcher will eventually publish.
    fake_sqs_event = {
        "Records": [
            {
                "body": json.dumps(
                    {
                        "run_id": run_record_data["run_id"],
                        "team_id": run_record_data["team_id"],
                    }
                )
            }
        ]
    }

    print("Invoking lambda_handler...\n")
    lambda_handler(fake_sqs_event, None)

    # Verify what actually happened by reading it back
    updated = table.get_item(
        Key={
            "team_id": run_record_data["team_id"],
            "run_id": run_record_data["run_id"],
        }
    )["Item"]

    print(f"\nFinal DynamoDB status: {updated.get('status')}")
    print(f"test_plan_s3_key: {updated.get('test_plan_s3_key')}")

    if updated.get("test_plan_s3_key"):
        s3 = boto3.client("s3")
        obj = s3.get_object(
            Bucket=os.environ["SENTINEL_ARTEFACTS_BUCKET"],
            Key=updated["test_plan_s3_key"],
        )
        test_plan = json.loads(obj["Body"].read())
        print(f"Scenarios confirmed in S3: {len(test_plan['scenarios'])}")


if __name__ == "__main__":
    main()