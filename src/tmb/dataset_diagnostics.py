"""Descriptive finite-sample bounds; no extra tests or replacement verdicts."""

from itertools import combinations

from .validation import validate_observations


def disagreement_bounds(run):
    validate_observations(run, dataset=True, require_gold=False)
    repeats = run["protocol"]["repeats"]
    names = [e["name"] for e in run["config"]["endpoints"]]
    samples = {(name, item["id"]): [] for name in names for item in run["items"]}
    for row in run["requests"]:
        if row["status"] == "ok" and row.get("choice") is not None:
            samples[row["endpoint"], row["question_id"]].append(row["choice"])
    output = []
    total = len(run["items"]) * repeats * repeats
    for left, right in combinations(names, 2):
        observed = disagreements = 0
        for item in run["items"]:
            a, b = samples[left, item["id"]], samples[right, item["id"]]
            observed += len(a) * len(b)
            disagreements += sum(x != y for x in a for y in b)
        missing = total - observed
        output.append(
            {
                "left": left,
                "right": right,
                "observed_cross_response_pairs": observed,
                "planned_cross_response_pairs": total,
                "disagreement_on_available_pairs": disagreements / observed if observed else None,
                "disagreement_bounds": [disagreements / total, (disagreements + missing) / total],
                "agreement_bounds": [(observed - disagreements) / total, (total - disagreements) / total],
                "interpretation": (
                    "Conservative bounds for the planned finite sample: every unobserved comparison could agree or disagree. "
                    "These are not population confidence intervals, independent trials, or identity verdicts. "
                    "Available-pair rates can be biased by nonrandom missingness."
                ),
            }
        )
    return output
