"""
sentinel-intake Lambda handler.

Trigger: API Gateway (proxy integration)
Routes (TAD Section 4.1):
  POST /runs                 — new submission
  POST /runs/{run_id}/rerun  — re-run

Design principle: exactly ONE external write (DynamoDB) before
returning a response. All downstream routing is sentinel-dispatcher's
job via DynamoDB Streams — intake never touches SQS directly.

Status note: re-runs are written with status=INTAKE_COMPLETE, not
RERUN_IN_PROGRESS. TAD Section 6.3 lists RERUN_IN_PROGRESS as a
distinct status, but TAD Section 4.1's own re-run pseudocode says to
set INTAKE_COMPLETE — and sentinel-dispatcher's routing logic (TAD
Section 4.2) only has a branch for INTAKE_COMPLETE. Using
INTAKE_COMPLETE is what actually makes the flattened re-run design
work with zero special-casing in the dispatcher, matching the
original intent from architecture review. TAD Section 6.3 needs a
correction to remove the RERUN_IN_PROGRESS row.
"""

import json
import logging
import time
import uuid

from services.intake.validation import validate_submission
from shared.aws.dynamodb_client import get_run_record, now_iso, put_run_record

logger = logging.getLogger()
logger.setLevel(logging.INFO)

RUN_TTL_SECONDS = 365 * 24 * 60 * 60  # 1 year — TAD Section 6.1

# Fields that only make sense once a run has progressed past intake.
# A fresh re-run hasn't reached those stages yet, so we strip them
# rather than carry stale values forward from the original run.
STAGE_PROGRESS_FIELDS = (
    "test_plan_s3_key",
    "report_s3_key",
    "stage2_completed_at",
    "stage3_completed_at",
    "error_detail",
)


def lambda_handler(event, context):
    method = event.get("httpMethod", "")
    path_params = event.get("pathParameters") or {}

    if method == "POST" and path_params.get("run_id"):
        return _handle_rerun(event, path_params["run_id"])

    if method == "POST":
        return _handle_new_run(event)

    return _response(404, {"error": "NOT_FOUND"})


def _handle_new_run(event):
    team_id = _get_header(event, "X-Team-ID")
    if not team_id:
        return _response(
            400, {"error": "MISSING_TEAM_ID", "message": "X-Team-ID header is required"}
        )

    body, parse_error = _parse_body(event)
    if parse_error:
        return parse_error

    errors = validate_submission(body)
    if errors:
        return _response(
            400,
            {
                "error": "VALIDATION_FAILED",
                "field_errors": errors,
                "message": "Submission rejected. Resolve all validation errors and resubmit.",
            },
        )

    run_id = str(uuid.uuid4())
    timestamp = now_iso()
    auth = body["auth"]

    item = {
        "team_id": team_id,
        "run_id": run_id,
        "status": "INTAKE_COMPLETE",
        "created_at": timestamp,
        "updated_at": timestamp,
        "ttl_timestamp": int(time.time()) + RUN_TTL_SECONDS,
        "openapi_spec": body["openapi_spec"],
        "auth_type": auth.get("type", ""),
        "auth_header_name": auth.get("header_name", ""),
        "vault_secret_reference": auth["vault_secret_reference"],
        "test_env_urls": body["test_env_urls"],
        "documentation": body["documentation"],
        "timeout_ms": body.get("timeout_ms", 10_000),
    }

    put_run_record(item)
    logger.info("Created run_id=%s for team_id=%s", run_id, team_id)

    return _response(
        202,
        {"run_id": run_id, "status": "INTAKE_COMPLETE", "status_url": f"/runs/{run_id}"},
    )


def _handle_rerun(event, referenced_run_id):
    team_id = _get_header(event, "X-Team-ID")
    if not team_id:
        return _response(
            400, {"error": "MISSING_TEAM_ID", "message": "X-Team-ID header is required"}
        )

    original = get_run_record(team_id, referenced_run_id)
    if original is None:
        return _response(
            404,
            {
                "error": "RUN_NOT_FOUND",
                "message": f"No run found for run_id={referenced_run_id}",
            },
        )

    body, parse_error = _parse_body(event)
    if parse_error:
        return parse_error

    # Flattened parent chain (TAD Section 4.1, architecture review Gap 3).
    # If the referenced run is already a child, reuse ITS parent_run_id
    # so re-runs of re-runs never nest more than one level deep.
    resolved_parent_id = original.get("parent_run_id") or referenced_run_id

    new_run_id = str(uuid.uuid4())
    timestamp = now_iso()

    new_item = dict(original)  # copy every field from the original run
    new_item["run_id"] = new_run_id
    new_item["parent_run_id"] = resolved_parent_id
    new_item["status"] = "INTAKE_COMPLETE"
    new_item["created_at"] = timestamp
    new_item["updated_at"] = timestamp
    new_item["ttl_timestamp"] = int(time.time()) + RUN_TTL_SECONDS

    context_note = body.get("context_note")
    if context_note:
        new_item["context_note"] = context_note
    else:
        new_item.pop("context_note", None)

    for field in STAGE_PROGRESS_FIELDS:
        new_item.pop(field, None)

    put_run_record(new_item)
    logger.info(
        "Created rerun_id=%s (parent_run_id=%s) from run_id=%s",
        new_run_id, resolved_parent_id, referenced_run_id,
    )

    return _response(
        202,
        {
            "rerun_id": new_run_id,
            "parent_run_id": resolved_parent_id,
            "status": "INTAKE_COMPLETE",
            "status_url": f"/runs/{new_run_id}",
        },
    )


def _parse_body(event):
    """Returns (body_dict, None) on success, or (None, error_response) on failure."""
    try:
        return json.loads(event.get("body") or "{}"), None
    except json.JSONDecodeError:
        return None, _response(
            400, {"error": "INVALID_JSON", "message": "Request body is not valid JSON"}
        )


def _get_header(event, name):
    headers = event.get("headers") or {}
    lowered = {k.lower(): v for k, v in headers.items()}
    return lowered.get(name.lower())


def _response(status_code, body_dict):
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body_dict),
    }