"""Prespecified API-outcome supplement: parsed choice or observed failure status.

This observable includes delivery and formatting behavior. It is not an
answer-only test and cannot identify differences in model weights.
"""

from itertools import combinations

from .choice_analysis import categorical_test
from .statistics import holm
from .validation import sampling_issue, validate_observations

METHOD = "choice-or-failure-status-mmd-v1"
INVALIDATING_STATUSES = {
    "in_flight", "interrupted_unknown", "adapter_error_unknown",
    "missing_api_key", "cache_suspected",
}


def analyze_outcomes(run):
    validate_observations(run, dataset=True)
    names = [e["name"] for e in run["config"]["endpoints"]]
    items, protocol = run["items"], run["protocol"]
    rows = {(name, item["id"]): [] for name in names for item in items}
    for row in run["requests"]:
        rows[row["endpoint"], row["question_id"]].append(row)
    pairs = []
    for left, right in combinations(names, 2):
        involved = [r for r in run["requests"] if r["endpoint"] in (left, right)]
        complete = all(len(rows[name, item["id"]]) == protocol["repeats"]
                       for name in (left, right) for item in items)
        reason = sampling_issue(run)
        if not complete:
            reason = "Required attempts were not all recorded"
        elif any(r["status"] in INVALIDATING_STATUSES for r in involved):
            reason = "Unknown delivery, local setup failure or suspected cached completion invalidates inference"
        elif any(r.get("http_status") in (401, 402) for r in involved):
            reason = "Authentication or account-credit failure invalidates provider attribution"
        pair = {"left": left, "right": right, "complete": complete,
                "verdict": "inconclusive", "reason": reason}
        if not reason:
            groups = []
            for item in items:
                group = []
                for name in (left, right):
                    group.append([
                        "choice:" + r["choice"] if r["status"] == "ok" else "status:" + r["status"]
                        for r in sorted(rows[name, item["id"]], key=lambda r: r["repeat"])
                    ])
                groups.append(group)
            pair.update(categorical_test(groups, [i["category"] for i in items],
                                         protocol["permutations"], protocol["bootstrap"], protocol["seed"]))
        pairs.append(pair)
    for pair, adjusted in zip(pairs, holm([p.get("p_value", 1) for p in pairs])):
        if "p_value" in pair:
            pair["adjusted_p_value"] = adjusted
            pair["verdict"] = "detectably different API outcomes" if adjusted <= protocol["alpha"] else "no API-outcome difference detected"
            if len(pairs) / (protocol["permutations"] + 1) > protocol["alpha"]:
                pair.update(verdict="inconclusive", reason="Insufficient permutation resolution")
    return {"method": METHOD, "pairs": pairs,
            "correction": f"Holm across {len(pairs)} planned outcome pairs; combine families when reporting multiple tests",
            "limitations": "Includes HTTP/transport/timeout, refusal, truncation and parsing behavior. "
            "A significant result may reflect availability or format rather than answer content. "
            "API control compliance, temporal exchangeability and independence remain assumptions."}
