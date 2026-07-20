"""
Thin wrapper around the Bedrock chat model and the structured
output parser. This is the "LLM Abstraction Module" from TAD
Section 5 — everything LangChain/Bedrock-specific lives here so
the rest of the pipeline never touches LangChain directly.
"""

import os

from langchain_aws import ChatBedrock
from langchain_core.output_parsers import PydanticOutputParser

from shared.models.test_plan import TestPlan

# Use Amazon Nova Lite as the default native model to bypass AWS Marketplace subscription checks.
SCENARIO_MODEL_ID = os.environ.get(
    "SENTINEL_SCENARIO_MODEL_ID",
    "global.amazon.nova-2-lite-v1:0",
)



def get_chat_model() -> ChatBedrock:
    """
    Returns the LangChain chat model used for scenario generation.

    temperature=0.2 — we want consistent, rigorous test plans, not
    creative variation. This is a QA task, not a brainstorm.
    """
    return ChatBedrock(
        model_id=SCENARIO_MODEL_ID,
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
        model_kwargs={
            "temperature": 0.2,
            "max_tokens": 4096,
        },
    )


def get_test_plan_parser() -> PydanticOutputParser:
    """Parser that coerces the model's text output into a TestPlan."""
    return PydanticOutputParser(pydantic_object=TestPlan)