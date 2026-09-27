import json

import pytest

from tmb.adapters import MockAdapter
from tmb.config import load_config
from tmb.datasets import load_dataset
from tmb.demo import prepare_demo


def test_demo_fixtures_are_reproducible_and_never_live(tmp_path):
    a, b = tmp_path / "first", tmp_path / "second"
    config, data = prepare_demo(a)
    assert prepare_demo(b)[1] == data
    assert len(data["items"]) == 300
    assert load_dataset(a / "dataset.json") == data
    assert load_config(a / "providers.yaml") == config
    assert all(e.adapter == "mock" and e.api_key_env is None for e in config.endpoints)
    assert config.consistency.margin == 0.12
    adapter = MockAdapter()
    for endpoint in config.endpoints:
        samples = {adapter.sample(endpoint, {}, str(i))["text"] for i in range(100)}
        assert samples == ({"B", "C"} if endpoint.role == "different_model_control" else {"A", "B"})
    assert "synthetic-demo" in json.dumps(data)
    with pytest.raises(ValueError, match="empty"):
        prepare_demo(a)
