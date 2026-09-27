"""Strict, public configuration. Credentials are resolved only by adapters."""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Prices(Strict):
    input_per_million: float = Field(ge=0)
    output_per_million: float = Field(ge=0)


class Endpoint(Strict):
    role: Literal["candidate", "different_model_control"] = "candidate"
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,48}$")
    base_url: str
    model: str
    api_key_env: str | None = Field(default=None, pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    adapter: Literal["openai", "mock"] = "openai"
    mock_behavior: Literal["a", "b", "error", "truncated"] = "a"
    unsupported_controls: list[Literal["temperature", "top_p", "seed"]] = []
    provider: str | None = None
    reasoning_effort: Literal["none", "minimal", "low", "medium", "high"] | None = None
    reasoning_enabled: bool | None = None
    tokenizer: str = "unknown"
    chat_template: str = "unknown"
    checkpoint_revision: str = "unknown"
    quantization: str = "unknown"
    serving_software: str = "unknown"
    prices: Prices | None = None

    @model_validator(mode="after")
    def safe_url(self):
        if self.reasoning_enabled is not None and self.reasoning_effort is not None:
            raise ValueError("Choose reasoning_enabled or reasoning_effort, not both")
        u = urlsplit(self.base_url)
        if u.username or u.password or u.query or u.fragment:
            raise ValueError("URLs must not contain credentials, query strings, or fragments")
        if self.adapter == "openai" and (u.scheme not in {"http", "https"} or not u.hostname):
            raise ValueError("OpenAI endpoints require an HTTP(S) URL")
        if (
            self.adapter == "openai"
            and u.scheme == "http"
            and u.hostname not in {"localhost", "127.0.0.1", "::1"}
        ):
            raise ValueError("Remote endpoints require HTTPS; HTTP is allowed only on loopback")
        return self


class Sampling(Strict):
    temperature: float = Field(default=1, ge=0, le=2)
    top_p: float = Field(default=1, gt=0, le=1)
    request_seed: int | None = None
    random_seed: int = Field(default=2026, ge=0)
    repeats: dict[int, int] = {0: 1, 1: 8, 2: 2, 3: 20}
    max_tokens: dict[int, int] = {0: 16, 1: 16, 2: 128, 3: 128}
    permutations: int = Field(default=999, ge=99, le=99999)
    bootstrap: int = Field(default=300, ge=100, le=10000)
    min_samples: int = Field(default=8, ge=4)
    alpha: float = Field(default=0.05, gt=0, lt=1)

    @model_validator(mode="after")
    def levels(self):
        for values in (self.repeats, self.max_tokens):
            if set(values) != {0, 1, 2, 3} or any(v < 1 or v > 100000 for v in values.values()):
                raise ValueError("repeats/max_tokens must specify positive limits for levels 0,1,2,3")
        return self


class Limits(Strict):
    max_requests: int = Field(default=1000, ge=1)
    max_total_tokens: int = Field(default=200000, ge=1)
    max_cost_usd: float | None = Field(default=None, gt=0)
    timeout_seconds: float = Field(default=60, gt=0, le=600)


class Config(Strict):
    claimed_model: str
    endpoints: list[Endpoint] = Field(min_length=2)
    reference: str | None = None
    sampling: Sampling = Field(default_factory=Sampling)
    limits: Limits = Field(default_factory=Limits)
    probes_file: str | None = None

    @model_validator(mode="after")
    def providers(self):
        names = [e.name for e in self.endpoints]
        if len(set(names)) != len(names):
            raise ValueError("Endpoint names must be unique")
        if self.reference and self.reference not in names:
            raise ValueError("Reference must name a configured endpoint")
        if any(e.name == self.reference and e.role != "candidate" for e in self.endpoints):
            raise ValueError("A different-model control cannot be the claimed-checkpoint reference")
        if self.limits.max_cost_usd and any(e.prices is None for e in self.endpoints):
            raise ValueError("A cost limit requires prices for every endpoint")
        return self


def load_config(path: Path) -> Config:
    return Config.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
