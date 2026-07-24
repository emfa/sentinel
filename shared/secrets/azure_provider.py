"""
Azure Key Vault provider — BACKLOG, NOT IMPLEMENTED.

Stubbed per Day 5 decision: no Azure credentials or Key Vault
instance available to build or test against yet. Picked up when a
real Azure target exists.

Reference format (after router.py strips the "azure:" prefix):
  "{vault_name}/{secret_name}"

Expected implementation, using the azure-identity and
azure-keyvault-secrets SDKs:

    from azure.identity import DefaultAzureCredential
    from azure.keyvault.secrets import SecretClient

    def fetch_secret(provider_reference: str) -> str:
        vault_name, secret_name = provider_reference.split("/", 1)
        vault_url = f"https://{vault_name}.vault.azure.net"
        client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
        return client.get_secret(secret_name).value

When implemented, add azure-identity and azure-keyvault-secrets to
requirements.txt, and confirm which auth mechanism the org's Azure
setup actually uses (managed identity vs. service principal) — that
choice changes which DefaultAzureCredential path actually fires.
"""


def fetch_secret(provider_reference: str) -> str:
    raise NotImplementedError(
        "Azure Key Vault provider is backlogged, not yet implemented. "
        f"Reference was: '{provider_reference}'"
    )