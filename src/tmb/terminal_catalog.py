"""Read-only catalog refresh; no model completions, roster changes or paid jobs."""

import argparse
import json
import os
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

from tmb.terminal_guard import nano_usd


def prices(pricing):
    """Reserve the highest time-of-day rate and never assume cache discounts."""
    options = [pricing, *pricing.get("overrides", [])]
    result = {}
    for source, target in (("prompt", "input_per_million"), ("completion", "output_per_million")):
        values = [Decimal(str(p.get(source, pricing[source]))) for p in options]
        for value in values:
            nano_usd(value)
        result[target] = str(max(values) * 1_000_000)
    # Request/image/audio charges are outside this text-only reservation model.
    for key in ("request", "image", "web_search", "internal_reasoning", "input_audio", "output_audio"):
        if any(Decimal(str(p.get(key, 0))) != 0 for p in options):
            raise ValueError("Unsupported extra billing dimension")
    return result


def inspect_routes(routes, catalogs, checked_at):
    refreshed = []
    for route in routes:
        row = {"name": route["name"], "model": route["model"], "provider": route["provider"]}
        if route.get("provider"):
            candidates = [
                e
                for e in catalogs[route["model"]]["data"]["endpoints"]
                if e.get("tag") == route["provider"] and e.get("status", 0) == 0
            ]
        else:
            candidates = [e for e in catalogs["netra"]["data"] if e.get("id") == route["model"]]
        if not candidates:
            refreshed.append({**row, "status": "missing_from_current_catalog"})
            continue
        # Multiple regional listings for a pinned provider use the maximum rates.
        quotes = [prices(e["pricing"]) for e in candidates]
        current = {key: str(max(Decimal(q[key]) for q in quotes)) for key in quotes[0]}
        providers = {e.get("provider_name") for e in candidates}
        if route.get("provider") and (len(providers) != 1 or None in providers):
            raise ValueError("Ambiguous response provider metadata")
        refreshed.append(
            {
                **route,
                **current,
                "status": "catalog_only_live_route_unverified",
                "price_checked_at_utc": checked_at,
                "expected_response_provider": next(iter(providers)) if route.get("provider") else None,
                "price_source": route["price_source"]
                if route.get("provider")
                else "https://api.netraruntime.com/v1/models",
                "price_changed": any(
                    Decimal(str(route[k])).quantize(Decimal("0.000000001"))
                    != Decimal(current[k]).quantize(Decimal("0.000000001"))
                    for k in current
                ),
            }
        )
    return {
        "checked_at_utc": checked_at,
        "status": "not_ready_for_collection",
        "paid_requests": 0,
        "routes": refreshed,
        "remaining_gates": [
            "Linux runner and fees",
            "OpenRouter credential",
            "full roster availability",
            "resource screening",
            "disjoint pilot",
            "final budget and preregistration",
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    routes = json.loads(args.routes.read_text(encoding="utf-8"))["routes"]
    catalogs = {}
    with httpx.Client(timeout=30, follow_redirects=False, trust_env=False) as client:
        for model in sorted({r["model"] for r in routes}):
            response = client.get("https://openrouter.ai/api/v1/models/" + model + "/endpoints")
            response.raise_for_status()
            catalogs[model] = response.json()
        key = os.environ.get("NETRA_API_KEY")
        if not key:
            parser.error("NETRA_API_KEY is required for the read-only Netra price catalog")
        response = client.get(
            "https://api.netraruntime.com/v1/models", headers={"Authorization": "Bearer " + key}
        )
        response.raise_for_status()
        catalogs["netra"] = response.json()
    report = inspect_routes(routes, catalogs, datetime.now(UTC).isoformat())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "paid_requests": 0,
                "missing": [
                    {"model": r["model"], "provider": r["provider"]}
                    for r in report["routes"]
                    if r["status"] == "missing_from_current_catalog"
                ],
            }
        )
    )


if __name__ == "__main__":
    main()
