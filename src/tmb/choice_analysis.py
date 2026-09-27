"""Question-stratified categorical tests; accuracy is a separate observable."""

from collections import Counter
from itertools import combinations

import numpy as np

from .report import cell
from .statistics import holm, mmd2

LIMIT = (
    "Parsed-choice behavior only, not weight identity. Public dataset contamination and selective routing are possible. "
    "Two to four repeats per question give limited power; non-rejection is not equivalence. "
    "Requested controls, independence and hidden serving conditions are unverified."
)


def cluster_indices(categories, draws, rng):
    groups = [np.flatnonzero(np.asarray(categories) == category) for category in sorted(set(categories))]
    return np.concatenate([rng.choice(g, (draws, len(g))) for g in groups], axis=1)


def categorical_test(groups, categories, permutations, bootstrap, seed):
    """Enumerate balanced label assignments per question, then sample their product null."""
    n = len(groups[0][0])
    if n not in (2, 3, 4) or any(len(a) != n or len(b) != n for a, b in groups):
        raise ValueError("Categorical test needs 2-4 balanced repeats per question")
    assignments = list(combinations(range(2 * n), n))
    scores = np.empty((len(groups), len(assignments)))
    observed = np.asarray([mmd2(a, b) for a, b in groups])
    for j, (a, b) in enumerate(groups):
        pooled = list(a) + list(b)
        for k, left in enumerate(assignments):
            scores[j, k] = mmd2([pooled[i] for i in left], [pooled[i] for i in range(2 * n) if i not in left])
    rng = np.random.default_rng(seed)
    # At most 2048 permutations in memory; RNG ordering is deterministic for this version.
    exceed = 0
    for start in range(0, permutations, 2048):
        indices = rng.integers(len(assignments), size=(min(2048, permutations - start), len(groups)))
        null = scores[np.arange(len(groups))[None, :], indices].mean(axis=1)
        exceed += int(np.count_nonzero(null >= observed.mean() - 1e-12))
    boot = observed[cluster_indices(categories, bootstrap, rng)].mean(axis=1)
    return {
        "effect_size": float(observed.mean()),
        "per_question_effect": observed.tolist(),
        "p_value": (1 + exceed) / (1 + permutations),
        "descriptive_interval_95": np.quantile(boot, [0.025, 0.975]).tolist(),
        "permutation_resolution": 1 / (1 + permutations),
    }


