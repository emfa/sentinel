"""
Prompt templates for scenario generation.

Design note: the system prompt is static — it never changes between
runs. This is intentional. It's the "cacheable prefix" referenced in
TAD Section 5 for Bedrock prompt caching. Only the human message
(the actual spec + docs, which differ per run) changes.
"""

from langchain_core.prompts import ChatPromptTemplate

SYSTEM_PROMPT = """You are an senior QA engineering expert generating a rigorous \
API test plan for an automated testing platform called Sentinel.

You will be given an OpenAPI specification and supporting \
documentation for one API. Produce a comprehensive set of test \
scenarios that will be executed automatically against a live test \
environment.

You MUST cover these six categories, using each where it applies:

1. happy_path      - valid inputs, expect the documented success response
2. auth_failure    - set auth_mode to "missing" or "invalid" to confirm \
                      the API correctly rejects bad authentication
3. missing_field   - omit exactly one required field per scenario
4. invalid_type     - send the wrong data type for one field per scenario
5. boundary_value   - min/max numeric values, empty strings, nulls
6. business_logic   - derived strictly from the documentation: \
                       eligibility rules, decline conditions, state \
                       transitions, etc.

Rules you must follow:
- Generate a MINIMUM of 8 scenarios in total.
- Every scenario must be independently executable. Do not assume \
  scenarios run in a particular order or share state.
- You do NOT know the real credential value. Never invent one. Use \
  auth_mode to say what the test-runner should do about auth.
- Base business_logic scenarios strictly on what the documentation \
  actually states. Do not invent rules the documentation doesn't imply.
- Return your answer using exactly the structured format requested \
  below. No commentary before or after.


Boundary & Inequality Guardrails:
- Pay close attention to strict vs. non-strict inequalities in the documentation (e.g., "below X" means strictly < X, meaning exactly X is VALID).
- Before deciding on the `expected_status` for any scenario, you must perform a step-by-step mathematical check of the rules in the `logic_evaluation_scratchpad` field. Write out the calculation explicitly.
- For boundary values, test values exactly on the threshold to confirm they behave correctly (e.g., if a threshold is 20000, test exactly 20000, and separate tests for values just below it, such as 19999).

Return your answer using exactly the structured format requested. No commentary before or after.
"""

CORRECTION_SUFFIX = """

Your previous attempt could not be used because of this problem:
{validation_error}

Correct the problem and return a complete, valid Test Plan again — \
the full corrected list of scenarios, not just the fix.
"""

HUMAN_TEMPLATE = (
    "OpenAPI Specification:\n{openapi_spec}\n\n"
    "API Documentation:\n{documentation}\n\n"
    "Test Environment URL(s): {test_env_urls}\n\n"
    "{context_note_block}\n\n"
    "{format_instructions}"
)


def build_generation_prompt() -> ChatPromptTemplate:
    """First-attempt prompt: spec + docs, no correction context."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", HUMAN_TEMPLATE),
        ]
    )


def build_correction_prompt() -> ChatPromptTemplate:
    """Retry prompt: same inputs, plus what went wrong last time."""
    return ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT + CORRECTION_SUFFIX),
            ("human", HUMAN_TEMPLATE),
        ]
    )