#!/usr/bin/env python3
"""
PravaasiDesk readiness checks.

Usage:
    python3 evals.py
    python3 evals.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import sys
from typing import Any

import httpx

G, R, Y, B, X = "\033[92m", "\033[91m", "\033[93m", "\033[96m", "\033[0m"
results: list[tuple[str, str]] = []


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="PravaasiDesk readiness checks")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL for the running PravaasiDesk server",
    )
    return parser.parse_args()


def record(name: str, status: str, detail: str = "") -> None:
    icon = {
        "PASS": f"{G}✓ PASS{X}",
        "FAIL": f"{R}✗ FAIL{X}",
        "WARN": f"{Y}~ WARN{X}",
    }[status]
    print(f"  {icon}  {name}")
    if detail:
        for line in detail.splitlines():
            print(f"          {line}")
    results.append((name, status))


def request_json(
    client: httpx.Client,
    method: str,
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    timeout: float = 20.0,
) -> tuple[int, Any]:
    response = client.request(
        method,
        f"{base_url}{path}",
        json=payload,
        timeout=timeout,
    )
    try:
        body = response.json()
    except Exception:
        body = response.text
    return response.status_code, body


def require_ok(status_code: int, body: Any, path: str) -> None:
    if status_code >= 400:
        raise RuntimeError(f"{path} returned {status_code}: {body}")


def main() -> int:
    args = parse_args()
    base_url = args.base_url.rstrip("/")
    print(f"\n{B}PravaasiDesk evals{X}  →  {base_url}\n")

    with httpx.Client() as client:
        try:
            status_code, _ = request_json(client, "GET", base_url, "/healthz")
            if status_code >= 400:
                raise RuntimeError(f"/healthz returned {status_code}")
        except Exception as exc:
            record("Server reachable", "FAIL", str(exc))
            print(f"\n{R}Server down — aborting.{X}\n")
            return 1

        checks = [
            ("GET /", "GET", "/", None),
            ("GET /demo", "GET", "/demo", None),
            ("GET /healthz", "GET", "/healthz", None),
            ("GET /api/config/public", "GET", "/api/config/public", None),
            ("POST /api/demo/seed", "POST", "/api/demo/seed", {}),
            ("POST /api/demo/wage", "POST", "/api/demo/wage", {}),
            ("POST /api/demo/health", "POST", "/api/demo/health", {}),
            ("GET /api/state", "GET", "/api/state", None),
            ("POST /api/reset", "POST", "/api/reset", {}),
        ]

        latest_state: dict[str, Any] | None = None
        latest_health_demo: dict[str, Any] | None = None

        for label, method, path, payload in checks:
            try:
                status_code, body = request_json(client, method, base_url, path, payload)
                require_ok(status_code, body, path)

                if path == "/healthz":
                    ok = (
                        isinstance(body, dict)
                        and body.get("ok") is True
                        and body.get("service") == "PravaasiDesk"
                    )
                    if not ok:
                        raise RuntimeError(f"Unexpected /healthz body: {body}")

                if path == "/api/config/public":
                    if not isinstance(body, dict):
                        raise RuntimeError("Public config did not return JSON")
                    forbidden = [key for key in body.keys() if "key" in key.lower() or "secret" in key.lower()]
                    if forbidden:
                        raise RuntimeError(f"Public config leaked sensitive-looking fields: {forbidden}")

                if path == "/api/demo/seed":
                    case = body.get("current_case", {}) if isinstance(body, dict) else {}
                    transcript = body.get("transcript", []) if isinstance(body, dict) else []
                    ok = (
                        case.get("name") == "Ramesh Yadav"
                        and case.get("city") == "Bengaluru"
                        and len(transcript) >= 1
                    )
                    if not ok:
                        raise RuntimeError(f"Seed state missing expected case data: {body}")

                if path == "/api/demo/wage":
                    complaint = body.get("wage_complaint", {}) if isinstance(body, dict) else {}
                    ok = (
                        complaint.get("status") == "drafted_demo"
                        and complaint.get("employer_name") == "Sharma Constructions"
                        and complaint.get("days_unpaid") == 12
                    )
                    if not ok:
                        raise RuntimeError(f"Wage demo missing expected complaint data: {body}")

                if path == "/api/demo/health":
                    latest_health_demo = body if isinstance(body, dict) else None
                    card = body.get("health_card", {}) if isinstance(body, dict) else {}
                    ok = (
                        card.get("text") == "ನನಗೆ ಹೊಟ್ಟೆ ನೋವು ಇದೆ. ದಯವಿಟ್ಟು ವೈದ್ಯರನ್ನು ತೋರಿಸಿ."
                        and card.get("audio_status") in {"ready", "demo_text_only"}
                    )
                    if not ok:
                        raise RuntimeError(f"Health demo missing expected card data: {body}")

                if path == "/api/state":
                    latest_state = body if isinstance(body, dict) else None
                    if not isinstance(latest_state, dict):
                        raise RuntimeError("State endpoint did not return JSON object")

                if path == "/api/reset":
                    cleared = body if isinstance(body, dict) else {}
                    ok = (
                        cleared.get("events") == []
                        and cleared.get("transcript") == []
                        and cleared.get("wage_complaint") is None
                        and cleared.get("health_card") is None
                    )
                    if not ok:
                        raise RuntimeError(f"Reset did not clear demo state: {body}")

                record(label, "PASS")
            except Exception as exc:
                record(label, "FAIL", str(exc))

        if latest_health_demo:
            card = latest_health_demo.get("health_card") or {}
            if card.get("audio_status") == "demo_text_only":
                record(
                    "Cartesia fallback",
                    "WARN",
                    "Cartesia keys are missing or TTS failed, but text-only hospital card fallback is working.",
                )

        if latest_state is None:
            record(
                "State shape",
                "WARN",
                "GET /api/state was not captured for extra validation.",
            )

    n_pass = sum(1 for _, status in results if status == "PASS")
    n_fail = sum(1 for _, status in results if status == "FAIL")
    n_warn = sum(1 for _, status in results if status == "WARN")
    print(f"\n{B}── summary ──{X}  {G}{n_pass} pass{X}  {Y}{n_warn} warn{X}  {R}{n_fail} fail{X}")

    if n_fail == 0:
        print(f"{G}READY TO RUN.{X}  Open /demo for the judge dashboard.\n")
        return 0

    print(f"{R}Not ready — fix the FAILs above.{X}\n")
    return 1


if __name__ == "__main__":
    sys.exit(main())
