#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

import httpx


@dataclass
class CheckResult:
    ok: bool
    reason: str


def api_base() -> str:
    return os.environ.get("API_BASE", "http://localhost:8000")


def check_health(base: str) -> CheckResult:
    try:
        response = httpx.get(f"{base}/health", timeout=15)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"/health request failed: {exc}")

    if response.status_code != 200:
        return CheckResult(False, f"/health returned HTTP {response.status_code}")

    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return CheckResult(False, "/health response is not JSON")

    agents = payload.get("agents", {})
    researcher = agents.get("researcher")
    if researcher != "ok":
        return CheckResult(False, f"researcher heartbeat not ok: {researcher}")
    return CheckResult(True, "health ok (researcher heartbeat present)")


def check_current_picture(base: str) -> CheckResult:
    try:
        response = httpx.get(f"{base}/current-picture/latest", timeout=20)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"/current-picture/latest request failed: {exc}")

    if response.status_code == 404:
        return CheckResult(True, "current picture warming up (404 expected before first generation)")

    if response.status_code != 200:
        return CheckResult(False, f"/current-picture/latest returned HTTP {response.status_code}")

    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return CheckResult(False, "/current-picture/latest response is not JSON")

    content = str(payload.get("content") or "").strip()
    if not content:
        return CheckResult(False, "current-picture payload missing content")

    generated_at = payload.get("generated_at")
    stale = payload.get("stale")
    pipeline_version = str(payload.get("pipeline_version") or "").strip()
    model_chain = payload.get("model_chain") or []
    if not pipeline_version:
        return CheckResult(False, "current-picture payload missing pipeline_version")
    if not isinstance(model_chain, list) or len(model_chain) < 3:
        return CheckResult(False, "current-picture payload missing staged model_chain metadata")
    return CheckResult(
        True,
        f"current picture loaded (generated_at={generated_at}, stale={stale}, pipeline={pipeline_version})",
    )


def check_deprecated_route(base: str) -> CheckResult:
    try:
        response = httpx.get(f"{base}/context/current-picture", timeout=15)
    except Exception as exc:  # noqa: BLE001
        return CheckResult(False, f"deprecated route check failed: {exc}")

    if response.status_code != 410:
        return CheckResult(False, f"expected 410 on /context/current-picture, got {response.status_code}")
    return CheckResult(True, "deprecated route returns 410")


def run_check(name: str, fn) -> bool:
    print(f"Checking: {name}")
    result = fn()
    status = "PASS" if result.ok else "FAIL"
    print(f"{status}: {result.reason}")
    return result.ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Minimal validator for current-picture app")
    parser.add_argument("--base", default=api_base(), help="API base URL (default from API_BASE env or http://localhost:8000)")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    checks = [
        ("health", lambda: check_health(base)),
        ("current-picture", lambda: check_current_picture(base)),
        ("deprecated-route", lambda: check_deprecated_route(base)),
    ]

    passed = 0
    for name, fn in checks:
        ok = run_check(name, fn)
        passed += 1 if ok else 0

    print(json.dumps({"base": base, "passed": passed, "total": len(checks)}, indent=2))
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
