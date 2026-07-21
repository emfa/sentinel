"""
Local test runner for sentinel-intake — exercises both routes against
the REAL DynamoDB table, by hand-building the API Gateway proxy event
shape Lambda would actually receive.

Usage (from the sentinel/ repo root, in myenv — NOT cdk-env):
    python -m services.intake.local_dev.run_local
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import boto3  # noqa: E402

from services.intake.handler import lambda_handler  # noqa: E402
from shared.aws.dynamodb_client import TABLE_NAME  # noqa: E402

SAMPLE_PATH = Path(__file__).parent / "sample_new_run_request.json"
TEAM_ID = "sandbox-team"


def _api_gateway_event(method: str, body: dict, run_id: str = None) -> dict:
    return {
        "httpMethod": method,
        "pathParameters": {"run_id": run_id} if run_id else None,
        "headers": {"X-Team-ID": TEAM_ID, "Content-Type": "application/json"},
        "body": json.dumps(body),
    }


def _print_response(label: str, response: dict):
    print(f"--- {label} ---")
    print(f"statusCode: {response['statusCode']}")
    print(json.dumps(json.loads(response["body"]), indent=2))
    print()


def main():
    with open(SAMPLE_PATH) as f:
        new_run_body = json.load(f)

    # 1. Submit a new run
    event = _api_gateway_event("POST", new_run_body)
    response = lambda_handler(event, None)
    _print_response("POST /runs", response)

    if response["statusCode"] != 202:
        print("New run submission failed — stopping here.")
        return

    run_id = json.loads(response["body"])["run_id"]

    # 2. Confirm it's actually in DynamoDB
    table = boto3.resource("dynamodb").Table(TABLE_NAME)
    item = table.get_item(Key={"team_id": TEAM_ID, "run_id": run_id})["Item"]
    print(f"Confirmed in DynamoDB: status={item['status']}, parent_run_id={item.get('parent_run_id')}")
    print()

    # 3. Trigger a re-run against that same run, with a context note
    rerun_event = _api_gateway_event(
        "POST", {"context_note": "Also test the loan-to-income ratio at exactly 5x"}, run_id=run_id
    )
    rerun_response = lambda_handler(rerun_event, None)
    _print_response("POST /runs/{run_id}/rerun", rerun_response)

    if rerun_response["statusCode"] != 202:
        print("Re-run failed — stopping here.")
        return

    rerun_id = json.loads(rerun_response["body"])["rerun_id"]

    # 4. Trigger a SECOND re-run against the FIRST re-run — this is the
    #    real test of the flattened parent chain. parent_run_id should
    #    still point at the ORIGINAL run_id, not at rerun_id.
    second_rerun_event = _api_gateway_event("POST", {}, run_id=rerun_id)
    second_rerun_response = lambda_handler(second_rerun_event, None)
    _print_response("POST /runs/{rerun_id}/rerun (re-run of a re-run)", second_rerun_response)

    second_rerun_id = json.loads(second_rerun_response["body"])["rerun_id"]
    second_item = table.get_item(Key={"team_id": TEAM_ID, "run_id": second_rerun_id})["Item"]

    print(f"Original run_id:        {run_id}")
    print(f"First rerun_id:         {rerun_id}")
    print(f"Second rerun_id:        {second_rerun_id}")
    print(f"Second rerun's parent_run_id: {second_item.get('parent_run_id')}")
    print(f"Chain is flat: {second_item.get('parent_run_id') == run_id}")


if __name__ == "__main__":
    main()