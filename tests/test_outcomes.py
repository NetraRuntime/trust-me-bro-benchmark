from copy import deepcopy

from tmb.outcomes import analyze_outcomes


def fixture():
    return {
        "config": {"endpoints": [{"name": "a"}, {"name": "b"}], "sampling": {"request_seed": None}},
        "items": [{"id": str(i), "category": "fixture", "answer": "A", "option_count": 2} for i in range(24)],
        "protocol": {"repeats": 4, "seed": 42, "permutations": 999, "bootstrap": 100, "alpha": 0.05},
        "requests": [
            {"endpoint": name, "question_id": str(i), "repeat": repeat, "status": "ok", "choice": "A"}
            for name in ("a", "b")
            for i in range(24)
            for repeat in range(4)
        ],
    }


def test_outcome_test_distinguishes_failures_without_mutating_answer_evidence():
    run = fixture()
    assert analyze_outcomes(run)["pairs"][0]["p_value"] == 1
    for row in run["requests"]:
        if row["endpoint"] == "b":
            row["status"] = "http_error"
    before = deepcopy(run)
    pair = analyze_outcomes(run)["pairs"][0]
    assert pair["effect_size"] == 2
    assert pair["p_value"] == 0.001
    assert pair["verdict"] == "detectably different API outcomes"
    assert run == before


def test_outcome_test_rejects_uncollected_or_nonindependent_samples():
    for status in (
        "in_flight",
        "interrupted_unknown",
        "adapter_error_unknown",
        "missing_api_key",
        "cache_suspected",
    ):
        run = fixture()
        run["requests"][0]["status"] = status
        assert "p_value" not in analyze_outcomes(run)["pairs"][0]
    run = fixture()
    run["requests"].pop()
    assert analyze_outcomes(run)["pairs"][0]["verdict"] == "inconclusive"
    run = fixture()
    run["config"]["sampling"]["request_seed"] = 3
    assert "p_value" not in analyze_outcomes(run)["pairs"][0]
    for code in (401, 402):
        run = fixture()
        run["requests"][0].update(status="http_error", http_status=code)
        assert "p_value" not in analyze_outcomes(run)["pairs"][0]
