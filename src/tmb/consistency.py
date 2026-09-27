"""Predeclared practical tolerance on paired excess answer disagreement.

Question clusters, not cross-response pairs, are the resampling units. Intervals
are approximate bootstrap intervals; this observable is not a distribution metric.
"""

from itertools import combinations

import numpy as np

from .choice_analysis import cluster_indices
from .report import cell


def analyze_consistency(run):
    protocol = run["protocol"]
    spec = protocol["consistency"]
    if spec["method"] != "paired-disagreement-bootstrap-v1":
        raise ValueError("Unsupported consistency method")
    names = [e["name"] for e in run["config"]["endpoints"]]
    endpoints = {e["name"]: e for e in run["config"]["endpoints"]}
    items = run["items"]
    n = protocol["repeats"]
    baseline = tuple(spec["baseline"])
    samples = {(name, i["id"]): {} for name in names for i in items}
    for row in run["requests"]:
        target = samples[row["endpoint"], row["question_id"]]
        repeat = row["repeat"]
        if repeat not in range(n) or repeat in target:
            raise ValueError("Duplicate or out-of-range sample in consistency analysis")
        item = next(i for i in items if i["id"] == row["question_id"])
        choice = row.get("choice")
        valid = row["status"] == "ok" and choice in list("ABCDEFGHIJ"[: item["option_count"]])
        target[repeat] = choice if valid else None

    def bounds(left, right):
        values = []
        for item in items:
            a = [x for x in samples[left, item["id"]].values() if x is not None]
            b = [x for x in samples[right, item["id"]].values() if x is not None]
            d = sum(x != y for x in a for y in b)
            values.append([d / n**2, (d + n**2 - len(a) * len(b)) / n**2])
        return np.asarray(values)

    missing = {
        name: 1
        - sum(x is not None for i in items for x in samples[name, i["id"]].values()) / (n * len(items))
        for name in names
    }
    base = bounds(*baseline)
    pairs = [p for p in combinations(names, 2) if set(p) != set(baseline)]
    tail = protocol["alpha"] / (2 * len(pairs))
    rng = np.random.default_rng(protocol["seed"])
    draws = cluster_indices([i["category"] for i in items], protocol["bootstrap"], rng)
    output = []
    for left, right in pairs:
        observed = bounds(left, right)
        lower = observed[:, 0] - base[:, 1]
        upper = observed[:, 1] - base[:, 0]
        interval = [
            float(np.quantile(lower[draws].mean(axis=1), tail)),
            float(np.quantile(upper[draws].mean(axis=1), 1 - tail)),
        ]
        reasons = []
        if run.get("remaining_requests", 0) or any(r["status"] == "in_flight" for r in run["requests"]):
            reasons.append("Collection is incomplete")
        involved = set(baseline) | {left, right}
        if len(items) < spec["min_questions"]:
            reasons.append("Too few question clusters for the predeclared protocol")
        if any(missing[name] > spec["max_missing_fraction"] + 1e-12 for name in involved):
            reasons.append("Missing-answer fraction exceeds the predeclared limit")
        if protocol["bootstrap"] * tail < 20:
            reasons.append("Insufficient bootstrap tail resolution")
        # A collapsed nonparametric bootstrap cannot quantify unseen variation.
        if np.ptp(lower) < 1e-12 and np.ptp(upper) < 1e-12:
            reasons.append("Degenerate question bootstrap; unseen variation is unquantified")
        fields = (
            "unsupported_controls",
            "reasoning_effort",
            "reasoning_enabled",
            "tokenizer",
            "chat_template",
            "checkpoint_revision",
            "quantization",
            "serving_software",
        )
        if any(len({str(endpoints[name].get(f)) for name in involved}) > 1 for f in fields):
            reasons.append("Known serving/control mismatch limits matched-condition attribution")
        candidate = "inconclusive"
        margin = spec["margin"]
        if not reasons:
            if interval[0] >= -margin and interval[1] <= margin:
                candidate = "within baseline tolerance"
            elif interval[0] > margin or interval[1] < -margin:
                candidate = "beyond baseline tolerance"
        output.append(
            {
                "left": left,
                "right": right,
                "kind": "different-model control"
                if any(endpoints[x]["role"] == "different_model_control" for x in (left, right))
                else "candidate",
                "verdict": candidate,
                "reasons": reasons,
                "questions": len(items),
                "planned_samples_per_endpoint": n * len(items),
                "valid_samples": [round((1 - missing[x]) * n * len(items)) for x in (left, right)],
                "disagreement_bounds": observed.mean(axis=0).tolist(),
                "excess_disagreement_bounds": [float(lower.mean()), float(upper.mean())],
                "approximate_simultaneous_interval": interval,
            }
        )
    # Sensitivity must be demonstrated against a baseline arm, not any arbitrary pair.
    controls = [
        p
        for p in output
        if p["kind"] == "different-model control" and ({p["left"], p["right"]} & set(baseline))
    ]
    sensitivity = any(
        p["verdict"] == "beyond baseline tolerance"
        and p["approximate_simultaneous_interval"][0] > spec["margin"]
        for p in controls
    )
    for pair in output:
        if pair["verdict"] == "within baseline tolerance" and not sensitivity:
            pair["verdict"] = "inconclusive"
            pair["reasons"].append("Different-model control did not demonstrate sensitivity")
    return {
        "method": spec["method"],
        "baseline": list(baseline),
        "baseline_disagreement_bounds": base.mean(axis=0).tolist(),
        "margin": spec["margin"],
        "family_alpha": protocol["alpha"],
        "correction": f"Bonferroni bootstrap tail allocation across {len(pairs)} planned contrasts",
        "missing_fraction": missing,
        "sensitivity_demonstrated": sensitivity,
        "pairs": output,
        "limitations": "Approximate subject-stratified question bootstrap, not finite-sample coverage guarantees. "
        "Equal disagreement rates can hide different answer distributions. Public probes, unknown controls, "
        "question dependence, drift and shared upstreams limit attribution. A tolerance result is not model identity or probability of authenticity.",
    }


def render_consistency(result):
    lines = [
        "",
        "## Practical consistency against repeat baseline",
        "",
        (f"Method: {result['method']}. Baseline: {cell(result['baseline'])}. "
        f"Predeclared excess-disagreement margin: ±{result['margin']:.1%}."),
        "",
        (f"{result['correction']}; family alpha={result['family_alpha']}. "
        f"Different-model sensitivity demonstrated: {result['sensitivity_demonstrated']}."),
        "",
        "Intervals incorporate worst-case missing answers and sampling uncertainty; bootstrap coverage is approximate.",
        "",
        "| Pair | Verdict | Excess disagreement bounds | Approximate simultaneous interval | Valid samples | Reasons |",
        "|---|---|---|---|---|---|",
    ]
    for p in result["pairs"]:
        lines.append(
            "| "
            + " | ".join(
                cell(x)
                for x in (
                    f"{p['left']} / {p['right']}",
                    p["verdict"],
                    p["excess_disagreement_bounds"],
                    p["approximate_simultaneous_interval"],
                    p["valid_samples"],
                    p["reasons"],
                )
            )
            + " |"
        )
    return "\n".join(lines + ["", result["limitations"], ""])