def analyze_choices(run):
    items = run["items"]
    endpoints = run["config"]["endpoints"]
    names = [e["name"] for e in endpoints]
    endpoint_map = {e["name"]: e for e in endpoints}
    protocol = run["protocol"]
    repeats = protocol["repeats"]
    categories = [i["category"] for i in items]
    rows = {(name, i["id"]): [] for name in names for i in items}
    for row in run["requests"]:
        rows[row["endpoint"], row["question_id"]].append(row)
    samples = {
        k: [
            r["choice"]
            for r in sorted(v, key=lambda r: r["repeat"])
            if r["status"] == "ok" and r.get("choice") is not None
        ]
        for k, v in rows.items()
    }
    rng = np.random.default_rng(protocol["seed"])
    ci_indices = cluster_indices(categories, protocol["bootstrap"], rng)
    scores = {}
    for name in names:
        correct = np.asarray([sum(a == i["answer"] for a in samples[name, i["id"]]) / repeats for i in items])
        count = sum(len(samples[name, i["id"]]) for i in items)
        planned = len(items) * repeats
        score = {
            "planned": planned,
            "valid": count,
            "coverage": count / planned,
            "observed_correct_over_planned": float(correct.mean()),
            "missing_answer_accuracy_bounds": [
                float(correct.mean()),
                float(correct.mean() + (planned - count) / planned),
            ],
            "pointwise_cluster_interval_95": np.quantile(
                correct[ci_indices].mean(axis=1), [0.025, 0.975]
            ).tolist(),
            "statuses": dict(Counter(r["status"] for r in run["requests"] if r["endpoint"] == name)),
            "by_category": {},
        }
        for category in sorted(set(categories)):
            selected = [i for i in items if i["category"] == category]
            score["by_category"][category] = {
                "correct": sum(a == i["answer"] for i in selected for a in samples[name, i["id"]]),
                "valid": sum(len(samples[name, i["id"]]) for i in selected),
                "planned": len(selected) * repeats,
            }
        scores[name] = score
    pairs = []
    for left, right in combinations(names, 2):
        groups = [(samples[left, i["id"]], samples[right, i["id"]]) for i in items]
        complete = all(len(a) == len(b) == repeats for a, b in groups)
        pair = {
            "left": left,
            "right": right,
            "verdict": "inconclusive",
            "complete": complete,
            "effect_size": None,
            "samples": [sum(len(a) for a, b in groups), sum(len(b) for a, b in groups)],
            "planned_per_endpoint": len(items) * repeats,
            "observations": [],
            "limitations": LIMIT,
        }
        pair["kind"] = (
            "same-configuration control"
            if {left, right} == set(protocol.get("same_configuration_pair") or [])
            else "different-model control"
            if any(e["name"] in (left, right) and e["role"] == "different_model_control" for e in endpoints)
            else "claimed-checkpoint comparison"
        )
        pair["known_configuration_differences"] = [
            field
            for field in (
                "unsupported_controls",
                "reasoning_effort",
                "reasoning_enabled",
                "tokenizer",
                "chat_template",
                "checkpoint_revision",
                "quantization",
                "serving_software",
            )
            if endpoint_map[left].get(field) != endpoint_map[right].get(field)
        ]
        disagreements = []
        differences = []
        for i, (a, b) in zip(items, groups):
            disagree = (
                1 - sum(Counter(a)[k] * Counter(b)[k] for k in set(a)) / (len(a) * len(b))
                if a and b
                else None
            )
            pair["observations"].append(
                {
                    "id": i["id"],
                    "category": i["category"],
                    "correct_answer": i["answer"],
                    "left": dict(Counter(a)),
                    "right": dict(Counter(b)),
                    "disagreement": disagree,
                }
            )
            if complete:
                disagreements.append(disagree)
                differences.append(
                    sum(x == i["answer"] for x in a) / repeats - sum(x == i["answer"] for x in b) / repeats
                )
        if complete:
            pair.update(
                categorical_test(
                    groups, categories, protocol["permutations"], protocol["bootstrap"], protocol["seed"]
                )
            )
            pair["mean_cross_sample_disagreement"] = float(np.mean(disagreements))
            pair["accuracy_difference_left_minus_right"] = float(np.mean(differences))
            pair["accuracy_difference_interval_95"] = np.quantile(
                np.asarray(differences)[ci_indices].mean(axis=1), [0.025, 0.975]
            ).tolist()
            pair["disagreement_interval_95"] = np.quantile(
                np.asarray(disagreements)[ci_indices].mean(axis=1), [0.025, 0.975]
            ).tolist()
        else:
            pair["reason"] = (
                "Missing, invalid, failed, truncated or cached answers: no complete-protocol inference"
            )
        pairs.append(pair)
    for pair, adjusted in zip(pairs, holm([p.get("p_value", 1) for p in pairs])):
        if pair["complete"]:
            pair["adjusted_p_value"] = adjusted
            pair["verdict"] = (
                "detectably different" if adjusted <= protocol["alpha"] else "no difference detected"
            )
            if len(pairs) / (protocol["permutations"] + 1) > protocol["alpha"]:
                pair["verdict"] = "inconclusive"
                pair["reason"] = "Insufficient permutation resolution for the planned family"
    return {
        "scores": scores,
        "pairs": pairs,
        "correction": f"Holm FWER across all {len(pairs)} planned pairs",
    }


