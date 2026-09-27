"""Regression cases from the external audit; all requests use offline fixtures."""

import json
import subprocess
import sys
from collections import Counter
from copy import deepcopy

import pytest

from tmb.analysis import analyze
from tmb.choice_analysis import analyze_choices, render_choices
from tmb.config import Config
from tmb.dataset_diagnostics import disagreement_bounds
from tmb.dataset_runner import compare_dataset, dataset_plan
from tmb.datasets import PROTOCOL
from tmb.probes import PUBLIC, digest
from tmb.runner import benchmark, plan
from tmb.service import BenchmarkService
from tmb.validation import CONSISTENCY_METHOD, validate_manifest


@pytest.fixture
def collected(tmp_path):
    config = Config.model_validate(
        {
            "claimed_model": "fixture",
            "endpoints": [
                {
                    "name": name,
                    "adapter": "mock",
                    "base_url": "mock://fixture",
                    "model": "fixture",
                    "mock_behavior": "choice_b" if name == "different" else "choice_a",
                    "role": "different_model_control" if name == "different" else "candidate",
                }
                for name in ("reference", "repeat", "candidate", "different")
            ],
            "sampling": {"permutations": 199, "bootstrap": 4000},
            "consistency": {"baseline": ["reference", "repeat"], "margin": 0.12},
        }
    )
    data = {
        "protocol": PROTOCOL,
        "dataset": "synthetic",
        "revision": "fixture-v1",
        "items": [
            {
                "id": str(i),
                "category": "fixture",
                "question": f"Question {i}",
                "options": ["one", "two", "three"],
                "answer": "A",
            }
            for i in range(6)
        ],
    }
    data["content_hash"] = digest(data)
    run = compare_dataset(config, data, tmp_path / "run")
    (tmp_path / "dataset.json").write_text(json.dumps(data), encoding="utf8")
    return config, data, run


def test_seeded_inference_rejected_before_dispatch_and_dry_run(tmp_path, collected):
    config, data, _ = collected
    config.sampling.request_seed = 42
    for call in (
        lambda: dataset_plan(config, data, 2, 2026),
        lambda: compare_dataset(config, data, tmp_path / "seeded"),
        lambda: plan(config, PUBLIC, 3),
    ):
        with pytest.raises(ValueError, match="request_seed: null"):
            call()
    assert not (tmp_path / "seeded").exists()
    assert plan(config, PUBLIC, 1)  # Descriptive-only levels may record seeded samples.


@pytest.mark.parametrize("change", ["duplicate", "repeat", "choice", "endpoint", "question", "status"])
def test_bad_rows_rejected_by_analysis_and_bounds(collected, change):
    _, _, original = collected
    run = deepcopy(original)
    run["protocol"].pop("consistency")  # Validation must not depend on this optional feature.
    row = run["requests"][0]
    if change == "duplicate":
        run["requests"].append(deepcopy(row))
    else:
        field, value = {
            "repeat": ("repeat", 2),
            "choice": ("choice", "J"),
            "endpoint": ("endpoint", "unknown"),
            "question": ("question_id", "unknown"),
            "status": ("status", "invented"),
        }[change]
        row[field] = value
    for analyzer in (analyze_choices, disagreement_bounds):
        with pytest.raises(ValueError):
            analyzer(run)


def test_duplicate_can_no_longer_replace_a_required_repeat(collected):
    _, _, run = collected
    first = run["requests"][0]
    other = next(
        i
        for i, r in enumerate(run["requests"])
        if r["endpoint"] == first["endpoint"]
        and r["question_id"] == first["question_id"]
        and r["repeat"] != first["repeat"]
    )
    run["requests"][other] = deepcopy(first)
    with pytest.raises(ValueError, match="Duplicate"):
        analyze_choices(run)


