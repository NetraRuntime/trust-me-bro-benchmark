import asyncio
import json
import sys
import threading
import time

import pytest
import yaml

from tmb.datasets import PROTOCOL
from tmb.probes import digest
from tmb.service import BenchmarkService


def inputs(root, live=False):
    cfg = {
        "claimed_model": "fixture",
        "endpoints": [
            {
                "name": name,
                "base_url": "https://example.invalid/v1",
                "model": "fixture",
                "adapter": "openai" if live else "mock",
                "api_key_env": "TMB_TEST_KEY",
            }
            for name in ("a", "b")
        ],
        "sampling": {"permutations": 99, "bootstrap": 100},
    }
    (root / "config.yaml").write_text(yaml.safe_dump(cfg))
    data = {
        "protocol": PROTOCOL,
        "revision": "0" * 40,
        "items": [
            {
                "id": str(i),
                "category": "fixture",
                "question": "Choose one",
                "options": ["one", "two"],
                "answer": "A",
            }
            for i in range(2)
        ],
    }
    data["content_hash"] = digest(data)
    (root / "dataset.json").write_text(json.dumps(data))
    return cfg


def test_service_workspace_budget_live_gate_and_redaction(tmp_path, monkeypatch):
    inputs(tmp_path, live=True)
    monkeypatch.setenv("TMB_TEST_KEY", "fixture-secret-do-not-expose")
    service = BenchmarkService(tmp_path, max_requests=1)
    try:
        result = service.plan("config.yaml", "dataset.json")
        assert not result["can_start"]
        assert len(result["blockers"]) == 3
        assert "fixture-secret" not in json.dumps(result)
        with pytest.raises(ValueError):
            service.start("config.yaml", "dataset.json", "output")
        with pytest.raises(ValueError):
            service.path("../escape", exists=False)
        with pytest.raises(ValueError):
            service.path(str(tmp_path.parent / "escape"), exists=False)
        assert not (tmp_path / "output").exists()
    finally:
        service.close()


def test_service_background_resume_and_report(tmp_path):
    inputs(tmp_path)
    service = BenchmarkService(tmp_path)
    try:
        job = service.start("config.yaml", "dataset.json", "output")
        deadline = time.monotonic() + 10
        while service.status(job["job_id"])["state"] in {"queued", "running"}:
            assert time.monotonic() < deadline
            time.sleep(0.01)
        status = service.status(job["job_id"])
        assert status["state"] == "completed" and status["completed"] == 8
        # Legacy mock emits digits; parser failures must remain visible, not be success answers.
        assert status["statuses"] == {"unparseable": 8}
        report = service.report("output/run.json")
        assert "inconclusive" in report["report_markdown"]
        with pytest.raises(ValueError):
            service.start("config.yaml", "dataset.json", "output")
        service.start("config.yaml", "dataset.json", "output", resume=True)
    finally:
        service.close()
    assert len(json.loads((tmp_path / "output/run.json").read_text())["requests"]) == 8


def test_symlink_escape_is_rejected(tmp_path):
    outside = tmp_path.parent / (tmp_path.name + "-outside.json")
    outside.write_text("{}")
    try:
        (tmp_path / "link.json").symlink_to(outside)
    except OSError:
        pytest.skip("Host does not permit symlink creation")
    service = BenchmarkService(tmp_path)
    try:
        with pytest.raises(ValueError):
            service.path("link.json")
    finally:
        service.close()


def test_active_job_collision_and_background_error_are_explicit(tmp_path, monkeypatch):
    import tmb.service

    inputs(tmp_path)
    started, finish = threading.Event(), threading.Event()

    def blocked(*args, **kwargs):
        started.set()
        assert finish.wait(5)
        raise RuntimeError("fixture-secret-in-exception")

    monkeypatch.setattr(tmb.service, "compare_dataset", blocked)
    service = BenchmarkService(tmp_path)
    try:
        job = service.start("config.yaml", "dataset.json", "output")
        assert started.wait(5)
        with pytest.raises(ValueError, match="active"):
            service.start("config.yaml", "dataset.json", "other-output")
    finally:
        finish.set()
        service.close()
    status = service.status(job["job_id"])
    assert status["state"] == "failed"
    assert "fixture-secret" not in json.dumps(status)


def test_stdio_discovery_plan_job_report_and_safe_errors(tmp_path):
    pytest.importorskip("mcp")
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    inputs(tmp_path)

    async def exercise():
        params = StdioServerParameters(
            command=sys.executable, args=["-m", "tmb.mcp_server", "--root", str(tmp_path)]
        )
        async with stdio_client(params) as streams, ClientSession(*streams) as session:
            await session.initialize()
            listing = await session.list_tools()
            assert {t.name for t in listing.tools} == {
                "plan_dataset",
                "start_dataset",
                "run_status",
                "read_report",
            }
            planned = await session.call_tool(
                "plan_dataset", {"config_path": "config.yaml", "dataset_path": "dataset.json"}
            )
            assert planned.structured_content["can_start"]
            job = await session.call_tool(
                "start_dataset",
                {"config_path": "config.yaml", "dataset_path": "dataset.json", "output": "stdio-run"},
            )
            jid = job.structured_content["job_id"]
            for _ in range(100):
                status = await session.call_tool("run_status", {"job_id": jid})
                if status.structured_content["state"] == "completed":
                    break
                await asyncio.sleep(0.02)
            else:
                pytest.fail("MCP job did not complete")
            report = await session.call_tool("read_report", {"manifest": "stdio-run/run.json"})
            assert "inconclusive" in report.structured_content["report_markdown"]
            failure = await session.call_tool("read_report", {"manifest": "../secret.txt"})
            assert "error" in failure.structured_content
            assert "secret.txt" not in str(failure)
            resource = await session.read_resource("tmb://methodology")
            assert "identity" in resource.contents[0].text

    asyncio.run(exercise())
