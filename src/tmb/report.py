"""Deterministic, standalone Markdown. Provider content is escaped as untrusted text."""

import html
import json
from collections import Counter

from .analysis import LIMITATIONS


def cell(value):
    text = html.escape(str(value)).replace("|", "&#124;").replace("\n", " ").replace("\r", " ")
    for char in ("`", "[", "]", "*", "_", "\\"):
        text = text.replace(char, f"&#{ord(char)};")
    return text


def render(run):
    lines = [
        "# Trust Me Bro — behavioral evidence",
        "",
        LIMITATIONS,
        "",
        f"Run: {cell(run['run_id'])} · tool {cell(run['tool_version'])}",
        "",
        f"Window: {cell(run['started_at'])} → {cell(run['updated_at'])}",
        "",
        f"Claimed model: {cell(run['config']['claimed_model'])}",
        "",
        f"Suite: {cell(run['suite_version'])} / {cell(run['suite_hash'])}",
        "",
        f"Request status counts: {cell(run['request_counts'])}. Remaining: {run['remaining_requests']}.",
        "",
        f"Token usage: {cell(run['usage'])}. Reserved estimated cost USD: {run['reserved_cost_usd']}.",
        "",
        f"Estimated cost from reported tokens USD: {run.get('estimated_reported_cost_usd')} (unknown if usage/prices missing).",
        "",
        f"Stop reason: {cell(run.get('stop_reason', 'plan completed'))}",
        "",
        "## Protocol and operational metrics",
        "",
        "Latency and spend are operational metrics, never model-identity scores.",
        "",
        "| Endpoint | Requested model | Returned model IDs | Mean latency (s) | Status counts |",
        "|---|---|---|---:|---|",
    ]
    for e in run["config"]["endpoints"]:
        rows = [r for r in run["requests"] if r["endpoint"] == e["name"]]
        latencies = [r["latency_seconds"] for r in rows if "latency_seconds" in r]
        lines.append(
            f"| {cell(e['name'])} | {cell(e['model'])} | "
            f"{cell(sorted({r['returned_model'] for r in rows if r.get('returned_model')}))} | "
            f"{sum(latencies) / len(latencies) if latencies else 'unknown'} | "
            f"{cell(dict(Counter(r['status'] for r in rows)))} |"
        )
    if run.get("reference_designation"):
        lines += [
            "",
            f"Reference designation: {cell(run['reference_designation'])}",
            "",
            f"Derived from: {cell(run['derived_from'])}. Collection config is preserved below.",
            "",
        ]
    lines += [
        "",
        "<details><summary>Configuration (credentials excluded)</summary>",
        "",
        "<pre>",
        html.escape(json.dumps(run["config"], indent=2, ensure_ascii=False)),
        "</pre>",
        "</details>",
        "",
    ]
    lines += [
        "## Probe protocol",
        "",
        "| ID | Level | Role | Prompt or private prompt hash |",
        "|---|---:|---|---|",
    ]
    for probe in run["probes"]:
        if probe["level"] <= min(run["level"], 3):
            lines.append(
                f"| {cell(probe['id'])} | {probe['level']} | {cell(probe['role'])} | "
                f"{cell(probe.get('prompt', 'Private: ' + probe['prompt_hash']))} |"
            )
    lines.append("")
    for level, data in run["analysis"].items():
        lines += [f"## Level {level}", "", cell(data.get("status", "Pairwise comparisons")), ""]
        if level == "4":
            lines += [f"Designated reference: {cell(data['reference'])}. {cell(data['trust'])}.", ""]
        matrix = data["matrix"]
        names = list(matrix)
        lines += ["| Endpoint | " + " | ".join(map(cell, names)) + " |", "|---|" + "---|" * len(names)]
        for name in names:
            lines.append("| " + cell(name) + " | " + " | ".join(cell(matrix[name][b]) for b in names) + " |")
        for pair in data["pairs"]:
            lines += [
                "",
                f"### {cell(pair['left'])} / {cell(pair['right'])}",
                "",
                f"**{cell(pair['verdict'])}**. Status: {cell(pair['status'])}.",
                "",
                f"Effect: {cell(pair.get('effect_name', 'not estimated'))}: {cell(pair['effect_size'])}.",
                "",
                f"Samples per probe [left, right]: {cell(pair['sample_counts'])}.",
                "",
                f"Uncertainty: {cell(pair['uncertainty'])}",
                "",
                f"Limitations: {cell(pair['limitations'])}",
                "",
            ]
            for field in (
                "method",
                "null_hypothesis",
                "p_value",
                "adjusted_p_value",
                "correction",
                "reason",
                "comparability",
                "known_differences",
                "comparison_kind",
                "signal_diagnostic",
            ):
                if field in pair:
                    lines += [f"{field}: {cell(pair[field])}", ""]
            if level in ("3", "4"):
                lines += [
                    "| Probe | MMD squared | Contribution to overall mean |",
                    "|---|---:|---:|",
                ]
                for observation in pair["observations"]:
                    lines.append(
                        f"| {cell(observation['probe'])} | {observation.get('mmd2', 'unavailable')} | "
                        f"{observation.get('contribution_to_mean_mmd2', 'unavailable')} |"
                    )
                lines += ["", "Contributions describe the observed statistic; no per-probe significance claim.", ""]
            lines += [
                "<details><summary>Per-probe evidence and representative disagreements (text only if opted in)</summary>",
                "",
                "<pre>",
                html.escape(json.dumps(pair["observations"], indent=2, ensure_ascii=False)),
                "</pre>",
                "</details>",
                "",
            ]
    lines += [
        "## Reproduce",
        "",
        "Run `tmb report PATH/run.json` to recompute statistics and this report offline.",
        "",
        "Hashes retain equality information, not semantic meaning. Private probe text stays outside the manifest.",
        "",
    ]
    return "\n".join(lines)
