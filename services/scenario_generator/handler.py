"""
sentinel-scenario-generator Lambda handler.

Trigger: SQS (sentinel-stage2-queue) — TAD Section 4.3
Message format: {"run_id": "...", "team_id": "..."} — TAD Section 7.1

NOTE (Day 1 scope): the DynamoDB read, S3 write, and status update
are not wired up yet — that needs the storage stack deployed first,
which is next session's work. For now this handler expects the full
run record to be embedded in the event so we can test the
generation logic end to end without any AWS infrastructure beyond
Bedrock itself.
"""

import json
import logging

from shared.llm.graph import run_scenario_generation
from shared.models.run_record import RunRecord

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def lambda_handler(event, context):
    for record in event.get("Records", []):
        body = json.loads(record["body"])
        _process_one_run(body)

    return {"statusCode": 200}


def _process_one_run(body: dict):
    run_id = body["run_id"]
    team_id = body["team_id"]
    logger.info("Processing run_id=%s team_id=%s", run_id, team_id)

    # TODO (next session): idempotency check —
    #   read status from DynamoDB, skip if already SCENARIOS_READY or beyond

    # TODO (next session): replace this with a real DynamoDB read keyed
    #   on (team_id, run_id) per TAD Section 6.1
    run_record = RunRecord(**body["run_record"])

    test_plan = run_scenario_generation(run_record)

    logger.info(
        "Generated %d scenarios for run_id=%s", len(test_plan.scenarios), run_id
    )

    # TODO (next session):
    #   - write test_plan to S3 at runs/{team_id}/{run_id}/test-plan.json
    #   - update DynamoDB: status=SCENARIOS_READY, test_plan_s3_key=...
    #   - DynamoDB Stream then fires -> dispatcher routes to stage3 queue

    return test_plan