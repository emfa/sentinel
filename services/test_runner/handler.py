"""
sentinel-test-runner Lambda handler.

Trigger: SQS (sentinel-stage3-queue) — TAD Section 4.4
Message format: {"run_id": "...", "team_id": "..."} — TAD Section 7.1

Reads the Test Plan from S3, fetches the real credential ONCE via the
cloud-agnostic secrets router, executes every scenario through the
HTTP Tool, writes the Test Report CSV (credentials redacted), and
updates DynamoDB status to COMPLETED or FAILED.
"""

import json
import logging

from services.test_runner.http_tool import execute_scenario
from shared.aws.dynamodb_client import get_run_record, now_iso, update_run_status
from shared.aws.s3_client import read_json, test_report_key, write_csv
from shared.secrets.router import fetch_secret
from shared.models.run_record import RunRecord

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# TAD Section 4.4 — idempotency check. Unlike scenario-generator,
# SCENARIOS_READY is what TRIGGERS this Lambda, not a completed state
# for it, so it's not in this set.
ALREADY_PROCESSED_STATUSES = {"COMPLETED", "FAILED"}

REDACTED = "***REDACTED***"

CSV_HEADERS = [
    "Run ID", "Scenario ID", "Scenario Name", "Description", "HTTP Method",
    "Endpoint", "Request Headers", "Request Body", "Expected Status",
    "Actual Status", "Expected Behaviour", "Actual Response", "Result",
    "Failure Reason", "Response Time (ms)",
]


def lambda_handler(event, context):
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        _process_one_run(body)
    return {"statusCode": 200}

def _process_one_run(body: dict):
    run_id = body["run_id"]
    team_id = body["team_id"]
    logger.info("Processing run_id=%s team_id=%s", run_id, team_id)

    item = get_run_record(team_id, run_id)
    if item is None:
        logger.error(
            "No run record found for run_id=%s team_id=%s — dropping message",
            run_id, team_id,
        )
        return

    if item.get("status") in ALREADY_PROCESSED_STATUSES:
        logger.info(
            "run_id=%s already at status=%s — skipping (idempotency check)",
            run_id, item.get("status"),
        )
        return

    # Build a RunRecord rather than reading the raw dict directly. This
    # is not just for consistency with scenario-generator — it's a real
    # bug fix. boto3's DynamoDB resource returns every number as
    # decimal.Decimal, not int. timeout_ms read straight off the raw
    # item stays a Decimal all the way down to socket.settimeout(),
    # which rejects anything that isn't int/float. RunRecord's Pydantic
    # validation coerces Decimal -> int automatically (confirmed on Day
    # 3), so this is the correct fix, not a workaround.
    try:
        run_record = RunRecord(**item)
    except Exception as e:
        _fail(team_id, run_id, f"Run record failed validation: {e}")
        return

    if not run_record.test_plan_s3_key:
        _fail(team_id, run_id, "Run record has no test_plan_s3_key")
        return

    try:
        test_plan = read_json(run_record.test_plan_s3_key)
    except Exception as e:
        _fail(team_id, run_id, f"Could not read test plan from S3: {e}")
        return

    # Fetched ONCE per invocation, held in memory only — never written
    # to S3, DynamoDB, or logs (TAD Section 10.1 credential handling).
    try:
        secret_value = fetch_secret(run_record.vault_secret_reference)
    except Exception as e:
        _fail(team_id, run_id, f"Could not fetch credential: {e}")
        return

    rows = [
        _run_one_scenario(
            scenario, run_id,
            run_record.auth_header_name, run_record.auth_type,
            secret_value, run_record.timeout_ms,
        )
        for scenario in test_plan["scenarios"]
    ]

    report_key = test_report_key(team_id, run_id)
    write_csv(report_key, CSV_HEADERS, rows)

    update_run_status(
        team_id,
        run_id,
        status="COMPLETED",
        report_s3_key=report_key,
        stage3_completed_at=now_iso(),
    )

    logger.info(
        "run_id=%s completed: %d scenarios executed, report at %s",
        run_id, len(rows), report_key,
    )


def _run_one_scenario(scenario, run_id, auth_header_name, auth_type, secret_value, timeout_ms):
    headers = dict(scenario.get("additional_headers", {}))
    headers.update(_build_auth_header(
        scenario.get("auth_mode", "valid"), auth_header_name, auth_type, secret_value
    ))

    result = execute_scenario(
        method=scenario["http_method"],
        url=scenario["endpoint"],
        headers=headers,
        body=scenario.get("request_body"),
        timeout_ms=timeout_ms,
    )

    outcome, failure_reason = _evaluate(scenario, result)

    redacted_headers = dict(headers)
    if auth_header_name in redacted_headers:
        redacted_headers[auth_header_name] = REDACTED

    return {
        "Run ID": run_id,
        "Scenario ID": scenario["scenario_id"],
        "Scenario Name": scenario["scenario_name"],
        "Description": scenario["description"],
        "HTTP Method": scenario["http_method"],
        "Endpoint": scenario["endpoint"],
        "Request Headers": json.dumps(redacted_headers),
        "Request Body": json.dumps(scenario.get("request_body") or {}),
        "Expected Status": scenario["expected_status"],
        "Actual Status": result["status_code"] if result["status_code"] is not None else "",
        "Expected Behaviour": scenario["expected_behavior"],
        "Actual Response": result["response_body"] or "",
        "Result": outcome,
        "Failure Reason": failure_reason,
        "Response Time (ms)": result["response_time_ms"],
    }


def _build_auth_header(auth_mode: str, header_name: str, auth_type: str, secret_value: str) -> dict:
    """
    The LLM never sees the real credential (shared/models/test_plan.py,
    AuthMode) — it only decides WHICH auth condition to test. This is
    where that decision actually becomes a header value.
    """
    if auth_mode == "missing":
        return {}

    if auth_mode == "invalid":
        return {header_name: "invalid-test-token-000000"}

    # auth_mode == "valid"
    if auth_type == "bearer":
        return {header_name: f"Bearer {secret_value}"}
    if auth_type == "api_key":
        return {header_name: secret_value}
    if auth_type == "basic":
        return {header_name: f"Basic {secret_value}"}

    # oauth2 or anything unrecognized — bearer-style is a reasonable
    # default; revisit if oauth2 needs a genuinely different token flow.
    return {header_name: f"Bearer {secret_value}"}


def _evaluate(scenario: dict, result: dict):
    if result["error"]:
        return "ERROR", result["error"]
    if result["status_code"] == scenario["expected_status"]:
        return "PASS", ""
    return "FAIL", f"Expected status {scenario['expected_status']}, got {result['status_code']}"


def _fail(team_id: str, run_id: str, error_detail: str):
    logger.error("run_id=%s FAILED: %s", run_id, error_detail)
    update_run_status(team_id, run_id, status="FAILED", error_detail=error_detail)