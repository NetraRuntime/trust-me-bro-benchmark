import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from tmb.adapters import OpenAIAdapter
from tmb.config import Endpoint, Prices, load_config
from tmb.probes import PUBLIC, digest
from tmb.runner import atomic_json, benchmark


def cfg():
    return load_config(Path("examples/mock.yaml"))


def run(config, path, **kwargs):
    return benchmark(config, PUBLIC, digest([p.model_dump() for p in PUBLIC]), 0, path, **kwargs)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"choices": []},
        {"choices": [{"message": None}]},
        {"id": {"bad": "metadata"}, "choices": []},
        {"choices": [{"message": {"content": 123}, "finish_reason": "stop"}]},
    ],
)
def test_malformed_api_responses(data):
    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))) as client:
        row = OpenAIAdapter(client).sample(
            Endpoint(name="a", base_url="https://example.invalid", model="m"), {}, "1"
        )
    assert row["status"] == "invalid_response"


def test_timeout_and_missing_credentials(monkeypatch):
    monkeypatch.delenv("NONEXISTENT_TMB_TEST_KEY", raising=False)
    ep = Endpoint(name="a", base_url="https://example.invalid", model="m")

    def timeout(req):
        raise httpx.ReadTimeout("do not persist exception body", request=req)

    with httpx.Client(transport=httpx.MockTransport(timeout)) as client:
        adapter = OpenAIAdapter(client)
        assert adapter.sample(ep, {}, "1")["status"] == "timeout"
        ep.api_key_env = "NONEXISTENT_TMB_TEST_KEY"
        assert adapter.sample(ep, {}, "1")["status"] == "missing_api_key"


def test_resume_after_actual_interrupt(tmp_path, monkeypatch):
    from tmb.adapters import MockAdapter

    original = MockAdapter.sample
    count = 0

    def interrupt(self, *args):
        nonlocal count
        count += 1
        if count == 2:
            raise KeyboardInterrupt
        return original(self, *args)

    monkeypatch.setattr(MockAdapter, "sample", interrupt)
    with pytest.raises(KeyboardInterrupt):
        run(cfg(), tmp_path)
    assert not (tmp_path / ".run.lock").exists()
    monkeypatch.setattr(MockAdapter, "sample", original)
    resumed = run(cfg(), tmp_path, resume=True)
    assert resumed["request_counts"] == {"ok": 2, "interrupted_unknown": 1}
    assert resumed["analysis"]["0"]["pairs"][0]["verdict"] == "inconclusive"


def test_cost_ceiling_and_overrun(tmp_path):
    c = cfg()
    for e in c.endpoints:
        e.prices = Prices(input_per_million=1, output_per_million=100)
    c.limits.max_cost_usd = 0.00001
    result = run(c, tmp_path / "budget")
    assert result["requests"] == []
    c.limits.max_cost_usd = 1
    for e in c.endpoints:
        e.adapter = "openai"
        e.base_url = "https://example.invalid"

    def handler(_):
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 17},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = run(c, tmp_path / "overrun", client=client)
    assert len(result["requests"]) == 1
    assert result["stop_reason"].startswith("reported usage")
    with pytest.raises(ValueError, match="Usage exceeded"):
        run(c, tmp_path / "overrun", resume=True)


def test_duplicate_response_ids(tmp_path):
    c = cfg()
    c.sampling.repeats[0] = 2
    for e in c.endpoints:
        e.adapter = "openai"
        e.base_url = "https://example.invalid"
    with httpx.Client(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"id": "same-id", "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}]},
            )
        )
    ) as client:
        result = run(c, tmp_path, client=client)
    assert result["request_counts"] == {"ok": 3, "cache_suspected": 3}
    assert all(p["verdict"] == "inconclusive" for p in result["analysis"]["0"]["pairs"])


def test_cli_installed_commands(tmp_path):
    command = [sys.executable, "-m", "tmb.cli"]
    result = subprocess.run(
        command + ["benchmark", "--config", "examples/mock.yaml", "--level", "0", "--output", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    report = (tmp_path / "report.md").read_bytes()
    result = subprocess.run(
        command + ["report", str(tmp_path / "run.json")], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    assert report == (tmp_path / "report.md").read_bytes()
    result = subprocess.run(
        command + ["benchmark", "--config", "examples/mock.yaml", "--dry-run"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert json.loads(result.stdout)["requests"] == 99


def test_atomic_manifest_retries_transient_lock_without_api_retry(tmp_path, monkeypatch):
    real_replace = Path.replace
    attempts = []

    def locked_once(path, target):
        attempts.append(target)
        if len(attempts) < 3:
            raise PermissionError("temporary reader lock")
        return real_replace(path, target)

    monkeypatch.setattr(Path, "replace", locked_once)
    monkeypatch.setattr("tmb.runner.time.sleep", lambda _: None)
    destination = tmp_path / "run.json"
    destination.write_text('{"old": true}')
    atomic_json(destination, {"new": True})
    assert len(attempts) == 3
    assert json.loads(destination.read_text()) == {"new": True}


def test_atomic_manifest_permanent_lock_is_bounded_and_preserves_old_file(tmp_path, monkeypatch):
    attempts = []

    def locked(path, target):
        attempts.append(target)
        raise PermissionError("persistent lock")

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr("tmb.runner.time.sleep", lambda _: None)
    destination = tmp_path / "run.json"
    destination.write_text('{"old": true}')
    with pytest.raises(PermissionError):
        atomic_json(destination, {"new": True})
    assert len(attempts) == 10
    assert json.loads(destination.read_text()) == {"old": True}
