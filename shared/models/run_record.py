"""
Pydantic model representing a Sentinel run record — the single
source of truth read from DynamoDB (TAD Section 6.1).

Day 3 update: expanded from the narrow scenario-generator-only view
used on Day 1/2 to the FULL record shape, since sentinel-intake now
writes this record directly. One canonical model, shared across
every Lambda that touches DynamoDB — a narrower per-Lambda view was
flagged as a drift risk during the Day 3 TAD/PRD recap and fixed
here rather than left to quietly diverge.
"""

from typing import List, Optional

from pydantic import BaseModel, Field


class RunRecord(BaseModel):
    run_id: str
    team_id: str
    status: str

    # Set once at creation by sentinel-intake — for both fresh runs
    # and re-runs — and never touched again.
    created_at: str
    ttl_timestamp: int = Field(
        description=(
            "Unix epoch SECONDS, not milliseconds — DynamoDB's TTL "
            "feature specifically requires seconds. Passing "
            "milliseconds here silently sets the expiry centuries "
            "in the future instead of erroring."
        )
    )

    # Updated by whichever Lambda last touched this record.
    updated_at: str

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

    # Re-run chain — TAD Section 4.1, Gap 3 from architecture review.
    # Always points to the ORIGINAL parent, never nests.
    context_note: Optional[str] = None
    parent_run_id: Optional[str] = None

    # Populated progressively as the run moves through the pipeline.
    # Absent/None until the relevant stage actually completes.
    test_plan_s3_key: Optional[str] = None
    report_s3_key: Optional[str] = None
    stage2_completed_at: Optional[str] = None
    stage3_completed_at: Optional[str] = None
    error_detail: Optional[str] = None
    notification_email: Optional[str] = None