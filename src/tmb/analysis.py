"""Offline analysis derived exclusively from the saved run manifest."""

from collections import Counter
from itertools import combinations

from .statistics import holm, jsd, mmd2, permutation_test

LIMITATIONS = (
    "Behavioral evidence only; no identity proof. No difference detected is not equivalence. "
    "Power is uncalibrated for real providers; exact-string tests can miss changes in diverse outputs. "
    "Capitalization or formatting alone can also produce a detectable difference. "
    "Independence, hidden instructions, serving configuration and control compliance are unverified."
)


def analyze(run):
    cfg = run["config"]
    names = [e["name"] for e in cfg["endpoints"]]
    settings = cfg["sampling"]
    levels = {}
    for level in range(min(run["level"], 3) + 1):
        probes = [p for p in run["probes"] if p["level"] == level]
        pairs = []
        for left, right in combinations(names, 2):
            pair = {
                "left": left,
                "right": right,
                "verdict": "inconclusive",
                "effect_size": None,
                "uncertainty": "Not estimated; see sample counts and reason. Split halves are descriptive only.",
                "limitations": LIMITATIONS,
                "observations": [],
                "sample_counts": {},
                "status": "complete",
            }
            groups = []
            complete = True
            for p in probes:
                rows = [
                    [r for r in run["requests"] if r["endpoint"] == e and r["probe"] == p["id"]]
                    for e in (left, right)
                ]
                samples = [[r["answer_hash"] for r in rr if r["status"] == "ok"] for rr in rows]
                expected = int(settings["repeats"][str(level)])
                complete &= all(len(s) == expected for s in samples)
                pair["sample_counts"][p["id"]] = [len(s) for s in samples]
                a, b = samples
                obs = {
                    "probe": p["id"],
                    "counts": [dict(Counter(s)) for s in samples],
                    "request_statuses": [dict(Counter(r["status"] for r in rr)) for rr in rows],
                    "jsd_bits": jsd(a, b),
                    "split_half_jsd_bits": [jsd(s[::2], s[1::2]) for s in samples],
                }
                if level == 3 and min(len(a), len(b)) >= 2:
                    obs["mmd2"] = mmd2(a, b)
                    obs["contribution_to_mean_mmd2"] = obs["mmd2"] / len(probes)
                if a and b:
                    obs["cross_sample_disagreement_rate"] = 1 - sum(
                        v * Counter(b)[k] for k, v in Counter(a).items()
                    ) / (len(a) * len(b))
                    obs["representatives"] = [
                        {
                            "endpoint": r["endpoint"],
                            "answer_hash": r.get("answer_hash"),
                            "text": r.get("text"),
                        }
                        for rr in rows
                        for r in rr[:2]
                    ]
                    disagreement = next(
                        (
                            (x, y)
                            for x in rows[0]
                            for y in rows[1]
                            if x["status"] == y["status"] == "ok" and x["answer_hash"] != y["answer_hash"]
                        ),
                        None,
                    )
                    if disagreement:
                        obs["representative_disagreement"] = [
                            {
                                "endpoint": r["endpoint"],
                                "answer_hash": r["answer_hash"],
                                "text": r.get("text"),
                            }
                            for r in disagreement
                        ]
                pair["observations"].append(obs)
                groups.append((a, b))
            if not complete:
                pair.update(
                    status="incomplete", reason="Missing, failed, cached, empty, refused or truncated samples"
                )
            elif level == 0:
                pair.update(
                    verdict="setup recorded", reason="API accepted requests; control compliance is unverified"
                )
            elif level in (1, 2):
                pair.update(
                    verdict="descriptive only",
                    effect_size=sum(jsd(a, b) for a, b in groups) / len(groups),
                    effect_name="mean empirical JSD in bits",
                    reason="No calibrated identity threshold; split halves describe baseline variability",
                )
            elif any(min(len(a), len(b)) < settings["min_samples"] for a, b in groups):
                pair.update(status="insufficient_samples", reason="Below configured minimum per prompt")
            elif all(len(set(a + b)) == len(a + b) for a, b in groups):
                pair.update(
                    status="uninformative_kernel",
                    reason="No string collisions; exact-match kernel has no observed signal",
                )
            else:
                pair.update(
                    permutation_test(
                        groups, settings["permutations"], settings["bootstrap"], settings["random_seed"]
                    )
                )
                absolute_total = sum(abs(o["mmd2"]) for o in pair["observations"])
                pair["signal_diagnostic"] = {
                    "largest_absolute_contributor": max(
                        pair["observations"], key=lambda o: abs(o["mmd2"])
                    )["probe"] if absolute_total else None,
                    "largest_absolute_share": (
                        max(abs(o["mmd2"]) for o in pair["observations"]) / absolute_total
                        if absolute_total else None
                    ),
                    "interpretation": (
                        "Descriptive attribution, not a per-probe significance test. "
                        "Inspect whether one task or formatting choice drives the result. "
                        "Negative unbiased contributions are retained."
                    ),
                }
            pairs.append(pair)
            endpoints = {e["name"]: e for e in cfg["endpoints"]}
            pair["comparison_kind"] = (
                "different-model control"
                if any(endpoints[e].get("role") == "different_model_control" for e in (left, right))
                else "claimed-checkpoint comparison"
            )
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
            differences = [k for k in fields if endpoints[left].get(k) != endpoints[right].get(k)]
            pair["comparability"] = (
                "limited: hidden/unknown settings" if not differences else "known configuration differences"
            )
            pair["known_differences"] = differences
        if level == 3:
            adjusted = holm([p.get("p_value", 1) for p in pairs])
            for p, adj in zip(pairs, adjusted):
                p["correction"] = (
                    f"Holm FWER across all {len(pairs)} planned pairs; untestable pairs count as p=1"
                )
                if "p_value" in p:
                    p["adjusted_p_value"] = adj
                    if len(pairs) / (settings["permutations"] + 1) > settings["alpha"]:
                        p.update(verdict="inconclusive", status="insufficient_permutation_resolution")
                    else:
                        p["verdict"] = (
                            "detectably different" if adj <= settings["alpha"] else "no difference detected"
                        )
        levels[str(level)] = {"pairs": pairs, "matrix": matrix(names, pairs)}
    reference = run.get("reference_designation", {}).get("endpoint") or cfg.get("reference")
    if run["level"] == 4:
        reference_pairs = []
        if reference:
            for pair in levels["3"]["pairs"]:
                if reference in (pair["left"], pair["right"]):
                    p = dict(pair)
                    if p["known_differences"]:
                        p.update(
                            verdict="inconclusive",
                            reason="Reference conditions have known mismatches; see level 3",
                        )
                    elif (
                        p["verdict"] == "no difference detected"
                        and p["comparison_kind"] != "different-model control"
                    ):
                        p["verdict"] = (
                            "consistent with reference under this protocol (no difference detected)"
                            if run.get("tool_version") == "0.1.0"
                            else "no difference detected against designated reference"
                        )
                    reference_pairs.append(p)
        levels["4"] = {
            "status": "reuses level-3 samples and correction"
            if reference
            else "skipped: no designated reference",
            "reference": reference,
            "trust": "User-designated; not independently certified",
            "pairs": reference_pairs,
            "matrix": matrix(names, reference_pairs),
        }
    return levels


def matrix(names, pairs):
    output = {a: {b: "self" if a == b else "not applicable" for b in names} for a in names}
    for p in pairs:
        output[p["left"]][p["right"]] = output[p["right"]][p["left"]] = p["verdict"]
    return output