def render_choices(run):
    from .dataset_diagnostics import disagreement_bounds

    analysis = run["analysis"]
    names = list(analysis["scores"])
    lines = [
        "# Dataset comparison: MMLU-Pro answer choices",
        "",
        LIMIT,
        "",
        "This is a balanced, zero-shot direct-answer subset, not an official MMLU-Pro leaderboard score.",
        "",
        f"Run: {run['run_id']}. Window: {run['started_at']} to {run['updated_at']}.",
        "",
        f"Dataset revision: {run['dataset']['revision']}; subset hash: {run['dataset']['content_hash']}.",
        "",
        (
            f"Questions: {len(run['items'])}; subjects: {len({i['category'] for i in run['items']})}. "
            f"Repeats: {run['protocol']['repeats']}. Request statuses: {cell(run['request_counts'])}."
        ),
        "",
        f"Remaining requests: {run['remaining_requests']}. Stop reason: {cell(run.get('stop_reason', 'completed'))}.",
        "",
        (
            f"Estimated known-usage subtotal USD: {run['known_cost_usd']}; requests missing usage: {run['missing_usage']}. "
            "This is not a billing receipt. Spend and latency are outside behavioral scores."
        ),
        "",
        "## Accuracy and coverage",
        "",
        "| Endpoint | Correct / planned | Pointwise 95% interval | Valid / planned | Statuses |",
        "|---|---:|---|---:|---|",
    ]
    for name, score in analysis["scores"].items():
        lines.append(
            f"| {cell(name)} | {score['observed_correct_over_planned']:.1%} | "
            f"{cell(score['pointwise_cluster_interval_95'])} | {score['valid']}/{score['planned']} | {cell(score['statuses'])} |"
        )
    lines += [
        "",
        (
            "Accuracy intervals resample whole questions within subjects, retaining repeats together; they are pointwise and descriptive. "
            "Missing/invalid answers count as not correct in observed correct/planned, not as established model errors. "
            "JSON includes worst/best bounds for missing answers. No accuracy-derived identity verdict."
        ),
        "",
        "## Answer agreement with missing-answer bounds",
        "",
        (
            "These descriptive bounds allow every missing cross-response comparison to agree or disagree. "
            "They describe the planned finite sample, not population confidence or identity. "
            "They supplement, and do not replace, the frozen statistical procedure."
        ),
        "",
        "| Pair | Agreement lower bound | Agreement upper bound | Observed / planned cross-response comparisons |",
        "|---|---:|---:|---:|",
    ]
    for bound in disagreement_bounds(run):
        lo, hi = bound["agreement_bounds"]
        lines.append(
            f"| {cell(bound['left'])} / {cell(bound['right'])} | {lo:.1%} | {hi:.1%} | "
            f"{bound['observed_cross_response_pairs']}/{bound['planned_cross_response_pairs']} |"
        )
    lines += [
        "",
        "## Answer-distribution comparison",
        "",
        (
            "Null: equal parsed-choice distributions for every sampled question under requested controls. "
            "Statistic: mean unbiased categorical MMD squared; labels permuted only within questions. "
            f"{analysis['correction']}; alpha {run['protocol']['alpha']}; {run['protocol']['permutations']} permutations. "
            "Untestable pairs count as p=1. Negative unbiased estimates are legitimate."
        ),
        "",
        "| Endpoint | " + " | ".join(map(cell, names)) + " |",
        "|---|" + "---|" * len(names),
    ]
    lookup = {frozenset((p["left"], p["right"])): p for p in analysis["pairs"]}
    for name in names:
        lines.append(
            "| "
            + cell(name)
            + " | "
            + " | ".join(
                "self" if name == other else lookup[frozenset((name, other))]["verdict"] for other in names
            )
            + " |"
        )
    lines += [
        "",
        "| Pair | Kind | Samples | MMD squared | Adjusted p | Descriptive 95% MMD interval | Answer disagreement | Accuracy gap (left minus right) |",
        "|---|---|---|---:|---:|---|---:|---:|",
    ]
    for p in analysis["pairs"]:
        lines.append(
            "| "
            + " | ".join(
                cell(x)
                for x in [
                    f"{p['left']} / {p['right']}",
                    p["kind"],
                    p["samples"],
                    p.get("effect_size"),
                    p.get("adjusted_p_value"),
                    p.get("descriptive_interval_95"),
                    p.get("mean_cross_sample_disagreement"),
                    p.get("accuracy_difference_left_minus_right"),
                ]
            )
            + " |"
        )
    lines += [
        "",
        (
            "MMD intervals are descriptive, not calibrated near the null. JSON also provides disagreement and paired accuracy-gap intervals. "
            "Incomplete pairs have no inferential verdict. A single repeat control diagnoses this run; it does not estimate a general false-positive rate."
        ),
        "",
        "## Accuracy by subject",
        "",
        "| Subject | " + " | ".join(map(cell, names)) + " |",
        "|---|" + "---|" * len(names),
    ]
    for category in sorted({i["category"] for i in run["items"]}):
        lines.append(
            "| "
            + cell(category)
            + " | "
            + " | ".join(
                f"{analysis['scores'][name]['by_category'][category]['correct']}/{analysis['scores'][name]['by_category'][category]['planned']}"
                for name in names
            )
            + " |"
        )
    reference = run["config"].get("reference")
    lines += [
        "",
        f"## Designated reference: {cell(reference)}",
        "",
        (
            "User-designated, not independently certified. "
            "Reference conclusions reuse the same samples and corrected tests, not an additional identity proof."
        ),
        "",
    ]
    for p in analysis["pairs"]:
        if reference in (p["left"], p["right"]):
            wording = p["verdict"]
            if p["known_configuration_differences"]:
                wording = "inconclusive for matched-reference attribution: known configuration differences"
            elif wording == "no difference detected" and p["kind"] != "different-model control":
                wording = "consistent with reference under this protocol (no difference detected)"
            lines.append(f"- {cell(p['left'])} / {cell(p['right'])}: {wording}.")
    lines += [
        "",
        "## Per-question evidence",
        "",
        (
            "Each table shows all disagreements or missing answers for that pair; question IDs refer to the pinned dataset. "
            "The JSON retains every item, including agreements."
        ),
        "",
    ]
    for p in analysis["pairs"]:
        lines += [
            f"<details><summary>{cell(p['left'])} / {cell(p['right'])}</summary>",
            "",
            "| Question | Subject | Gold | Left choices | Right choices |",
            "|---|---|---|---|---|",
        ]
        for o in p["observations"]:
            if o["disagreement"] != 0:
                lines.append(
                    "| "
                    + " | ".join(cell(o[k]) for k in ("id", "category", "correct_answer", "left", "right"))
                    + " |"
                )
        lines += ["", "</details>", ""]
    lines += [
        "## Reproduce",
        "",
        (
            "`tmb report PATH/run.json` recomputes this analysis offline from parsed choices. "
            "The frozen dataset file is needed to recollect prompts. Parsing is versioned; raw text is optional. "
            "See docs/dataset-protocol.md for departures from published methods and interpretation."
        ),
        "",
    ]
    lines += [
        "## Operational metadata",
        "",
        "| Endpoint | Requested model | Pinned provider | Returned model IDs | Mean latency seconds |",
        "|---|---|---|---|---:|",
    ]
    for endpoint in run["config"]["endpoints"]:
        rows = [r for r in run["requests"] if r["endpoint"] == endpoint["name"]]
        latencies = [r["latency_seconds"] for r in rows if "latency_seconds" in r]
        lines.append(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    endpoint["name"],
                    endpoint["model"],
                    endpoint.get("provider"),
                    sorted({r["returned_model"] for r in rows if r.get("returned_model")}),
                    sum(latencies) / len(latencies) if latencies else None,
                )
            )
            + " |"
        )
    totals = {
        k: sum((r.get("usage") or {}).get(k, 0) for r in run["requests"])
        for k in ("prompt_tokens", "completion_tokens")
    }
    lines += [
        "",
        f"Reported token totals (partial if usage is missing): {cell(totals)}.",
        "",
        (
            f"Requested temperature: {run['config']['sampling']['temperature']}; "
            f"top-p: {run['config']['sampling']['top_p']}; seed: {cell(run['config']['sampling']['request_seed'])}. "
            "Per-endpoint controls, metadata, failures and source provenance are retained in run.json."
        ),
        "",
    ]
    return "\n".join(lines)
