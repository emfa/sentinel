"""
Thin wrapper around the sentinel-runs DynamoDB table (TAD Section 6.1).

Deliberately dumb: no business logic lives here — no idempotency
decisions, no status-transition rules. This module only knows how to
get an item by key and update one. Every Lambda that touches
DynamoDB (scenario-generator today, test-runner and intake later)
imports this instead of writing its own boto3 calls.
"""

import os
from datetime import datetime, timezone
from typing import Optional

import boto3

TABLE_NAME = os.environ.get("SENTINEL_RUNS_TABLE", "sentinel-runs")

_dynamodb = boto3.resource("dynamodb")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _table():
    return _dynamodb.Table(TABLE_NAME)


def get_run_record(team_id: str, run_id: str) -> Optional[dict]:
    """Fetch a run record by primary key. Returns None if not found."""
    response = _table().get_item(Key={"team_id": team_id, "run_id": run_id})
    return response.get("Item")

def put_run_record(item: dict) -> None:
    """
    Writes a full run record — an unconditional put, not a partial
    update. Used by sentinel-intake for both new submissions and
    re-runs (TAD Section 4.1). Every other Lambda uses
    update_run_status instead, since they're only ever patching a
    record intake already created.
    """
    _table().put_item(Item=item)

def update_run_status(team_id: str, run_id: str, status: str, **extra_attributes) -> None:
    """
    Updates status and any extra attributes (e.g. test_plan_s3_key,
    stage2_completed_at, error_detail). Always stamps updated_at.

    "status" is a DynamoDB reserved word, hence the
    ExpressionAttributeNames alias below — this is a common gotcha
    that produces a confusing ValidationException if you forget it.
    """
    update_expr_parts = ["#status = :status", "updated_at = :updated_at"]
    expr_attr_names = {"#status": "status"}
    expr_attr_values = {
        ":status": status,
        ":updated_at": now_iso(),
    }

    for key, value in extra_attributes.items():
        placeholder = f":{key}"
        update_expr_parts.append(f"{key} = {placeholder}")
        expr_attr_values[placeholder] = value

    _table().update_item(
        Key={"team_id": team_id, "run_id": run_id},
        UpdateExpression="SET " + ", ".join(update_expr_parts),
        ExpressionAttributeNames=expr_attr_names,
        ExpressionAttributeValues=expr_attr_values,
    )