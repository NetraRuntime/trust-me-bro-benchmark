"""Offline Terminal-Bench sampling and cost scenarios; never starts paid jobs."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def build_plan(inventory, routes, *, task_count, repeats=3, cpu_only=True, seed=20260928):
    if type(task_count) is not int or task_count < 1 or type(repeats) is not int or repeats < 1:
        raise ValueError("task_count and repeats must be positive integers")
    tasks = inventory["tasks"]
    if len({task["name"] for task in tasks}) != len(tasks):
        raise ValueError("Duplicate task names")
    keys = [(route["model"], route["name"]) for route in routes]
    if not keys or len(set(keys)) != len(keys):
        raise ValueError("Routes must be nonempty and unique within a model")
    for route in routes:
        for key in ("input_per_million", "output_per_million"):
            value = route[key]
            if isinstance(value, bool) or not math.isfinite(value) or value < 0:
                raise ValueError("Prices must be finite and nonnegative")
    eligible = []
    excluded = []
    for task in tasks:
        envs = [task["environment"], task["verifier"].get("environment", {})]
        if cpu_only and any(env.get("gpus", 0) > 0 for env in envs):
            excluded.append(task["name"])
        else:
            eligible.append(task["name"])
    if task_count > len(eligible):
        raise ValueError("Not enough eligible tasks")
    ordered = sorted(eligible, key=lambda name: hashlib.sha256(f"{seed}:{name}".encode()).hexdigest())
    selected = ordered[:task_count]
    scenarios = []
    # Totals across ALL requests in one episode, including retransmitted history.
    for name, input_tokens, output_tokens in (
        ("short", 100_000, 20_000),
        ("medium", 1_000_000, 100_000),
        ("long", 5_000_000, 500_000),
    ):
        by_model = {}
        for route in routes:
            cost = (
                task_count
                * repeats
                * (input_tokens * route["input_per_million"] + output_tokens * route["output_per_million"])
                / 1_000_000
            )
            by_model[route["model"]] = by_model.get(route["model"], 0) + cost
        scenarios.append(
            {
                "name": name,
                "input_tokens_per_episode": input_tokens,
                "output_tokens_per_episode": output_tokens,
                "api_usd_by_model": {key: round(value, 6) for key, value in by_model.items()},
                "api_usd_total": round(sum(by_model.values()), 6),
            }
        )
    return {
        "status": "planning_only_not_preregistered_not_executed",
        "dataset_revision": inventory["revision"],
        "selection_seed": seed,
        "cpu_only": cpu_only,
        "eligible_count": len(eligible),
        "excluded_gpu_tasks": sorted(excluded),
        "selected_tasks": selected,
        "unselected_eligible_tasks": ordered[task_count:],
        "repeats": repeats,
        "route_count": len(routes),
        "episodes": task_count * repeats * len(routes),
        "cost_scenarios": scenarios,
        "cost_warning": (
            "Scenarios, not measured predictions or spending caps. Excludes sandbox charges, "
            "pilot, taxes, unknown failure billing and fees; assumes no cache discounts. "
            "Freeze a task manifest, dependency lock, pilot and budget enforcement before execution."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--routes", type=Path, required=True)
    parser.add_argument("--tasks", type=int, required=True)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--include-gpu", action="store_true")
    args = parser.parse_args()
    plan = build_plan(
        json.loads(args.inventory.read_text(encoding="utf-8")),
        json.loads(args.routes.read_text(encoding="utf-8"))["routes"],
        task_count=args.tasks,
        repeats=args.repeats,
        cpu_only=not args.include_gpu,
    )
    print(json.dumps(plan, indent=2))


if __name__ == "__main__":
    main()
