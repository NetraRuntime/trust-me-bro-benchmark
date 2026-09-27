import json

import httpx
import pytest

from tmb.adapters import OpenAIAdapter, payload, redact
from tmb.config import Endpoint, Sampling
from tmb.probes import PUBLIC


@pytest.mark.parametrize(
    "finish,content,refusal,status",
    [
        ("stop", "OK", None, "ok"),
        ("length", "O", None, "truncated"),
        ("stop", "", None, "empty"),
        ("stop", "", "denied", "refusal"),
        ("content_filter", "", None, "refusal"),
        (None, "yes", None, "unexpected_finish"),
    ],
)
def test_normalized_response(finish, content, refusal, status):
    def handler(request):
        assert str(request.url) == "https://example.invalid/v1/chat/completions"
        return httpx.Response(
            200,
            json={
                "id": "id-1",
                "model": "m",
                "choices": [{"message": {"content": content, "refusal": refusal}, "finish_reason": finish}],
                "usage": {"prompt_tokens": 5, "completion_tokens": 1, "secret": "not saved"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        row = OpenAIAdapter(client).sample(
            Endpoint(name="a", base_url="https://example.invalid/v1", model="m"), {}, "1"
        )
    assert row["status"] == status
    assert "secret" not in row["usage"]


def test_http_error_body_not_persisted(monkeypatch):
    monkeypatch.setenv("TEST_KEY", "secret-in-env")

    def handler(request):
        assert request.headers["Authorization"] == "Bearer secret-in-env"
        return httpx.Response(400, text="secret-in-env invalid parameter")

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        row = OpenAIAdapter(client).sample(
            Endpoint(name="a", base_url="https://example.invalid", model="m", api_key_env="TEST_KEY"), {}, "1"
        )
    assert row["status"] == "http_error"
    assert "secret-in-env" not in json.dumps(row)


def test_controls_and_pinned_routing():
    ep = Endpoint(
        name="a",
        base_url="https://example.invalid",
        model="m",
        provider="chosen",
        unsupported_controls=["seed"],
    )
    body = payload(ep, PUBLIC[0], Sampling(request_seed=5), 0, 3)
    assert "seed" not in body
    assert body["provider"] == {"only": ["chosen"], "allow_fallbacks": False, "require_parameters": True}
    assert redact({"text": "hello secret-value sk-test_12345678901234"}, ["secret-value"]) == {
        "text": "hello [REDACTED] [REDACTED]"
    }


def test_explicit_reasoning_control():
    ep = Endpoint(name="a", base_url="https://example.invalid", model="m", reasoning_enabled=False)
    assert payload(ep, PUBLIC[0], Sampling(), 0, 0)["reasoning"] == {"enabled": False}
    with pytest.raises(ValueError):
        Endpoint(
            name="a",
            base_url="https://example.invalid",
            model="m",
            reasoning_enabled=False,
            reasoning_effort="none",
        )


@pytest.mark.parametrize(
    "url",
    ["https://user:password@example.invalid", "https://example.invalid?key=secret", "http://remote.invalid"],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        Endpoint(name="a", base_url=url, model="m")
