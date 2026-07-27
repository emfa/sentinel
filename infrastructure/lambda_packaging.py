"""
infrastructure/lambda_packaging.py

Solves a mechanical problem left open since Day 1: "shared/ gets
bundled directly into each Lambda's zip" was the decision, but never
implemented at the CDK level. CDK's Code.from_asset(path) only stages
what's under `path` — it has no built-in way to also pull in a
sibling directory like shared/.

The fix: before any stack is defined, copy each service's own code
PLUS a fresh copy of shared/ into infrastructure/.build/{service}/.
compute_stack.py then points Code.from_asset at that already-merged
folder — a single, self-contained directory per Lambda, nothing
clever needed inside the Docker bundling command itself.

Runs automatically at the top of app.py on every `cdk synth` /
`cdk deploy`, so the staged folders are always fresh, never stale.
"""

import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SHARED_DIR = REPO_ROOT / "shared"
SERVICES_DIR = REPO_ROOT / "services"
BUILD_DIR = Path(__file__).resolve().parent / ".build"

SERVICES = ["intake", "dispatcher", "scenario_generator", "test_runner"]

# local_dev/ is test-only tooling, never needed in the deployed
# Lambda — skipping it keeps the zip smaller and bundling faster.
EXCLUDE_DIRS = {"local_dev", "__pycache__"}


def stage_all_lambda_packages():
    if BUILD_DIR.exists():
        shutil.rmtree(BUILD_DIR)
    BUILD_DIR.mkdir(parents=True)

    for service in SERVICES:
        _stage_one_package(service)


def _stage_one_package(service: str):
    source = SERVICES_DIR / service
    dest = BUILD_DIR / service
    dest.mkdir(parents=True)

    _copy_tree(source, dest)
    _copy_tree(SHARED_DIR, dest / "shared")


def _copy_tree(source: Path, dest: Path):
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        if any(part in EXCLUDE_DIRS for part in relative.parts):
            continue
        target = dest / relative
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)