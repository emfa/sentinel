"""
Pydantic model representing a Sentinel run record — the single
source of truth read from DynamoDB (see TAD Section 6.1).

For sentinel-scenario-generator, this record IS the entire context
it gets. There is no separate "API Context Document" — the run
record read from DynamoDB is the context, per the Gap 2 decision
made during architecture review.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class RunRecord(BaseModel):
    run_id: str
    team_id: str
    status: str

    openapi_spec: str = Field(
        description="Raw OpenAPI spec, JSON or YAML string, as submitted"
    )
    auth_type: str = Field(description="bearer | api_key | basic | oauth2")
    auth_header_name: str

    vault_secret_reference: str = Field(
        description=(
            "Key Vault secret name. This is a REFERENCE only — never "
            "the actual credential. scenario-generator never has "
            "access to real secrets and must never need them."
        )
    )

    test_env_urls: List[str]
    documentation: str = Field(
        description=(
            "Team-provided API documentation. Primary source for "
            "business-logic test scenario generation."
        )
    )

    timeout_ms: int = 10_000

    context_note: Optional[str] = Field(
        default=None,
        description=(
            "Extra guidance provided on a re-run to correct a "
            "previous bad generation."
        ),
    )
    parent_run_id: Optional[str] = None