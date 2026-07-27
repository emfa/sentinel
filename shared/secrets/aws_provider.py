"""
AWS Secrets Manager provider for the cloud-agnostic secret router.

Reference format (after router.py strips the "aws:" prefix): the raw
secret name or ARN, exactly as Secrets Manager expects it.
"""

import boto3

_client = boto3.client("secretsmanager")


def fetch_secret(provider_reference: str) -> str:
    response = _client.get_secret_value(SecretId=provider_reference)
    return response["SecretString"]