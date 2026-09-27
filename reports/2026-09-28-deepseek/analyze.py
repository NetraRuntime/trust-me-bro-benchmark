"""Reproduce the campaign reports offline from reviewed public evidence.

Run from the repository root after installing the package:
    python reports/2026-09-28-deepseek/analyze.py
"""

import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

import numpy as np

from tmb.choice_analysis import analyze_choices
from tmb.config import load_config
from tmb.dataset_diagnostics import disagreement_bounds
from tmb.datasets import load_dataset
from tmb.outcomes import analyze_outcomes
from tmb.statistics import holm
from tmb.validation import validate_manifest

ROOT = Path(__file__).resolve().parent
LABELS = {
    "dekallm": "DekaLLM",
    "deepinfra": "DeepInfra",
    "deepinfra_repeat": "DeepInfra repeat",
    "novita": "Novita",
    "fireworks": "Fireworks",
    "together": "Together",
    "parasail": "Parasail",
    "netra": "Netra",
    "coreweave": "CoreWeave",
    "nebius": "Nebius",
}
TITLES = {"deepseek-v4.1-flash": "DeepSeek V4.1 Flash", "deepseek-v4-flash-0731": "DeepSeek V4 Flash 0731"}


def number(value, digits=4):
    return "—" if value is None else f"{value:.{digits}f}"


def percent(value):
    return f"{value:.2%}"


def provenance_issues(run):
    """Do not attribute a comparison to a route its response metadata contradicts."""
    issues = {}
    for endpoint in run["config"]["endpoints"]:
        rows = [
            r for r in run["requests"] if r["endpoint"] == endpoint["name"] and r.get("http_status") == 200
        ]
        expected_provider = LABELS[endpoint["name"]].replace(" repeat", "")
        bad = [
            r
            for r in rows
            if r.get("returned_model") != endpoint["model"]
            or (endpoint["provider"] and r.get("provider") != expected_provider)
        ]
        if bad:
            issues[endpoint["name"]] = (
                f"{len(bad)} responses have missing or unexpected model/provider metadata"
            )
    return issues


def analyze(runs):
    protocol = json.loads((ROOT / "protocol.json").read_text(encoding="utf8"))
    dataset = load_dataset(ROOT / "dataset.json")
    studies, family = {}, []
    for slug, run in runs.items():
        validation = validate_manifest(run, dataset)
        assert run["dataset"]["content_hash"] == protocol["dataset_hash"]
        plan = next(p for p in protocol["plans"] if p["model"] == run["config"]["claimed_model"])
        expected_config = load_config(ROOT / plan["config"]).model_dump(mode="json")
        if expected_config.get("consistency") is None:
            expected_config.pop("consistency", None)
        assert run["config"] == expected_config, "Collection differs from the published configuration"
        assert run["tool_version"] == "0.3.0" and not run["store_text"]
        assert run["protocol"]["repeats"] == plan["repeats"]
        assert run["protocol"]["workers"] == plan["workers"]
        assert run["protocol"]["same_configuration_pair"] == plan["repeat_control"]
        assert len(run["requests"]) == plan["reservation"]["requests"] and not run["remaining_requests"]
        primary, outcomes = analyze_choices(run), analyze_outcomes(run)
        issues = provenance_issues(run)
        for metric, result in (("answers", primary), ("api_outcomes", outcomes)):
            for pair in result["pairs"]:
                pair["metric"] = metric
                pair["model"] = slug
                pair["per_run_adjusted_p_value"] = pair.pop("adjusted_p_value", None)
                pair["per_run_verdict"] = pair["verdict"]
                pair["valid_for_campaign"] = (
                    pair.get("p_value") is not None and pair["verdict"] != "inconclusive"
                )
                if issues.keys() & {pair["left"], pair["right"]}:
                    pair["valid_for_campaign"] = False
                    pair["reason"] = "Missing or conflicting route/model evidence"
                family.append(pair)
        studies[slug] = {
            "validation": validation,
            "route_issues": issues,
            "answers": primary,
            "api_outcomes": outcomes,
            "agreement_bounds": disagreement_bounds(run),
        }
    correct_family(family, protocol["alpha"])
    return {"alpha": protocol["alpha"], "family_size": len(family), "studies": studies}


def correct_family(family, alpha):
    if len(family) != 98:
        raise ValueError("Campaign requires all 98 planned tests, including invalid comparisons")
    corrected = holm([p["p_value"] if p["valid_for_campaign"] else 1 for p in family])
    for pair, adjusted in zip(family, corrected):
        pair["campaign_adjusted_p_value"] = adjusted if pair["valid_for_campaign"] else None
        pair["campaign_verdict"] = (
            "inconclusive"
            if not pair["valid_for_campaign"]
            else "detectably different"
            if adjusted <= alpha
            else "no difference detected"
        )


