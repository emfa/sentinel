"""
Thin wrapper around the sentinel-artefacts S3 bucket (TAD Section 6.2).
"""

import json
import os

import boto3

BUCKET_NAME = os.environ.get("SENTINEL_ARTEFACTS_BUCKET")

_s3 = boto3.client("s3")


def write_json(key: str, data: dict) -> None:
    if not BUCKET_NAME:
        raise RuntimeError(
            "SENTINEL_ARTEFACTS_BUCKET environment variable is not set"
        )
    _s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=json.dumps(data, indent=2).encode("utf-8"),
        ContentType="application/json",
    )


def test_plan_key(team_id: str, run_id: str) -> str:
    return f"runs/{team_id}/{run_id}/test-plan.json"