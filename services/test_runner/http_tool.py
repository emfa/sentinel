"""
The HTTP Tool — TAD Section 4.4.

The only place in all of Sentinel that makes an outbound HTTP call to
an API under test. Deliberately NOT a separate service — just an
internal function inside sentinel-test-runner, per TAD's explicit
design (a single-purpose tool, not its own Lambda).

Constraints, all from TAD Section 4.4:
  - Timeout: from run config, default 10,000ms, max 30,000ms
  - Retries: ONE automatic retry, connection-level failures only.
             No retry on 4xx/5xx — those are recorded as-is.
  - Response size: captured up to 64KB, truncated beyond that
  - Redirects: followed automatically, max 3 hops
  - SSL: standard certificate validation enforced
  - Protocols: HTTP and HTTPS only
"""

import time

import requests

MAX_RESPONSE_BYTES = 64 * 1024
MAX_REDIRECTS = 3
DEFAULT_TIMEOUT_MS = 10_000
MAX_TIMEOUT_MS = 30_000

_session = requests.Session()
_session.max_redirects = MAX_REDIRECTS


def execute_scenario(method: str, url: str, headers: dict, body, timeout_ms: int) -> dict:
    """
    Executes one scenario's HTTP request.

    Returns:
        {status_code, response_body, response_time_ms, error}

    `error` is None for any request that completed an HTTP exchange —
    including 4xx and 5xx responses, which are not errors, just
    results. `error` is only populated when the connection itself
    never succeeded (timeout, refused connection, too many redirects)
    after the retry is exhausted.
    """
    timeout_ms = min(timeout_ms or DEFAULT_TIMEOUT_MS, MAX_TIMEOUT_MS)
    timeout_seconds = timeout_ms / 1000

    last_exception = None
    start = time.monotonic()

    for _attempt in range(2):  # 1 initial attempt + 1 retry, connection failures only
        start = time.monotonic()
        try:
            response = _session.request(
                method=method,
                url=url,
                headers=headers,
                json=body if body else None,
                timeout=timeout_seconds,
                allow_redirects=True,
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)

            raw = response.content
            truncated = len(raw) > MAX_RESPONSE_BYTES
            text = raw[:MAX_RESPONSE_BYTES].decode("utf-8", errors="replace")

            return {
                "status_code": response.status_code,
                "response_body": text + (" [TRUNCATED]" if truncated else ""),
                "response_time_ms": elapsed_ms,
                "error": None,
            }

        except requests.exceptions.TooManyRedirects:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return {
                "status_code": None,
                "response_body": None,
                "response_time_ms": elapsed_ms,
                "error": f"Exceeded {MAX_REDIRECTS} redirects",
            }

        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
            last_exception = e
            continue  # the one automatic retry, connection-level failures only

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {
        "status_code": None,
        "response_body": None,
        "response_time_ms": elapsed_ms,
        "error": f"{type(last_exception).__name__}: {last_exception}",
    }