from copy import deepcopy

import numpy as np
import pytest

from tmb.config import Config
from tmb.consistency import analyze_consistency, render_consistency


def fixture(seed=13, questions=300, margin=0.12):
    rng = np.random.default_rng(seed)
    names = ["reference", "repeat", "candidate", "different"]
    endpoints = [
        {"name": n, "role": "different_model_control" if n == "different" else "candidate"} for n in names
    ]
    rows = []
    for i in range(questions):
        # Independent draws; difficulty varies across question clusters.
        chance = 0.55 if i % 4 == 0 else 0.99
        for name in names:
            for repeat in range(2):
                answer = "A" if rng.random() < (0.15 if name == "different" else chance) else "B"
                rows.append(
                    {
                        "endpoint": name,
                        "question_id": str(i),
                        "repeat": repeat,
                        "choice": answer,
                        "status": "ok",
                    }
                )
    return {
        "config": {"endpoints": endpoints},
        "protocol": {
            "repeats": 2,
            "seed": 2026,
            "bootstrap": 4000,
            "alpha": 0.05,
            "consistency": {
                "method": "paired-disagreement-bootstrap-v1",
                "baseline": names[:2],
                "margin": margin,
                "min_questions": 100,
                "max_missing_fraction": 0.05,
            },
        },
        "items": [{"id": str(i), "category": str(i % 3), "option_count": 2} for i in range(questions)],
        "requests": rows,
    }


def pair(result, a, b):
    return next(p for p in result["pairs"] if {p["left"], p["right"]} == {a, b})


def test_same_different_and_failure_bounds_reproduce():
    run = fixture()
    result = analyze_consistency(run)
    assert result["sensitivity_demonstrated"]
    assert pair(result, "reference", "candidate")["verdict"] == "within baseline tolerance"
    assert pair(result, "reference", "different")["verdict"] == "beyond baseline tolerance"
    before = pair(result, "reference", "candidate")["excess_disagreement_bounds"]
    run["requests"][4]["status"] = "truncated"
    changed = analyze_consistency(run)
    after = pair(changed, "reference", "candidate")["excess_disagreement_bounds"]
    assert after[0] <= before[0] <= before[1] <= after[1]
    assert pair(changed, "reference", "candidate")["verdict"] == "within baseline tolerance"
    assert changed == analyze_consistency(deepcopy(run))
    assert "approximate" in render_consistency(changed).lower()


def test_no_sensitivity_no_consistency_and_high_missingness():
    run = fixture()
    for row in run["requests"]:
        if row["endpoint"] == "different":
            row["status"] = "http_error"
    result = analyze_consistency(run)
    assert not result["sensitivity_demonstrated"]
    assert pair(result, "reference", "candidate")["verdict"] == "inconclusive"
    assert pair(result, "reference", "different")["verdict"] == "inconclusive"


def test_insufficient_degenerate_incomplete_and_mismatched_are_inconclusive():
    for variant in ("few", "degenerate", "pending", "mismatch", "resolution"):
        run = fixture(questions=30 if variant == "few" else 100)
        if variant == "degenerate":
            for row in run["requests"]:
                row["choice"] = "A"
        if variant == "pending":
            run["remaining_requests"] = 1
        if variant == "mismatch":
            run["config"]["endpoints"][0]["reasoning_enabled"] = False
        if variant == "resolution":
            run["protocol"]["bootstrap"] = 100
        assert pair(analyze_consistency(run), "reference", "candidate")["verdict"] == "inconclusive"


def test_duplicate_observation_rejected():
    run = fixture(questions=30)
    run["requests"].append(run["requests"][0])
    with pytest.raises(ValueError, match="Duplicate"):
        analyze_consistency(run)


def test_predeclaration_requires_matched_baseline_control_and_resolution():
    base = {
        "claimed_model": "fixture",
        "endpoints": [
            {
                "name": name,
                "base_url": "https://example.invalid/v1",
                "model": "fixture",
                "role": "different_model_control" if name == "different" else "candidate",
            }
            for name in ("reference", "repeat", "candidate", "different")
        ],
        "sampling": {"bootstrap": 4000},
        "consistency": {"baseline": ["reference", "repeat"], "margin": 0.12},
    }
    Config.model_validate(base)
    for variant in ("margin", "baseline", "control", "resolution"):
        cfg = deepcopy(base)
        if variant == "margin":
            del cfg["consistency"]["margin"]
        if variant == "baseline":
            cfg["endpoints"][1]["model"] = "other"
        if variant == "control":
            cfg["endpoints"][-1]["role"] = "candidate"
        if variant == "resolution":
            cfg["sampling"]["bootstrap"] = 100
        with pytest.raises(ValueError):
            Config.model_validate(cfg)


def test_synthetic_operating_characteristics_without_threshold_tuning():
    # Fixed seed grid and fixed tolerance; independent of all live evaluation results.
    same_pass = different_detected = false_beyond = 0
    for seed in range(12):
        result = analyze_consistency(fixture(seed=seed))
        same = pair(result, "reference", "candidate")["verdict"]
        same_pass += same == "within baseline tolerance"
        false_beyond += same == "beyond baseline tolerance"
        different_detected += pair(result, "reference", "different")["verdict"] == "beyond baseline tolerance"
    assert same_pass >= 10
    assert false_beyond <= 1
    assert different_detected >= 11


def test_collection_freezes_tolerance_and_refuses_resume_changes(tmp_path):
    import json

    import httpx

    from tmb.choice_analysis import analyze_choices, render_choices
    from tmb.dataset_runner import compare_dataset
    from tmb.datasets import PROTOCOL
    from tmb.probes import digest

    cfg = Config.model_validate(
        {
            "claimed_model": "fixture",
            "endpoints": [
                {
                    "name": name,
                    "base_url": "https://example.invalid/v1",
                    "model": "fixture",
                    "role": "different_model_control" if name == "different" else "candidate",
                }
                for name in ("reference", "repeat", "candidate", "different")
            ],
            "sampling": {"bootstrap": 4000, "permutations": 99},
            "consistency": {"baseline": ["reference", "repeat"], "margin": 0.12},
        }
    )
    package = {
        "protocol": PROTOCOL,
        "revision": "0" * 40,
        "items": [
            {
                "id": str(i),
                "category": "fixture",
                "question": "Pick one",
                "options": ["x", "y"],
                "answer": "A",
            }
            for i in range(4)
        ],
    }
    package["content_hash"] = digest(package)

    def respond(request):
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "A"}}]})

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        run = compare_dataset(cfg, package, tmp_path, client=client)
        assert run["protocol"]["consistency"]["margin"] == 0.12
        assert "inconclusive" in render_choices(run)
        assert run["analysis"] == analyze_choices(json.loads((tmp_path / "run.json").read_text()))
        cfg.consistency.margin = 0.2
        with pytest.raises(ValueError, match="differs"):
            compare_dataset(cfg, package, tmp_path, resume=True, client=client)
