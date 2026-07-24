"""
Thin wrapper around the sentinel-artefacts S3 bucket (TAD Section 6.2).
"""

import json
import os

import boto3
import csv
import io   

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

def generate_presigned_url(key: str, expires_in_seconds: int) -> str:
    """
    TAD Section 4.4 — 7-day expiry for report download links. Presigned
    URLs need no auth on the recipient's end, which is exactly what an
    email link needs to be useful.
    """
    if not BUCKET_NAME:
        raise RuntimeError(
            "SENTINEL_ARTEFACTS_BUCKET environment variable is not set"
        )
    return _s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": BUCKET_NAME, "Key": key},
        ExpiresIn=expires_in_seconds,
    )


def read_csv_result_counts(key: str) -> dict:
    """
    Reads a Test Report CSV (TAD Section 8 column format) and counts
    rows by the Result column. Used by sentinel-dispatcher to put
    pass/fail counts in the completion email without the recipient
    having to open the CSV first.
    """
    if not BUCKET_NAME:
        raise RuntimeError(
            "SENTINEL_ARTEFACTS_BUCKET environment variable is not set"
        )
    obj = _s3.get_object(Bucket=BUCKET_NAME, Key=key)
    content = obj["Body"].read().decode("utf-8")

    counts = {"PASS": 0, "FAIL": 0, "ERROR": 0}
    reader = csv.DictReader(io.StringIO(content))
    for row in reader:
        result = (row.get("Result") or "").strip().upper()
        if result in counts:
            counts[result] += 1

    return counts

def test_report_key(team_id: str, run_id: str) -> str:
    return f"runs/{team_id}/{run_id}/test-report.csv"


def read_json(key: str) -> dict:
    if not BUCKET_NAME:
        raise RuntimeError(
            "SENTINEL_ARTEFACTS_BUCKET environment variable is not set"
        )
    obj = _s3.get_object(Bucket=BUCKET_NAME, Key=key)
    return json.loads(obj["Body"].read().decode("utf-8"))


def write_csv(key: str, headers: list, rows: list) -> None:
    """
    Writes the Test Report CSV (TAD Section 8). Rows are dicts keyed
    by the same header names — sentinel-test-runner is responsible
    for redacting any credential values before they ever reach this
    function.
    """
    if not BUCKET_NAME:
        raise RuntimeError(
            "SENTINEL_ARTEFACTS_BUCKET environment variable is not set"
        )
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=headers)
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    _s3.put_object(
        Bucket=BUCKET_NAME,
        Key=key,
        Body=buffer.getvalue().encode("utf-8"),
        ContentType="text/csv",
    )    