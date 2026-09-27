import json
from pathlib import Path

import httpx
import pytest

from tmb.analysis import analyze
from tmb.config import Config, load_config
from tmb.probes import PUBLIC, digest, load_probes
from tmb.report import render
from tmb.runner import benchmark, plan


def config():
    cfg = load_config(Path("examples/mock.yaml"))
    cfg.sampling.repeats = {0: 1, 1: 2, 2: 1, 3: 8}
    cfg.sampling.permutations = 199
    cfg.sampling.bootstrap = 100
    return cfg


def run_at(tmp_path, cfg=None, level=3, **kwargs):
    cfg = cfg or config()
    return benchmark(cfg, PUBLIC, digest([p.model_dump() for p in PUBLIC]), level, tmp_path, **kwargs)


def test_vertical_slice_and_reproduction(tmp_path):
    run = run_at(tmp_path, level=1)
    assert len(run["analysis"]["1"]["pairs"]) == 3
    assert len(run["analysis"]["1"]["matrix"]) == 3
    loaded = json.loads((tmp_path / "run.json").read_text(encoding="utf-8"))
    assert analyze(loaded) == run["analysis"]
    assert render(loaded) == render(run)
    assert all("text" not in r for r in loaded["requests"])


def test_statistical_and_reference_reports(tmp_path):
    run = run_at(tmp_path, level=4)
    pairs = run["analysis"]["3"]["pairs"]
    assert pairs[0]["verdict"] == "no difference detected"
    assert all(p["verdict"] == "detectably different" for p in pairs[1:])
    assert len(run["analysis"]["4"]["pairs"]) == 2


def test_single_formatting_probe_attribution_preserves_primary_test(tmp_path):
    run = run_at(tmp_path, level=4)
    for row in run["requests"]:
        if row["level"] == 3:
            text = "Biru" if row["endpoint"] == "mock_a" and row["probe"] == "l3-multilingual" else "biru"
            row["answer_hash"] = digest(text)
    run["analysis"] = analyze(run)
    pair = run["analysis"]["3"]["pairs"][0]
    assert pair["verdict"] == "detectably different"
    assert pair["signal_diagnostic"]["largest_absolute_contributor"] == "l3-multilingual"
    assert pair["signal_diagnostic"]["largest_absolute_share"] == 1
    assert sum(o["contribution_to_mean_mmd2"] for o in pair["observations"]) == pytest.approx(pair["statistic"])
    assert "Contribution to overall mean" in render(run)
    # Normalize this synthetic case only: zero signal must not select an arbitrary driver.
    for row in run["requests"]:
        row["answer_hash"] = digest("biru")
    pair = analyze(run)["3"]["pairs"][0]
    assert pair["signal_diagnostic"]["largest_absolute_contributor"] is None
    assert pair["signal_diagnostic"]["largest_absolute_share"] is None
    assert pair["verdict"] == "no difference detected"


def test_insufficient_and_failures_visible(tmp_path):
    cfg = config()
    cfg.sampling.min_samples = 9
    cfg.endpoints[-1].mock_behavior = "truncated"
    run = run_at(tmp_path, cfg)
    assert run["analysis"]["3"]["pairs"][0]["status"] == "insufficient_samples"
    assert run["analysis"]["3"]["pairs"][-1]["status"] == "incomplete"
    assert run["request_counts"]["truncated"] > 0


def test_budget_and_no_repeat_resume(tmp_path):
    cfg = config()
    cfg.limits.max_requests = 3
    first = run_at(tmp_path, cfg, level=1)
    resumed = run_at(tmp_path, cfg, level=1, resume=True)
    assert len(first["requests"]) == len(resumed["requests"]) == 3
    assert resumed["remaining_requests"] > 0
    cfg.sampling.temperature = 0.5
    with pytest.raises(ValueError, match="protocol changed"):
        run_at(tmp_path, cfg, level=1, resume=True)


