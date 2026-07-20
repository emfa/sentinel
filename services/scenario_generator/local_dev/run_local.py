"""
Local test runner for sentinel-scenario-generator.

Run this directly on your machine (with AWS credentials configured
and Bedrock model access enabled for Claude Sonnet) to test scenario
generation without needing any AWS infrastructure deployed yet.

Usage (from the sentinel/ repo root):
    python -m services.scenario_generator.local_dev.run_local
"""

import json
import sys
from pathlib import Path

# Lets this run directly during early development, before the
# project is packaged as an installable module
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from shared.llm.graph import run_scenario_generation  # noqa: E402
from shared.models.run_record import RunRecord  # noqa: E402

SAMPLE_PATH = Path(__file__).parent / "sample_run_record.json"


def main():
    with open(SAMPLE_PATH) as f:
        data = json.load(f)

    run_record = RunRecord(**data)

    print(f"Generating test plan for run_id={run_record.run_id}...\n")
    test_plan = run_scenario_generation(run_record)

    print(f"Generated {len(test_plan.scenarios)} scenarios:\n")
    for s in test_plan.scenarios:
        print(f"  [{s.category.value}] {s.scenario_id} - {s.scenario_name}")
        print(f"      {s.http_method} {s.endpoint} -> expect {s.expected_status}")

    out_path = Path(__file__).parent / "test_plan_output.json"
    with open(out_path, "w") as f:
        f.write(test_plan.model_dump_json(indent=2))

    print(f"\nFull Test Plan written to {out_path}")


if __name__ == "__main__":
    main()