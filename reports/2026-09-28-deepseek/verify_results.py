"""Independently check public evidence checksums, counts and reported effects.

No API calls. Effect verification uses pairwise equality kernels rather than
the analysis implementation's category-count formula. This checks arithmetic,
not provider truthfulness or the statistical exchangeability assumptions.
"""

import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def close(actual, expected):
    assert math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-12), (actual, expected)


def kernel_effect(a, b):
    within_a = sum(x == y for i, x in enumerate(a) for j, y in enumerate(a) if i != j)
    within_b = sum(x == y for i, x in enumerate(b) for j, y in enumerate(b) if i != j)
    cross = sum(x == y for x in a for y in b)
    return (
        within_a / (len(a) * (len(a) - 1))
        + within_b / (len(b) * (len(b) - 1))
        - 2 * cross / (len(a) * len(b))
    )


def main():
    checksums = json.loads((ROOT / "checksums.json").read_text(encoding="utf8"))
    analysis = json.loads(gzip.decompress((ROOT / "campaign-analysis.json.gz").read_bytes()))
    verified_effects, attempts, tests = 0, 0, []
    for slug, study in analysis["studies"].items():
        compressed = (ROOT / "evidence" / f"{slug}.json.gz").read_bytes()
        payload = gzip.decompress(compressed)
        assert hashlib.sha256(compressed).hexdigest() == checksums[slug]["public_gzip_sha256"]
        assert hashlib.sha256(payload).hexdigest() == checksums[slug]["public_json_sha256"]
        run = json.loads(payload)
        assert not run["remaining_requests"]
        assert all("text" not in r and "response_id" not in r for r in run["requests"])
        attempts += len(run["requests"])
        items = run["items"]
        gold = {q["id"]: q["answer"] for q in items}
        repeats = run["protocol"]["repeats"]
        names = [e["name"] for e in run["config"]["endpoints"]]
        grouped = {(name, q["id"]): [] for name in names for q in items}
        for row in run["requests"]:
            grouped[row["endpoint"], row["question_id"]].append(row)
        assert all(len(rows) == repeats for rows in grouped.values())
        for name in names:
            rows = [r for r in run["requests"] if r["endpoint"] == name]
            valid = sum(r["status"] == "ok" for r in rows)
            correct = sum(r["status"] == "ok" and r["choice"] == gold[r["question_id"]] for r in rows)
            score = study["answers"]["scores"][name]
            assert score["valid"] == valid and score["planned"] == len(rows)
            assert score["statuses"] == dict(Counter(r["status"] for r in rows))
            close(score["observed_correct_over_planned"], correct / len(rows))
            close(score["missing_answer_accuracy_bounds"][0], correct / len(rows))
            close(score["missing_answer_accuracy_bounds"][1], (correct + len(rows) - valid) / len(rows))
        for metric in ("answers", "api_outcomes"):
            for pair in study[metric]["pairs"]:
                tests.append(pair)
                if pair.get("effect_size") is None:
                    continue
                effects = []
                for item in items:
                    a, b = [], []
                    for name, target in ((pair["left"], a), (pair["right"], b)):
                        for row in grouped[name, item["id"]]:
                            if metric == "answers":
                                assert row["status"] == "ok"
                                target.append(row["choice"])
                            else:
                                target.append(
                                    "choice:" + row["choice"]
                                    if row["status"] == "ok"
                                    else "status:" + row["status"]
                                )
                    effects.append(kernel_effect(a, b))
                close(pair["effect_size"], sum(effects) / len(effects))
                for actual, expected in zip(pair["per_question_effect"], effects):
                    close(actual, expected)
                verified_effects += 1
    assert attempts == 16800 and len(tests) == analysis["family_size"] == 98
    ordered = sorted(tests, key=lambda p: p["p_value"] if p["valid_for_campaign"] else 1)
    running = 0
    for rank, pair in enumerate(ordered):
        raw = pair["p_value"] if pair["valid_for_campaign"] else 1
        running = min(1, max(running, (len(ordered) - rank) * raw))
        if pair["valid_for_campaign"]:
            close(pair["campaign_adjusted_p_value"], running)
            assert pair["campaign_verdict"] == (
                "detectably different" if running <= analysis["alpha"] else "no difference detected"
            )
        else:
            assert pair["campaign_verdict"] == "inconclusive"
            assert pair["campaign_adjusted_p_value"] is None
    result = {
        "attempts_verified": attempts,
        "planned_tests_verified": len(tests),
        "pair_effects_independently_recomputed": verified_effects,
        "checksums_verified": True,
        "raw_text_and_response_ids_excluded": True,
        "accuracy_and_missing_bounds_recomputed": True,
        "holm_family_recomputed": True,
        "analysis_gzip_sha256": hashlib.sha256((ROOT / "campaign-analysis.json.gz").read_bytes()).hexdigest(),
        "scope": "Arithmetic and publication checks only; no certification of provider assertions or statistical assumptions.",
    }
    (ROOT / "result-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
