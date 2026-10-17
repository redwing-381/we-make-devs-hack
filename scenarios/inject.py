"""Replay a demo act's events without astro-mini: baseline telemetry, the bad deploy, then the alerts.

    uv run python scenarios/inject.py act1              # against http://localhost:8000
    uv run python scenarios/inject.py act3 --api URL
    uv run python scenarios/inject.py act1 --dry-run    # print the payloads only

Values match docs/work-split.md §2. Act 2 is prevention (the SDE agent calls MCP check_change_risk before it
ships), so it has nothing to inject here.
"""

import argparse
import json
import sys
import time

import httpx

from whygraph.models.events import AlertIn, DeployIn, TelemetryIn

REPO = "redwing-381/astro-mini"
# callee-side p99 per call edge (ms), from the latency model in astro-mini/config/services.yaml
BASELINE = [
    ("frontend", "checkout", 700.0),
    ("frontend", "cart", 25.0),
    ("frontend", "currency", 17.0),
    ("frontend", "shipping", 330.0),
    ("frontend", "product-catalog", 150.0),
    ("frontend", "recommendation", 190.0),
    ("checkout", "payment", 450.0),
    ("checkout", "cart", 25.0),
    ("checkout", "currency", 17.0),
    ("checkout", "product-catalog", 150.0),
    ("checkout", "shipping", 330.0),
    ("shipping", "quote", 300.0),
    ("recommendation", "product-catalog", 150.0),
]

ACTS = {
    "act1": {
        "sha": "9f2c1ab4d1e07c3a",
        "pr": 12,
        "author": "coder-bot",
        "message": "Reduce checkout latency: lower payment timeout",
        "change": {"service": "checkout", "key": "timeouts_ms.payment", "old": 800, "new": 200},
        "alerts": [("checkout", 0.62), ("frontend", 0.41)],
    },
    "act3": {
        "sha": "4be81d0c93aa7f21",
        "pr": 16,
        "author": "arjun",
        "message": "Speed up product page: lower catalog timeout (override PR Guard)",
        "change": {"service": "recommendation", "key": "timeouts_ms.product-catalog", "old": 400, "new": 80},
        "alerts": [("recommendation", 0.71), ("frontend", 0.22)],
    },
}


def payloads(act: str, now_ms: int) -> list[tuple[str, dict]]:
    a = ACTS[act]
    deploy_ts = now_ms - 3 * 60_000  # the deploy lands 3 minutes before the alerts
    telemetry = TelemetryIn(
        ts=deploy_ts - 60_000,
        edges=[{"caller": c, "callee": d, "p99_ms": p, "error_rate": 0.0} for c, d, p in BASELINE],
    )
    deploy = DeployIn(
        sha=a["sha"],
        repo=REPO,
        services=[a["change"]["service"]],
        ts=deploy_ts,
        pr_number=a["pr"],
        author=a["author"],
        message=a["message"],
        config_changes=[a["change"]],
    )
    alerts = [
        AlertIn(
            id=f"{act}-{service}-{now_ms}",
            service=service,
            signal="error_rate",
            value=value,
            threshold=0.10,
            severity="sev2",
            ts=now_ms + i * 4000,
            source="inject",
        )
        for i, (service, value) in enumerate(a["alerts"])
    ]
    return [("/api/telemetry", telemetry.model_dump()), ("/api/deploys", deploy.model_dump())] + [
        ("/api/alerts", x.model_dump()) for x in alerts
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("act", choices=[*ACTS, "act2"])
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.act == "act2":
        print(
            "Act 2 is prevention: the SDE agent calls the MCP tool check_change_risk before opening its PR."
        )
        return 0

    steps = payloads(args.act, int(time.time() * 1000))
    if args.dry_run:
        for path, body in steps:
            print(f"POST {path}\n{json.dumps(body, indent=2)}\n")
        return 0

    with httpx.Client(base_url=args.api, timeout=10) as http:
        for path, body in steps:
            r = http.post(path, json=body)
            r.raise_for_status()
            print(f"POST {path:16} {r.status_code} {r.json()}")
    incident = r.json().get("incident_id")
    if incident:
        print(f"\nWatch it: {args.api}/api/incidents/{incident}/stream")
    return 0


if __name__ == "__main__":
    sys.exit(main())
