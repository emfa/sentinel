"""
Thin wrapper around SNS for sentinel-dispatcher notifications
(TAD Section 4.4).

Topic ARNs are CONSTRUCTED, not looked up. TAD Section 12 defines the
naming convention (sentinel-notifications-{team_id}) as something the
platform team sets up once per team at onboarding — so at notify
time, dispatcher just needs to build the ARN string, not search for
it. The only missing piece is the AWS account ID, which isn't
available as a plain environment variable, so it's fetched once via
STS and cached at module level — a standard pattern for avoiding a
repeated API call on every warm Lambda invocation.
"""

import os

import boto3

_sns = boto3.client("sns")
_sts = boto3.client("sts")

_account_id_cache = None


def _account_id() -> str:
    global _account_id_cache
    if _account_id_cache is None:
        _account_id_cache = _sts.get_caller_identity()["Account"]
    return _account_id_cache


def topic_arn_for_team(team_id: str) -> str:
    region = os.environ.get("AWS_REGION") or boto3.Session().region_name
    return f"arn:aws:sns:{region}:{_account_id()}:sentinel-notifications-{team_id}"


def publish(team_id: str, subject: str, message: str) -> None:
    _sns.publish(
        TopicArn=topic_arn_for_team(team_id),
        Subject=subject[:100],  # SNS hard limit on subject length
        Message=message,
    )