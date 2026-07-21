"""
sentinel-scenario-generator Lambda handler.

Trigger: SQS (sentinel-stage2-queue) — TAD Section 4.3
Message format: {"run_id": "...", "team_id": "..."} — TAD Section 7.1

Day 2 update: wired to real DynamoDB and S3 (Day 1's TODOs resolved).
"""

import json
import logging

from shared.aws.dynamodb_client import get_run_record, now_iso, update_run_status
from shared.aws.s3_client import test_plan_key, write_json
from shared.llm.graph import run_scenario_generation
from shared.models.run_record import RunRecord

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Statuses that mean generation already happened for this run — safe
# to skip on SQS at-least-once redelivery. TAD Section 4.3,
# "Idempotency Check".
ALREADY_PROCESSED_STATUSES = {"SCENARIOS_READY", "COMPLETED", "FAILED"}


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

    run_record = RunRecord(**item)

    try:
        test_plan = run_scenario_generation(run_record)
    except RuntimeError as e:
        logger.error("Scenario generation failed for run_id=%s: %s", run_id, e)
        update_run_status(team_id, run_id, status="FAILED", error_detail=str(e))
        return

    key = test_plan_key(team_id, run_id)
    write_json(key, json.loads(test_plan.model_dump_json()))

    update_run_status(
        team_id,
        run_id,
        status="SCENARIOS_READY",
        test_plan_s3_key=key,
        stage2_completed_at=now_iso(),
    )

    logger.info(
        "Generated %d scenarios for run_id=%s, wrote to %s",
        len(test_plan.scenarios), run_id, key,
    )