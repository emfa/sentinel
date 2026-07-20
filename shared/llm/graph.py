"""
LangGraph workflow wrapping scenario generation with a
self-correction loop.

Why this exists: a plain linear call — prompt -> Bedrock -> parse —
fails hard the moment the model returns something that doesn't
parse into a TestPlan (missing fields, wrong types, fewer than 8
scenarios). Without this graph, that failure would set the run
straight to FAILED and force the team to manually trigger a re-run.

This graph gives the model up to MAX_ATTEMPTS chances to fix its
own output before we give up and let the pipeline's normal FAILED
handling take over.

Graph shape:

    generate ──> validate ──success──> END
                    │
                    ├──retry (attempt < MAX_ATTEMPTS)──> generate
                    │
                    └──give_up (attempt >= MAX_ATTEMPTS)──> END
"""

from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from shared.llm.client import get_chat_model, get_test_plan_parser
from shared.llm.prompts import build_correction_prompt, build_generation_prompt
from shared.models.run_record import RunRecord
from shared.models.test_plan import TestPlan

MAX_ATTEMPTS = 3
MIN_SCENARIOS = 8


class GenerationState(TypedDict):
    run_record: RunRecord
    attempt: int
    raw_output: Optional[str]
    validation_error: Optional[str]
    test_plan: Optional[TestPlan]


def _context_note_block(run_record: RunRecord) -> str:
    if run_record.context_note:
        return f"Additional context from a re-run request:\n{run_record.context_note}"
    return ""


def generate_node(state: GenerationState) -> GenerationState:
    """Calls Bedrock. Uses the correction prompt if this is a retry."""
    run_record = state["run_record"]
    model = get_chat_model()
    parser = get_test_plan_parser()

    is_retry = state.get("validation_error") is not None
    prompt = build_correction_prompt() if is_retry else build_generation_prompt()

    chain = prompt | model

    result = chain.invoke(
        {
            "openapi_spec": run_record.openapi_spec,
            "documentation": run_record.documentation,
            "test_env_urls": ", ".join(run_record.test_env_urls),
            "context_note_block": _context_note_block(run_record),
            "format_instructions": parser.get_format_instructions(),
            "validation_error": state.get("validation_error", ""),
        }
    )

    return {
        **state,
        "raw_output": result.content,
        "attempt": state["attempt"] + 1,
    }


def validate_node(state: GenerationState) -> GenerationState:
    """Tries to parse raw_output into a TestPlan. Sets validation_error on failure."""
    parser = get_test_plan_parser()
    run_id = state["run_record"].run_id

    try:
        plan = parser.parse(state["raw_output"])
        plan.run_id = run_id  # stamp it ourselves — don't trust the LLM to get this right

        if len(plan.scenarios) < MIN_SCENARIOS:
            raise ValueError(
                f"Only {len(plan.scenarios)} scenarios generated, "
                f"minimum required is {MIN_SCENARIOS}"
            )

        return {**state, "test_plan": plan, "validation_error": None}

    except (ValidationError, ValueError) as e:
        return {**state, "validation_error": str(e)}


def route_after_validation(state: GenerationState) -> str:
    if state.get("test_plan") is not None:
        return "success"
    if state["attempt"] >= MAX_ATTEMPTS:
        return "give_up"
    return "retry"


def build_graph():
    graph = StateGraph(GenerationState)

    graph.add_node("generate", generate_node)
    graph.add_node("validate", validate_node)

    graph.set_entry_point("generate")
    graph.add_edge("generate", "validate")

    graph.add_conditional_edges(
        "validate",
        route_after_validation,
        {
            "success": END,
            "retry": "generate",
            "give_up": END,
        },
    )

    return graph.compile()


def run_scenario_generation(run_record: RunRecord) -> TestPlan:
    """
    Public entry point used by both the Lambda handler and local
    testing. Runs the graph to completion and returns a TestPlan.

    Raises RuntimeError if the model could not produce a valid
    Test Plan within MAX_ATTEMPTS.
    """
    app = build_graph()

    final_state: GenerationState = app.invoke(
        {
            "run_record": run_record,
            "attempt": 0,
            "raw_output": None,
            "validation_error": None,
            "test_plan": None,
        }
    )

    if final_state.get("test_plan") is None:
        raise RuntimeError(
            f"Scenario generation failed after {MAX_ATTEMPTS} attempts. "
            f"Last error: {final_state.get('validation_error')}"
        )

    return final_state["test_plan"]