@pytest.mark.parametrize("change", ["margin", "alpha", "gold", "counts", "request_settings"])
def test_altered_manifest_rejected_by_cli_and_mcp(tmp_path, collected, change):
    _, _, run = collected
    if change == "margin":
        run["protocol"]["consistency"]["margin"] = 0.9
    elif change == "alpha":
        run["protocol"]["alpha"] = run["config"]["sampling"]["alpha"] = 0.9
    elif change == "gold":
        run["items"][0]["answer"] = "B"
    elif change == "request_settings":
        run["requests"][0]["requested_settings"]["temperature"] = 0.123
    else:
        run["request_counts"]["ok"] += 1
    manifest = tmp_path / "altered.json"
    manifest.write_text(json.dumps(run), encoding="utf8")
    result = subprocess.run(
        [sys.executable, "-m", "tmb.cli", "report", str(manifest), "--output", str(tmp_path / "rejected.md")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert not (tmp_path / "rejected.md").exists()
    service = BenchmarkService(tmp_path)
    try:
        with pytest.raises(ValueError):
            service.report("altered.json")
    finally:
        service.close()


def test_legacy_dataset_requires_original_for_item_linkage(collected):
    _, data, run = collected
    run["tool_version"] = "0.2.0"
    run["schema_version"] = 1
    run["protocol"].pop("items_hash")
    run["protocol"]["consistency"]["method"] = "paired-disagreement-bootstrap-v1"
    run["protocol_hash"] = digest(
        [
            run["config"],
            run["dataset"]["content_hash"],
            run["protocol"],
            run["store_text"],
            run["tool_version"],
        ]
    )
    assert "unverified" in validate_manifest(run)["dataset"]
    assert "verified against" in validate_manifest(run, data)["dataset"]
    run["items"][0]["answer"] = "B"
    with pytest.raises(ValueError, match="items do not match"):
        validate_manifest(run, data)


def test_cli_and_mcp_verify_dataset_and_keep_manifest_unchanged(tmp_path, collected):
    _, _, _ = collected
    manifest = tmp_path / "run/run.json"
    before = manifest.read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "tmb.cli",
            "report",
            str(manifest),
            "--dataset",
            str(tmp_path / "dataset.json"),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert manifest.read_bytes() == before
    assert "verified against the supplied frozen dataset" in (tmp_path / "run/report.md").read_text()
    service = BenchmarkService(tmp_path)
    try:
        assert "verified against" in service.report("run/run.json", "dataset.json")["report_markdown"]
        outside = tmp_path.parent / f"{tmp_path.name}-outside.json"
        outside.write_text("{}", encoding="utf8")
        with pytest.raises(ValueError):
            service.report("run/run.json", str(outside))
    finally:
        service.close()


def test_agreeing_survivors_still_show_missing_question(collected):
    _, _, run = collected
    qid = run["items"][0]["id"]
    for row in run["requests"]:
        if row["question_id"] == qid:
            row["choice"] = "A"
    missing = next(r for r in run["requests"] if r["question_id"] == qid and r["endpoint"] == "reference")
    missing["status"] = "transport_error"
    run["request_counts"] = dict(Counter(r["status"] for r in run["requests"]))
    run["analysis"] = analyze_choices(run)
    report = render_choices(run)
    # All three affected pair tables include the missing question despite agreement.
    assert report.count("| 1/2, 2/2 |") == 3
    assert "transport&#95;error" in report
    assert all(p["verdict"] == "inconclusive" for p in run["analysis"]["pairs"] if p["left"] == "reference")


def test_new_baseline_view_is_only_descriptive(collected):
    _, _, run = collected
    assert run["protocol"]["consistency"]["method"] == CONSISTENCY_METHOD
    result = run["analysis"]["consistency"]
    assert all(p["verdict"] == "descriptive only" for p in result["pairs"])
    assert all("descriptive_bootstrap_interval" in p for p in result["pairs"])
    assert "No calibrated tolerance/equivalence verdict" in render_choices(run)


def test_historical_seeded_observations_cannot_claim_significance(collected):
    _, _, run = collected
    run["config"]["sampling"]["request_seed"] = 42
    result = analyze_choices(run)
    assert all(
        p["verdict"] == "inconclusive" and "Shared request seeds" in p["reason"] for p in result["pairs"]
    )
    run["analysis"] = result
    assert "Shared request seeds" in render_choices(run)


def test_legacy_duplicate_rejected_and_report_cannot_overwrite_input(tmp_path):
    cfg = Config.model_validate(
        {
            "claimed_model": "fixture",
            "endpoints": [
                {"name": name, "adapter": "mock", "base_url": "mock://fixture", "model": "fixture"}
                for name in ("a", "b")
            ],
        }
    )
    run = benchmark(cfg, PUBLIC, digest([p.model_dump() for p in PUBLIC]), 0, tmp_path)
    run["requests"].append(deepcopy(run["requests"][0]))
    with pytest.raises(ValueError, match="Duplicate"):
        analyze(run)
    manifest = tmp_path / "run.json"
    before = manifest.read_bytes()
    result = subprocess.run(
        [sys.executable, "-m", "tmb.cli", "report", str(manifest), "--output", str(manifest)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert manifest.read_bytes() == before
