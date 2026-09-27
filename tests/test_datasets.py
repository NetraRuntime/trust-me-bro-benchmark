import json
from collections import Counter
from threading import Lock

import httpx
import numpy as np
import pytest

from tmb.choice_analysis import analyze_choices, categorical_test, render_choices
from tmb.config import Config
from tmb.dataset_runner import compare_dataset
from tmb.datasets import PROTOCOL, load_dataset, parse_choice, question_prompt, select_items
from tmb.probes import digest


def package():
    data = {
        "protocol": PROTOCOL,
        "revision": "0" * 40,
        "items": [
            {
                "id": str(i),
                "category": "math" if i % 2 else "logic",
                "question": f"Fixture question {i}",
                "options": ["first", "second", "third"],
                "answer": "A",
            }
            for i in range(12)
        ],
    }
    return data | {"content_hash": digest(data)}


def config():
    return Config.model_validate(
        {
            "claimed_model": "example",
            "endpoints": [
                {"name": n, "base_url": "https://example.invalid/v1", "model": m, "api_key_env": "TEST_KEY"}
                for n, m in [("a", "same"), ("b", "same"), ("c", "different")]
            ],
            "reference": "a",
            "sampling": {"permutations": 199, "bootstrap": 100},
        }
    )


@pytest.mark.parametrize("text", ["a", " A ", "(a)", "**A**", "`a`", "Answer: a", "option: (A)."])
def test_parser_cosmetic_equivalence(text):
    assert parse_choice(text, 3) == "A"


@pytest.mark.parametrize(
    "text", ["A or B", "A because it is correct", "The answer is A", "J", "(A", "(A) B", ""]
)
def test_parser_rejects_ambiguous_or_invalid(text):
    assert parse_choice(text, 3) is None


def test_selection_and_hash_validation(tmp_path):
    rows = [
        {"question_id": i, "category": str(i % 2), "question": "x", "options": ["a", "b"], "answer": "A"}
        for i in range(20)
    ]
    selected = select_items(rows, 3, 91)
    assert selected == select_items(list(reversed(rows)), 3, 91)
    assert Counter(i["category"] for i in selected) == {"0": 3, "1": 3}
    assert "answer" not in question_prompt(selected[0]).split("Return only")[0].lower().replace(
        "best answer", ""
    )
    p = tmp_path / "data.json"
    p.write_text(json.dumps(package()))
    assert load_dataset(p)["items"] == package()["items"]
    data = package()
    data["items"][0]["answer"] = "B"
    p.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="hash"):
        load_dataset(p)


def test_categorical_same_accuracy_different_wrong_answers():
    # Both endpoints have zero accuracy if gold=A, yet answer distributions differ.
    groups = [(["B", "B"], ["C", "C"]) for _ in range(12)]
    result = categorical_test(groups, ["x"] * 12, 999, 100, 7)
    assert result["effect_size"] == 2
    assert result["p_value"] == 0.001
    assert categorical_test([(["B", "B"], ["B", "B"])] * 12, ["x"] * 12, 999, 100, 7)["p_value"] == 1


def test_synthetic_categorical_null_and_alternative():
    rng = np.random.default_rng(991)
    null_rejections = alternatives = 0
    for seed in range(40):
        groups = [
            (rng.choice(list("ABC"), 2).tolist(), rng.choice(list("ABC"), 2).tolist()) for _ in range(30)
        ]
        null_rejections += (
            categorical_test(groups, ["x"] * 15 + ["y"] * 15, 199, 100, seed)["p_value"] <= 0.05
        )
        shifted = [(a, ["D", "D"]) for a, b in groups]
        alternatives += categorical_test(shifted, ["x"] * 15 + ["y"] * 15, 199, 100, seed)["p_value"] <= 0.05
    assert null_rejections <= 6
    assert alternatives >= 35


def test_collection_report_controls_failures_resume_and_privacy(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_KEY", "private-fixture-credential")
    counter = 0
    lock = Lock()

    def handler(request):
        nonlocal counter
        body = json.loads(request.content)
        with lock:
            counter += 1
            rid = str(counter)
        answer = "Answer: b" if body["model"] == "same" else "**C**"
        return httpx.Response(
            200, json={"id": rid, "choices": [{"finish_reason": "stop", "message": {"content": answer}}]}
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = compare_dataset(config(), package(), tmp_path, workers=3, same_pair=["a", "b"], client=client)
        assert run["request_counts"] == {"ok": 72}
        assert run["analysis"]["pairs"][0]["kind"] == "same-configuration control"
        assert run["analysis"]["pairs"][0]["verdict"] == "no difference detected"
        assert run["analysis"]["pairs"][1]["verdict"] == "detectably different"
        assert all(s["observed_correct_over_planned"] == 0 for s in run["analysis"]["scores"].values())
        assert analyze_choices(run) == run["analysis"]
        assert render_choices(run) == render_choices(json.loads((tmp_path / "run.json").read_text()))
        raw = (tmp_path / "run.json").read_text()
        assert "private-fixture-credential" not in raw and "Fixture question" not in raw
        run["requests"][0]["status"] = "in_flight"
        (tmp_path / "run.json").write_text(json.dumps(run))
        resumed = compare_dataset(
            config(), package(), tmp_path, workers=3, same_pair=["a", "b"], resume=True, client=client
        )
        assert counter == 72
        assert resumed["request_counts"]["interrupted_unknown"] == 1
        assert sum(p["verdict"] == "inconclusive" for p in resumed["analysis"]["pairs"]) == 2


def test_budget_fails_before_dispatch_and_control_requires_matched_settings(tmp_path):
    cfg = config()
    cfg.limits.max_requests = 1
    with pytest.raises(ValueError, match="budget"):
        compare_dataset(cfg, package(), tmp_path)
    assert not (tmp_path / "run.json").exists()
    with pytest.raises(ValueError, match="identical"):
        compare_dataset(config(), package(), tmp_path, same_pair=["a", "c"])


def test_missing_answer_bounds_cover_every_possible_completion():
    from tmb.dataset_diagnostics import disagreement_bounds

    run = {
        "protocol": {"repeats": 2},
        "config": {"endpoints": [{"name": "a"}, {"name": "b"}]},
        "items": [{"id": "1", "option_count": 3}],
        "requests": [
            {"endpoint": "a", "question_id": "1", "repeat": 0, "status": "ok", "choice": "A"},
            {"endpoint": "a", "question_id": "1", "repeat": 1, "status": "truncated"},
            {"endpoint": "b", "question_id": "1", "repeat": 0, "status": "ok", "choice": "A"},
            {"endpoint": "b", "question_id": "1", "repeat": 1, "status": "ok", "choice": "B"},
        ],
    }
    result = disagreement_bounds(run)[0]
    assert result["disagreement_bounds"] == [0.25, 0.75]
    for value in "ABC":
        run["requests"][1].update(status="ok", choice=value)
        complete = disagreement_bounds(run)[0]
        rate = complete["disagreement_on_available_pairs"]
        assert result["disagreement_bounds"][0] <= rate <= result["disagreement_bounds"][1]
        assert complete["disagreement_bounds"] == [rate, rate]
