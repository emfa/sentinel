"""
Pydantic models describing the structured Test Plan that
sentinel-scenario-generator must produce.

This is the CONTRACT between the LLM and the rest of the pipeline.
sentinel-test-runner will read exactly this structure — nothing
more, nothing less. If the LLM's output can't be coerced into this
shape, we treat the generation as failed and retry (see
shared/llm/graph.py for the retry loop).
"""

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class ScenarioCategory(str, Enum):
    """The six test categories mandated in TAD Section 6.2."""

    HAPPY_PATH = "happy_path"
    AUTH_FAILURE = "auth_failure"
    MISSING_FIELD = "missing_field"
    INVALID_TYPE = "invalid_type"
    BOUNDARY_VALUE = "boundary_value"
    BUSINESS_LOGIC = "business_logic"


class AuthMode(str, Enum):
    """
    How the test-runner should handle auth for this scenario.

    Deliberate design choice: the LLM NEVER sees or invents the real
    credential value. scenario-generator only has the OpenAPI spec
    and documentation — it never touches the Key Vault. So instead
    of asking the model to produce a header value, we ask it to
    decide *which auth condition* to test, and the test-runner
    injects the real value (or omits/corrupts it) at execution time.
    """

    VALID = "valid"      # test-runner injects the real credential
    MISSING = "missing"  # test-runner omits the auth header entirely
    INVALID = "invalid"  # test-runner injects a deliberately wrong value


class TestScenario(BaseModel):
    """A single test scenario the test-runner will execute."""

    scenario_id: str = Field(description="Short unique id, e.g. 'TC-001'")
    scenario_name: str = Field(
        description="Short human-readable name, e.g. 'Missing auth token'"
    )
    description: str = Field(
        description="What this scenario tests and why it matters"
    )
    category: ScenarioCategory
    http_method: str = Field(description="GET, POST, PUT, PATCH, or DELETE")
    endpoint: str = Field(description="Full endpoint path, e.g. '/applications'")

    auth_mode: AuthMode = Field(
        default=AuthMode.VALID,
        description=(
            "Whether the test-runner should inject the real credential "
            "(valid), omit it (missing), or inject a deliberately wrong "
            "value (invalid). Never a literal credential value."
        ),
    )
    additional_headers: Dict[str, str] = Field(
        default_factory=dict,
        description="Non-auth headers, e.g. Content-Type",
    )
    request_body: Optional[Dict] = Field(
        default=None, description="JSON body to send, if applicable"
    )

    logic_evaluation_scratchpad: str = Field(
        description="Scratchpad for the LLM to work out the business logic",
    )
    expected_status: int = Field(description="Expected HTTP status code")
    expected_behavior: str = Field(
        description="Plain-English description of what a correct response should show"
    )


class TestPlan(BaseModel):
    """The complete set of scenarios generated for one run."""

    run_id: str
    scenarios: List[TestScenario] = Field(
        description=(
            "Minimum 8 scenarios per PRD success metrics, covering all "
            "six categories where applicable to this API"
        )
    )