def test_redaction_and_identical_payloads(tmp_path, monkeypatch):
    secret = "unusual-key-without-prefix"
    monkeypatch.setenv("MOCK_KEY", secret)
    cfg = config()
    seen = []
    for ep in cfg.endpoints:
        ep.adapter = "openai"
        ep.base_url = "https://example.invalid/v1"
        ep.api_key_env = "MOCK_KEY"

    def handler(req):
        seen.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "id": f"id-{len(seen)}",
                "model": "example",
                "choices": [
                    {"finish_reason": "stop", "message": {"content": secret + " <script>x</script>"}}
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        run = run_at(tmp_path, cfg, level=0, store_text=True, client=client)
    assert seen[0] == seen[1] == seen[2]
    assert secret not in (tmp_path / "run.json").read_text(encoding="utf-8")
    assert "<script>" not in render(run)


def test_private_prompts_not_saved(tmp_path):
    private = tmp_path / "private.yaml"
    private.write_text("\n".join(f"- id: p{i}\n  level: {i}\n  prompt: sensitive-{i}" for i in range(4)))
    cfg = config()
    cfg.probes_file = "private.yaml"
    probes, suite_hash = load_probes(cfg, tmp_path / "config.yaml")
    benchmark(cfg, probes, suite_hash, 0, tmp_path / "output")
    assert "sensitive-" not in (tmp_path / "output/run.json").read_text()


def test_missing_reference_and_uninformative_kernel(tmp_path):
    cfg = config()
    cfg.reference = None
    run = run_at(tmp_path, cfg, level=4)
    assert run["analysis"]["4"]["status"].startswith("skipped")
    for i, r in enumerate(run["requests"]):
        r["answer_hash"] = str(i)
    assert analyze(run)["3"]["pairs"][0]["status"] == "uninformative_kernel"


def test_interrupted_request_not_resent(tmp_path):
    run = run_at(tmp_path, level=0)
    run["requests"][0]["status"] = "in_flight"
    (tmp_path / "run.json").write_text(json.dumps(run))
    resumed = run_at(tmp_path, level=0, resume=True)
    assert len(resumed["requests"]) == 3
    assert resumed["requests"][0]["status"] == "interrupted_unknown"


def test_config_and_plan():
    with pytest.raises(ValueError):
        Config(claimed_model="x", endpoints=[])
    cfg = config()
    jobs = plan(cfg, PUBLIC, 1)
    assert jobs == plan(cfg, PUBLIC, 1)
    assert len(jobs) == 27
    for i in range(0, len(jobs), 3):
        assert len({j["endpoint"] for j in jobs[i : i + 3]}) == 3


def test_different_model_control_is_labelled(tmp_path):
    cfg = config()
    cfg.endpoints[-1].role = "different_model_control"
    run = run_at(tmp_path, cfg, level=0)
    assert run["analysis"]["0"]["pairs"][-1]["comparison_kind"] == "different-model control"
    cfg.reference = cfg.endpoints[-1].name
    with pytest.raises(ValueError):
        Config.model_validate(cfg.model_dump())


def test_post_collection_reference_preserves_statistical_family(tmp_path):
    import subprocess
    import sys

    cfg = config()
    cfg.reference = None
    run_at(tmp_path, cfg, level=3)
    original = (tmp_path / "run.json").read_bytes()
    command = [sys.executable, "-m", "tmb.cli", "report", str(tmp_path / "run.json"), "--reference", "mock_a"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    audit = json.loads((tmp_path / "reference-report.json").read_text(encoding="utf-8"))
    source = json.loads(original)
    assert (tmp_path / "run.json").read_bytes() == original
    assert audit["config"] == source["config"]
    assert audit["requests"] == source["requests"]
    assert audit["analysis"]["3"] == source["analysis"]["3"]
    assert audit["analysis"]["4"]["reference"] == "mock_a"
    assert audit["reference_designation"]["kind"] == "post-collection user designation"
    assert subprocess.run(command, capture_output=True, check=False).returncode == 2
    source_report = tmp_path / "report.md"
    source_report.write_text("Original collection report", encoding="utf-8")
    audit_report = (tmp_path / "reference-report.md").read_bytes()
    result = subprocess.run(
        [sys.executable, "-m", "tmb.cli", "report", str(tmp_path / "reference-report.json")],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0
    assert source_report.read_text(encoding="utf-8") == "Original collection report"
    assert (tmp_path / "reference-report.md").read_bytes() == audit_report
