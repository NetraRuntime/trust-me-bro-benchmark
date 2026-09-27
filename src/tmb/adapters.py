"""Adapters return normalized observations; no response bodies enter error logs."""

import os
import random
import re
import time
from datetime import UTC, datetime
from typing import Protocol

import httpx

from .probes import digest


def now():
    return datetime.now(UTC).isoformat()


def redact(value, secrets=()):
    if isinstance(value, dict):
        return {k: redact(v, secrets) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"(?i)\bBearer\s+\S+", "Bearer [REDACTED]", value)
        return re.sub(r"\bsk[-_][A-Za-z0-9_-]{12,}", "[REDACTED]", value)
    return value


def payload(endpoint, probe, settings, level, repeat):
    body = {
        "model": endpoint.model,
        "messages": [{"role": probe.role, "content": probe.prompt}],
        "max_tokens": settings.max_tokens[level],
        "temperature": settings.temperature,
        "top_p": settings.top_p,
        "stream": False,
    }
    if settings.request_seed is not None:
        body["seed"] = settings.request_seed + repeat
    for name in endpoint.unsupported_controls:
        body.pop(name, None)
    if endpoint.provider:
        body["provider"] = {"only": [endpoint.provider], "allow_fallbacks": False, "require_parameters": True}
    if endpoint.reasoning_effort is not None:
        body["reasoning_effort"] = endpoint.reasoning_effort
    if endpoint.reasoning_enabled is not None:
        body["reasoning"] = {"enabled": endpoint.reasoning_enabled}
    return body


class Adapter(Protocol):
    def sample(self, endpoint, body: dict, sample_id: str) -> dict: ...


class MockAdapter:
    def sample(self, endpoint, body, sample_id):
        rng = random.Random(int(digest(sample_id), 16))
        text = rng.choice(["1", "2"]) if endpoint.mock_behavior == "a" else rng.choice(["8", "9"])
        if endpoint.mock_behavior in {"choice_a", "choice_b"}:
            text = (
                rng.choice(["A"] * 9 + ["B"])
                if endpoint.mock_behavior == "choice_a"
                else rng.choice(["C"] * 9 + ["B"])
            )
        status = {"error": "transport_error", "truncated": "truncated"}.get(endpoint.mock_behavior, "ok")
        return {
            "status": status,
            "text": text,
            "response_id": f"mock-{sample_id}",
            "returned_model": endpoint.model,
            "finish_reason": "length" if status == "truncated" else "stop",
            "usage": {"prompt_tokens": 20, "completion_tokens": 1},
            "latency_seconds": 0,
            "timestamp": now(),
            "controls": "synthetic fixture",
        }


class OpenAIAdapter:
    def __init__(self, client: httpx.Client):
        self.client = client

    def sample(self, endpoint, body, sample_id):
        key = os.environ.get(endpoint.api_key_env, "") if endpoint.api_key_env else ""
        result = {"timestamp": now(), "usage": None, "controls": "requested; compliance unverified"}
        if endpoint.api_key_env and not key:
            return result | {"status": "missing_api_key"}
        headers = {"Cache-Control": "no-cache"}
        if key:
            headers["Authorization"] = f"Bearer {key}"
        start = time.monotonic()
        try:
            response = self.client.post(
                endpoint.base_url.rstrip("/") + "/chat/completions", json=body, headers=headers
            )
            result.update(latency_seconds=time.monotonic() - start, http_status=response.status_code)
            if response.status_code != 200:
                return result | {"status": "http_error"}
            data = response.json()
            metadata_fields = ("id", "model", "system_fingerprint", "provider")
            if any(data.get(k) is not None and not isinstance(data[k], str) for k in metadata_fields):
                return result | {"status": "invalid_response"}
            choice = data["choices"][0]
            message = choice["message"]
            text = message.get("content")
            if text is None:
                text = ""
            if not isinstance(text, str):
                return result | {"status": "invalid_response"}
            finish = choice.get("finish_reason")
            if finish is not None and not isinstance(finish, str):
                return result | {"status": "invalid_response"}
            status = "ok"
            if message.get("refusal") or finish == "content_filter":
                status = "refusal"
            elif finish == "length":
                status = "truncated"
            elif not text.strip():
                status = "empty"
            elif finish != "stop":
                status = "unexpected_finish"
            # Cached prompt/prefix tokens do NOT imply a cached completion.
            if response.headers.get("x-cache", "").lower().startswith("hit"):
                status = "cache_suspected"
            usage = data.get("usage")
            if isinstance(usage, dict):
                usage = {
                    k: v
                    for k, v in usage.items()
                    if k in {"prompt_tokens", "completion_tokens", "total_tokens"}
                    and isinstance(v, int)
                    and not isinstance(v, bool)
                    and v >= 0
                }
            else:
                usage = None
            return result | {
                "status": status,
                "text": text,
                "finish_reason": finish,
                "response_id": data.get("id"),
                "returned_model": data.get("model"),
                "system_fingerprint": data.get("system_fingerprint"),
                "provider": data.get("provider"),
                "usage": usage,
            }
        except httpx.TimeoutException:
            return result | {"status": "timeout", "latency_seconds": time.monotonic() - start}
        except httpx.HTTPError:
            return result | {"status": "transport_error", "latency_seconds": time.monotonic() - start}
        except (ValueError, KeyError, TypeError, IndexError, AttributeError):
            return result | {"status": "invalid_response", "latency_seconds": time.monotonic() - start}
