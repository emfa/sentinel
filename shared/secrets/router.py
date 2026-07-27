"""
Cloud-agnostic secret fetcher for sentinel-test-runner.

Reference format: "{provider}:{provider-specific-reference}"
  aws:sentinel/team-x/loan-api/token   -> AWS Secrets Manager
  azure:my-vault-name/loan-api-token    -> Azure Key Vault (BACKLOG)

Adding a new provider (e.g. GCP) later is: one new file exposing
fetch_secret(provider_reference), plus one more branch here. Nothing
else in the codebase needs to know a new provider exists —
sentinel-test-runner only ever calls fetch_secret() from this module.
"""

from shared.secrets import aws_provider, azure_provider

SUPPORTED_PROVIDERS = {"aws", "azure"}


def fetch_secret(reference: str) -> str:
    if ":" not in reference:
        raise ValueError(
            f"Secret reference '{reference}' is missing a provider prefix. "
            f"Expected format: '<provider>:<reference>', e.g. 'aws:my-secret-name'"
        )

    provider, provider_reference = reference.split(":", 1)
    provider = provider.strip().lower()

    if provider == "aws":
        return aws_provider.fetch_secret(provider_reference)

    if provider == "azure":
        return azure_provider.fetch_secret(provider_reference)

    raise ValueError(
        f"Unknown secret provider '{provider}'. Supported: {sorted(SUPPORTED_PROVIDERS)}"
    )