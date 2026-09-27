"""Deterministic synthetic fixtures for a no-network end-to-end demonstration."""

import json
from pathlib import Path

import yaml

from .config import Config
from .datasets import PROTOCOL
from .probes import digest


def prepare_demo(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if any(output.iterdir()):
        raise ValueError("Demo output must be empty; choose a new directory")
    endpoints = [
        {
            "name": name,
            "adapter": "mock",
            "base_url": "mock://fixture",
            "model": "fixture",
            "mock_behavior": "choice_b" if name == "different" else "choice_a",
            "role": "different_model_control" if name == "different" else "candidate",
        }
        for name in ("reference", "reference_repeat", "candidate", "different")
    ]
    config = Config.model_validate(
        {
            "claimed_model": "synthetic-fixture",
            "reference": "reference",
            "endpoints": endpoints,
            "consistency": {"baseline": ["reference", "reference_repeat"], "margin": 0.12},
            "sampling": {"bootstrap": 4000, "permutations": 999},
            "limits": {"max_requests": 2400, "max_total_tokens": 2000000},
        }
    )
    data = {
        "protocol": PROTOCOL,
        "dataset": "synthetic-demo",
        "revision": "fixture-v1",
        "items": [
            {
                "id": str(i),
                "category": f"synthetic-{i % 3}",
                "question": f"Synthetic fixture {i}: choose an option.",
                "options": ["first", "second", "third"],
                "answer": "A",
            }
            for i in range(300)
        ],
    }
    data["content_hash"] = digest(data)
    (output / "providers.yaml").write_text(
        yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False), encoding="utf8"
    )
    (output / "dataset.json").write_text(json.dumps(data, indent=2), encoding="utf8")
    return config, data