def render_model(slug, run, study):
    names = [e["name"] for e in run["config"]["endpoints"]]
    primary = study["answers"]["pairs"]
    outcomes = study["api_outcomes"]["pairs"]
    verdicts = {
        metric: dict(Counter(p["campaign_verdict"] for p in pairs))
        for metric, pairs in (("answers", primary), ("api_outcomes", outcomes))
    }
    valid = sum(r["status"] == "ok" for r in run["requests"])
    planned = len(run["items"]) * run["protocol"]["repeats"] * len(names)
    lines = [
        f"# {TITLES[slug]} — provider comparison",
        "",
        f"**280 questions · 14 subjects · 4 repeats · {len(names) - 1} providers + repeat control · 2,048-token ceiling**",
        "",
        (
            f"Collection window (UTC): **{run['started_at']} → {run['updated_at']}**. "
            "Report series dated 28 September 2026 in Asia/Bangkok."
        ),
        "",
        "## Results at a glance",
        "",
        (
            f"**{valid:,}/{planned:,} valid parsed answers ({valid / planned:.2%}).** "
            f"All {len(run['requests']):,} planned attempts are recorded; no failed request was retried."
        ),
        "",
        "| Analysis | Detectably different | No difference detected | Inconclusive |",
        "|---|---:|---:|---:|",
    ]
    for metric, label in (
        ("answers", "Answer choices (primary)"),
        ("api_outcomes", "API outcomes (supplement)"),
    ):
        v = verdicts[metric]
        lines.append(
            f"| {label} | {v.get('detectably different', 0)} | {v.get('no difference detected', 0)} | {v.get('inconclusive', 0)} |"
        )
    lines += [
        "",
        (
            "All significance decisions use one Holm correction across **98 planned comparisons across both model reports**, "
            "at family alpha 0.05. Counts include repeat-control comparisons. A completed nonsignificant test is distinct from an inconclusive test."
        ),
        "",
        (
            "The API-outcome supplement counts either the returned option letter or a failure status. "
            "It can detect formatting or availability differences; it does not establish different substantive answers or model weights. "
            "The answer-only test requires every planned answer to be valid."
        ),
        "",
    ]
    notable = [p for p in primary if p["campaign_verdict"] == "detectably different"]
    if notable:
        lines += [
            (
                "The primary analysis detects answer-distribution differences in the pairs listed below. "
                "Serving settings, hidden prompts, precision and routing remain possible explanations; the test does not identify the cause."
            ),
            "",
        ]
    elif all(p["campaign_verdict"] == "inconclusive" for p in primary):
        lines += [
            (
                "**The primary answer-only study is inconclusive for every pair because its complete-protocol requirements were not met.** "
                "The coverage and outcome results below do not turn that into evidence of equal answer distributions."
            ),
            "",
        ]
    else:
        lines += [
            (
                "No primary answer-choice difference passed the campaign correction. "
                "For completed comparisons this means no difference was detected at this sample size; unresolved pairs remain inconclusive."
            ),
            "",
        ]
    if study["route_issues"]:
        lines += ["### Route-evidence limitations", ""]
        lines += [
            f"- {LABELS[n]}: {reason}. Affected significance decisions are inconclusive."
            for n, reason in study["route_issues"].items()
        ]
        lines.append("")
    lines += [
        f"![Coverage and API-outcome effect estimates](figures/{slug}.png)",
        "",
        "## Coverage, task accuracy and request latency",
        "",
        (
            "Accuracy is correct/planned. Its range below allows every missing or invalid answer to be wrong or correct; "
            "it is a finite-sample bound, not a confidence interval. Latency is client-observed, non-streaming latency for HTTP-200 responses, "
            "including formatting failures. It is descriptive, not isolated inference throughput or time to first token."
        ),
        "",
        "| Provider | Valid / planned | Correct / planned | Accuracy bounds | HTTP-200 latency p50 / p95 | Known-usage estimate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for endpoint in run["config"]["endpoints"]:
        name = endpoint["name"]
        score = study["answers"]["scores"][name]
        rows = [r for r in run["requests"] if r["endpoint"] == name]
        latency = [
            r["latency_seconds"]
            for r in rows
            if r.get("http_status") == 200 and r.get("latency_seconds") is not None
        ]
        lo, hi = score["missing_answer_accuracy_bounds"]
        prices = endpoint["prices"]
        cost = (
            sum(
                (r.get("usage") or {}).get("prompt_tokens", 0) * prices["input_per_million"]
                + (r.get("usage") or {}).get("completion_tokens", 0) * prices["output_per_million"]
                for r in rows
            )
            / 1e6
        )
        timing = f"{np.quantile(latency, 0.5):.2f}s / {np.quantile(latency, 0.95):.2f}s" if latency else "—"
        lines.append(
            f"| {LABELS[name]} | {score['valid']}/{score['planned']} | {percent(score['observed_correct_over_planned'])} | "
            f"{percent(lo)}–{percent(hi)} | {timing} | ${cost:.4f} |"
        )
    lines += [
        "",
        (
            f"Total known-usage estimate: **${run['known_cost_usd']:.4f}**. "
            f"Requests missing complete token usage: **{run['missing_usage']}**. "
            "These are listed-price estimates, not receipts; unknown failed-request billing, cache discounts and fees are not resolved."
        ),
        "",
        "### Failure accounting",
        "",
        "| Provider | Recorded non-success statuses |",
        "|---|---|",
    ]
    for name in names:
        counts = Counter(
            r["status"] for r in run["requests"] if r["endpoint"] == name and r["status"] != "ok"
        )
        lines.append(
            f"| {LABELS[name]} | "
            + (", ".join(f"{k}: {v}" for k, v in sorted(counts.items())) or "None")
            + " |"
        )
    lines += [
        "",
        "## Pairwise statistical results",
        "",
        (
            "MMD² is the mean unbiased categorical effect estimate; negative estimates are allowed. "
            "The p-values below are campaign-adjusted. A dash indicates that inference was invalid, not p=0 or nonsignificance."
        ),
        "",
        "| Pair | Answer result | Answer MMD² | Adjusted p | API-outcome result | Outcome MMD² | Adjusted p |",
        "|---|---|---:|---:|---|---:|---:|",
    ]
    for answer, outcome in zip(primary, outcomes):
        assert (answer["left"], answer["right"]) == (outcome["left"], outcome["right"])
        lines.append(
            f"| {LABELS[answer['left']]} / {LABELS[answer['right']]} | {answer['campaign_verdict']} | "
            f"{number(answer.get('effect_size'))} | {number(answer['campaign_adjusted_p_value'], 5)} | "
            f"{outcome['campaign_verdict']} | {number(outcome.get('effect_size'))} | {number(outcome['campaign_adjusted_p_value'], 5)} |"
        )
    repeat = next(p for p in outcomes if {p["left"], p["right"]} == {"deepinfra", "deepinfra_repeat"})
    lines += [
        "",
        (
            f"**Repeat control:** {repeat['campaign_verdict']} for API outcomes "
            f"(campaign-adjusted p={number(repeat['campaign_adjusted_p_value'], 5)}). "
            "These aliases query the same configuration; shared infrastructure remains possible. This single comparison is not a calibrated false-positive-rate estimate."
        ),
        "",
        "## Agreement with missing-answer bounds",
        "",
        (
            "Every missing cross-response comparison is allowed either to agree or disagree. These finite-sample bounds preserve failures; "
            "they are not population confidence intervals or proof of equivalence."
        ),
        "",
        "| Pair | Agreement lower bound | Agreement upper bound | Observed / planned comparisons |",
        "|---|---:|---:|---:|",
    ]
    for b in study["agreement_bounds"]:
        lo, hi = b["agreement_bounds"]
        lines.append(
            f"| {LABELS[b['left']]} / {LABELS[b['right']]} | {percent(lo)} | {percent(hi)} | "
            f"{b['observed_cross_response_pairs']}/{b['planned_cross_response_pairs']} |"
        )
    display_names = [name for name in names if name != "deepinfra_repeat"]
    lines += [
        "",
        "## Subject-level results",
        "",
        "Each cell is correct / planned responses. Invalid or unavailable answers receive no credit; this is not an official leaderboard score.",
        "",
        "| Subject | " + " | ".join(LABELS[name] for name in display_names) + " |",
        "|---|" + "---:|" * len(display_names),
    ]
    for category in sorted({item["category"] for item in run["items"]}):
        scores = [study["answers"]["scores"][name]["by_category"][category] for name in display_names]
        lines.append(
            "| " + category + " | " + " | ".join(f"{s['correct']}/{s['planned']}" for s in scores) + " |"
        )
    lines += [
        "",
        "## Illustrative question-level disagreement",
        "",
        (
            "The following questions have the largest observed cross-provider disagreement among valid choices, excluding the repeat alias. "
            "They are selected descriptively after collection, not additional significance tests. Counts show repeated choices; missing responses remain missing."
        ),
        "",
        "| Question ID | Subject | Gold | " + " | ".join(LABELS[name] for name in display_names) + " |",
        "|---|---|---|" + "---|" * len(display_names),
    ]
    question_rows = []
    for item in run["items"]:
        choices = {
            name: Counter(
                r["choice"]
                for r in run["requests"]
                if r["question_id"] == item["id"] and r["endpoint"] == name and r["status"] == "ok"
            )
            for name in display_names
        }
        disagreements, comparisons = 0, 0
        for i, name in enumerate(display_names):
            for other in display_names[i + 1 :]:
                count = sum(choices[name].values()) * sum(choices[other].values())
                comparisons += count
                disagreements += count - sum(v * choices[other][k] for k, v in choices[name].items())
        if comparisons:
            question_rows.append((disagreements / comparisons, item["id"], item, choices))
    for _, _, item, choices in sorted(question_rows, key=lambda x: (-x[0], x[1]))[:12]:
        cells = []
        for name in display_names:
            text = ", ".join(f"{letter}×{count}" for letter, count in sorted(choices[name].items())) or "—"
            missing = run["protocol"]["repeats"] - sum(choices[name].values())
            cells.append(text + (f"; missing {missing}" if missing else ""))
        lines.append(f"| {item['id']} | {item['category']} | {item['answer']} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "## Exact routes and controls",
        "",
        "| Provider | Access path | Pinned route | Returned model metadata |",
        "|---|---|---|---|",
    ]
    for e in run["config"]["endpoints"]:
        returned = sorted(
            {
                r["returned_model"]
                for r in run["requests"]
                if r["endpoint"] == e["name"] and r.get("returned_model")
            }
        )
        lines.append(
            f"| {LABELS[e['name']]} | {'OpenRouter' if e['provider'] else 'Direct Netra API'} | `{e['provider'] or e['model']}` | "
            + ", ".join(f"`{m}`" for m in returned)
            + " |"
        )
    lines += [
        "",
        (
            "Requested settings: temperature 0.6, top-p 1, reasoning disabled, max output 2,048 tokens, no API seed, "
            "120-second timeout, no retries and no provider fallback. Exact-tag routing and returned metadata were checked. "
            "Metadata is a provider assertion, not independent attestation of weights or precision."
        ),
        "",
        "## Method and limitations",
        "",
        (
            "The [protocol](PROTOCOL.md) was published before main collection in commit "
            "[`4ecc14f`](https://github.com/NetraRuntime/trust-me-bro-benchmark/commit/4ecc14fe32cebd0fbb4528c3b331c92ad5211ca2). "
            "Its categorical MMD/permutation procedure uses 99,999 permutations, with one Holm family across both reports and both observables. "
            "Questions receive equal weight. The 2,000 subject-stratified bootstrap draws provide descriptive intervals in the analysis JSON."
        ),
        "",
        (
            "This is a balanced zero-shot direct-answer subset, not an official MMLU-Pro leaderboard score. "
            "The small independent setup pilot is excluded. Providers were curated for availability; the roster is not exhaustive. "
            "For V4 Flash 0731, Parasail was excluded before evaluation after six pilot HTTP-429 failures, as recorded in the protocol."
        ),
        "",
        (
            "Public benchmark contamination, correlated questions, hidden serving controls, temporal drift, cache behavior and cross-provider shared infrastructure "
            "limit generalization. A failed or invalid answer can reflect formatting rather than knowledge. "
            "The API-outcome test includes that distinction as observable behavior; it cannot resolve the underlying cause. "
            "HTTP-429 responses may reflect provider, router or account limits: error bodies and retry headers are not retained, so their origin is not established. "
            "Four repeats per question do not guarantee power against subtle differences. No equivalence or model-identity claim is made."
        ),
        "",
        "## Evidence and reproduction",
        "",
        f"- [Reviewed observations](evidence/{slug}.json.gz), with raw text and provider response IDs excluded.",
        "- [Combined campaign analysis](campaign-analysis.json.gz), containing per-question effects, descriptive intervals and both correction scopes.",
        "- [Frozen dataset](dataset.json), [protocol](protocol.json) and [pilot accounting](pilot-summary.json).",
        f"- [Exact configuration](configs/{slug}.yaml).",
        "",
        "```sh",
        "python -m pip install -e .",
        "python reports/2026-09-28-deepseek/analyze.py",
        "```",
        "",
        (
            "Reproduction is offline and makes no inference requests. The generic `tmb report` uses a narrower single-run correction; "
            "use the campaign script to reproduce the published cross-study correction."
        ),
        "",
    ]
    return "\n".join(lines)


def main():
    runs = {}
    for slug in TITLES:
        with gzip.open(ROOT / "evidence" / f"{slug}.json.gz", "rt", encoding="utf8") as stream:
            runs[slug] = json.load(stream)
    result = analyze(runs)
    payload = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    (ROOT / "campaign-analysis.json.gz").write_bytes(gzip.compress(payload, mtime=0))
    for slug, run in runs.items():
        (ROOT / f"{slug}.md").write_text(render_model(slug, run, result["studies"][slug]), encoding="utf8")
    print(
        json.dumps(
            {"analysis_sha256": hashlib.sha256(payload).hexdigest(), "family_size": result["family_size"]}
        )
    )


if __name__ == "__main__":
    main()
