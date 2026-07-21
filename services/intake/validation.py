"""
Validation logic for sentinel-intake — TAD Section 4.1, "Validation Rules".

Deliberately matches only the four checks the architect actually signed
off on (TAD Section 14 decisions log) — no extra validation gold-plated
in beyond what's documented. If we want stricter checks later (e.g.
validating auth.type is one of the four known values), that's an easy
addition, but today this stays exactly as scoped.

Every check runs regardless of earlier failures, so a team gets every
problem back in one response rather than discovering them one at a time
across multiple resubmissions.
"""

import json
from typing import Optional
from urllib.parse import urlparse

import yaml

MAX_SPEC_BYTES = 300 * 1024  # 300KB — TAD Section 14, architect sign-off
MIN_DOC_CHARS = 100


def validate_openapi_spec(spec) -> Optional[str]:
    if not spec or not isinstance(spec, str) or not spec.strip():
        return "openapi_spec is required"

    # Size check runs BEFORE parsing — cheap, and catches the common
    # accidental-huge-file case before spending time trying to parse it.
    size = len(spec.encode("utf-8"))
    if size > MAX_SPEC_BYTES:
        return (
            f"openapi_spec is {size} bytes, exceeds the 300KB limit for V1. "
            f"V2 will lift this via the Claim Check pattern (TAD Section 14)."
        )

    try:
        json.loads(spec)
        return None
    except (json.JSONDecodeError, TypeError):
        pass

    try:
        yaml.safe_load(spec)
        return None
    except yaml.YAMLError:
        return "openapi_spec is not valid JSON or YAML"


def validate_auth(auth) -> Optional[str]:
    """
    TAD's stated rule is narrow, on purpose: only check the vault
    reference is present and non-empty. No Key Vault lookup happens
    here — that's Stage 3's job, at execution time.
    """
    if not isinstance(auth, dict):
        return "auth is required and must be an object"

    vault_ref = auth.get("vault_secret_reference")
    if not vault_ref or not str(vault_ref).strip():
        return "auth.vault_secret_reference is required and must be non-empty"

    return None


def validate_test_env_urls(urls) -> Optional[str]:
    """Well-formed URL string only — no reachability check (TAD Section 4.1)."""
    if not urls or not isinstance(urls, list) or len(urls) == 0:
        return "test_env_urls must contain at least one URL"

    for url in urls:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return f"'{url}' is not a well-formed http(s) URL"

    return None


def validate_documentation(documentation) -> Optional[str]:
    if not documentation or len(str(documentation).strip()) < MIN_DOC_CHARS:
        actual = len(str(documentation).strip()) if documentation else 0
        return f"documentation must be at least {MIN_DOC_CHARS} characters, got {actual}"
    return None


def validate_submission(body: dict) -> dict:
    """
    Returns {field_name: error_message} for every failing field.
    Empty dict means the submission satisfies the Minimum API Contract.
    """
    errors = {}

    if err := validate_openapi_spec(body.get("openapi_spec")):
        errors["openapi_spec"] = err

    if err := validate_auth(body.get("auth")):
        errors["auth"] = err

    if err := validate_test_env_urls(body.get("test_env_urls")):
        errors["test_env_urls"] = err

    if err := validate_documentation(body.get("documentation")):
        errors["documentation"] = err

    return errors