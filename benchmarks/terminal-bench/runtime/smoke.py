"""Exercise the pinned Harbor/LiteLLM stack against a local fake API; costs $0."""

import asyncio
import hashlib
import json
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import httpx
from harbor.agents.installed.base import NonZeroAgentExitCodeError
from harbor.agents.terminus_2.terminus_2 import Terminus2
from harbor.models.job.config import JobConfig
from litellm.exceptions import RateLimitError

from tmb.terminal_agent import BoundedTerminus2
from tmb.terminal_guard import Ledger
from tmb.terminal_pilot import harbor_config
from tmb.terminal_proxy import Gateway, make_server


async def run(root):
    route = {
        "model": "fake/model",
        "base_url": "https://openrouter.ai/api/v1",
        "provider": "fake",
        "expected_response_provider": "Fake",
        "input_per_million": 1,
        "output_per_million": 2,
        "price_checked_at_utc": datetime.now(UTC).isoformat(),
    }
    ledger = Ledger(root / "ledger.db")
    ledger.episode("smoke", route)
    calls = []

    def upstream(request):
        payload = json.loads(request.content)
        assert payload["provider"]["only"] == ["fake"]
        assert payload["provider"]["allow_fallbacks"] is False
        assert payload["max_tokens"] <= 8192
        calls.append(payload)
        if len(calls) == 1:
            return httpx.Response(503, json={"error": {"message": "synthetic failure"}})
        return httpx.Response(
            200,
            json={
                "id": "fake",
                "object": "chat.completion",
                "created": 1,
                "model": "fake/model",
                "provider": "Fake",
                "choices": [
                    {"index": 0, "message": {"role": "assistant", "content": "ok"}, "finish_reason": "stop"}
                ],
                "usage": {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(upstream))
    gateway = Gateway(ledger, "smoke", route, "fake-upstream-key", client=client)
    server = make_server(gateway, "local-test-token")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}/v1"
        config = harbor_config("mvcc-lsm-compaction", "smoke", base, str(root))
        JobConfig.model_validate(config)
        options = config["agents"][0]["kwargs"]
        options["llm_kwargs"]["api_key"] = "local-test-token"
        agent = BoundedTerminus2(logs_dir=root / "agent", model_name="openai/tmb", **options)
        result = await agent._llm.call("hello", max_tokens=128)
        assert result.content == "ok"
        attempts = ledger.snapshot()["attempts"]
        assert len(attempts) == len(calls) == 2
        assert [a["state"] for a in attempts] == ["unknown", "settled"]
        # Authentication failure never reaches the fake upstream.
        async with httpx.AsyncClient() as local:
            denied = await local.post(base + "/chat/completions", json={"model": "tmb"})
            assert denied.status_code == 401
        assert len(calls) == 2

        # Budget stop conversion lets the official single-step verifier run.
        async def stopped(*_args, **_kwargs):
            raise RateLimitError("local budget gate", llm_provider="openai", model="tmb")

        with patch.object(Terminus2, "run", stopped):
            try:
                await agent.run("instruction", None, None)
            except NonZeroAgentExitCodeError:
                pass
            else:
                raise AssertionError("Budget stop did not preserve verification")
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        client.close()
    lock = Path(__file__).with_name("uv.lock")
    print(
        json.dumps(
            {
                "status": "passed",
                "upstream": "fake_only",
                "paid_requests": 0,
                "attempts_observed": len(calls),
                "lock_sha256": hashlib.sha256(lock.read_bytes()).hexdigest(),
            }
        )
    )


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as tmp:
        asyncio.run(run(Path(tmp)))
