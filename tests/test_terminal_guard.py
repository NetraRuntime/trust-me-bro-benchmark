import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from tmb.terminal_catalog import inspect_routes, prices
from tmb.terminal_guard import BudgetStop, Ledger, nano_usd, prepare_request
from tmb.terminal_pilot import child_environment, harbor_config
from tmb.terminal_proxy import Gateway, validate_route


@pytest.fixture
def route():
    return {
        "model": "model",
        "base_url": "https://openrouter.ai/api/v1",
        "provider": "test/fp8",
        "expected_response_provider": "Test",
        "api_key_env": "TEST_KEY",
        "input_per_million": 1,
        "output_per_million": 2,
        "price_checked_at_utc": datetime.now(UTC).isoformat(),
    }


@pytest.fixture
def ledger(tmp_path, route):
    ledger = Ledger(tmp_path / "ledger.db")
    ledger.episode("episode", route)
    return ledger


def body():
    return {"model": "tmb", "messages": [{"role": "user", "content": "hello"}], "max_tokens": 8192}


def response(usage=None, provider="Test"):
    return {
        "model": "model",
        "provider": provider,
        "choices": [
            {"index": 0, "message": {"role": "assistant", "content": "hello"}, "finish_reason": "stop"}
        ],
        "usage": usage or {"prompt_tokens": 20, "completion_tokens": 30},
    }


def test_unknown_reservation_survives_restart_and_retry(ledger):
    a, _ = ledger.reserve("episode", 50_000, 8192, "first")
    ledger.settle(a)
    reopened = Ledger(ledger.path)
    b, limit = reopened.reserve("episode", 50_000, 8192, "retry")
    assert b != a and limit == 8192
    _, limit = reopened.reserve("episode", 50_000, 8192, "retry2")
    assert limit == 3616
    with pytest.raises(BudgetStop):
        reopened.reserve("episode", 1, 1, "retry3")
    assert [x["state"] for x in reopened.snapshot()["attempts"]] == ["unknown", "reserved", "reserved"]


def test_success_releases_only_verified_usage_and_no_cache_discount(ledger):
    a, _ = ledger.reserve("episode", 5000, 100, "first")
    ledger.settle(
        a,
        {
            "prompt_tokens": 100,
            "completion_tokens": 50,
            "prompt_tokens_details": {"cached_tokens": 100},
            "completion_tokens_details": {"reasoning_tokens": 40},
        },
    )
    record = ledger.snapshot()["attempts"][0]
    assert record["charged"] == nano_usd("0.0002")
    assert record["input_used"] == 100 and record["output_used"] == 50
    with pytest.raises(BudgetStop):
        ledger.settle(a, {"prompt_tokens": 0, "completion_tokens": 0})


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {},
        {"prompt_tokens": True, "completion_tokens": 0},
        {"prompt_tokens": -1, "completion_tokens": 0},
    ],
)
def test_missing_or_invalid_usage_keeps_reservation(ledger, usage):
    a, _ = ledger.reserve("episode", 100, 100, "x")
    ledger.settle(a, usage)
    record = ledger.snapshot()["attempts"][0]
    assert record["charged"] == record["reserved"]
    assert record["state"] == "unknown"


@pytest.mark.parametrize(
    "usage",
    [
        {"prompt_tokens": 101, "completion_tokens": 1},
        {"prompt_tokens": 1, "completion_tokens": 101},
        {"prompt_tokens": 1, "completion_tokens": 1, "cost": 1},
    ],
)
def test_underreservation_halts_campaign_durably(ledger, usage):
    a, _ = ledger.reserve("episode", 100, 100, "x")
    with pytest.raises(BudgetStop):
        ledger.settle(a, usage)
    restarted = Ledger(ledger.path)
    assert restarted.snapshot()["halt"]
    with pytest.raises(BudgetStop):
        restarted.reserve("episode", 1, 1, "next")


def test_concurrent_requests_cannot_overdraw_episode(ledger):
    def reserve(_):
        try:
            return ledger.reserve("episode", 100_000, 1, "race")[0]
        except BudgetStop:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(reserve, range(8)))
    assert sum(x is not None for x in results) == 1


def test_pilot_dollar_cap_applies_across_episodes(tmp_path, route):
    ledger = Ledger(tmp_path / "ledger.db", pilot_usd="0.005")
    for i in range(2):
        ledger.episode(str(i), route)
    ledger.reserve("0", 1000, 2000, "first")
    with pytest.raises(BudgetStop):
        ledger.reserve("1", 1, 1, "next")


def test_main_cannot_spend_pilot_or_withheld_budget(tmp_path, route):
    ledger = Ledger(tmp_path / "ledger.db", total_usd="1", withheld_usd="0.98", pilot_usd="0.01")
    ledger.episode("main", route, phase="main")
    ledger.reserve("main", 2000, 4000, "first")
    with pytest.raises(BudgetStop):
        ledger.reserve("main", 1, 1, "next")


def test_policy_and_episode_are_immutable(ledger, route):
    with pytest.raises(BudgetStop):
        Ledger(ledger.path, withheld_usd="0")
    with pytest.raises(BudgetStop):
        ledger.episode("episode", {**route, "provider": "different"})
    ledger.close("episode")
    with pytest.raises(BudgetStop):
        ledger.episode("episode", route)


@pytest.mark.parametrize("value", ["NaN", "Infinity", -1])
def test_bad_prices_fail_closed(tmp_path, value):
    with pytest.raises(ValueError):
        Ledger(tmp_path / "ledger.db", total_usd=value)


@pytest.mark.parametrize(
    "change",
    [
        {"stream": True},
        {"n": 2},
        {"tools": []},
        {"model": "other"},
        {"max_tokens": -1},
        {"messages": [{"role": "user", "content": []}]},
    ],
)
def test_unbounded_request_features_rejected(route, change):
    with pytest.raises(ValueError):
        prepare_request({**body(), **change}, route)


def test_request_forces_route_and_output_cap(route):
    payload, bound, requested, digest = prepare_request(body(), route)
    assert payload["provider"] == {"only": ["test/fp8"], "allow_fallbacks": False, "require_parameters": True}
    assert bound > len(json.dumps(body()).encode())
    assert requested == 8192 and len(digest) == 64


def test_fake_api_retries_are_individually_reserved(ledger, route):
    calls = []

    def fake(request):
        calls.append(request)
        assert request.headers["authorization"] == "Bearer upstream-secret"
        if len(calls) == 1:
            return httpx.Response(503, text="secret must not be reflected")
        return httpx.Response(200, json=response())

    gateway = Gateway(
        ledger, "episode", route, "upstream-secret", client=httpx.Client(transport=httpx.MockTransport(fake))
    )
    status, data = gateway.complete(body())
    assert status == 502 and "secret" not in json.dumps(data)
    assert gateway.complete(body())[0] == 200
    attempts = ledger.snapshot()["attempts"]
    assert [x["state"] for x in attempts] == ["unknown", "settled"]
    assert len(calls) == 2 and "upstream-secret" not in json.dumps(ledger.snapshot())


def test_transport_ambiguity_keeps_reservation(ledger, route):
    def fake(request):
        raise httpx.ReadTimeout("secret", request=request)

    gateway = Gateway(
        ledger, "episode", route, "secret", client=httpx.Client(transport=httpx.MockTransport(fake))
    )
    assert gateway.complete(body())[0] == 502
    record = ledger.snapshot()["attempts"][0]
    assert record["state"] == "unknown" and record["charged"] == record["reserved"]


@pytest.mark.parametrize("status,provider", [(200, "Other"), (401, "Test"), (402, "Test")])
def test_route_and_account_failure_stop_further_network_calls(ledger, route, status, provider):
    calls = []

    def fake(request):
        calls.append(request)
        return httpx.Response(status, json=response(provider=provider))

    gateway = Gateway(
        ledger, "episode", route, "secret", client=httpx.Client(transport=httpx.MockTransport(fake))
    )
    for _ in range(2):
        with pytest.raises(BudgetStop):
            gateway.complete(body())
    assert len(calls) == 1


def test_stale_prices_and_redirect_targets_rejected(route):
    with pytest.raises(BudgetStop):
        validate_route({**route, "price_checked_at_utc": (datetime.now(UTC) - timedelta(days=2)).isoformat()})
    with pytest.raises(ValueError):
        validate_route({**route, "base_url": "http://untrusted.example"})


def test_wrong_response_model_halts_campaign(ledger, route):
    data = {**response(), "model": "wrong-model"}
    gateway = Gateway(
        ledger,
        "episode",
        route,
        "secret",
        client=httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=data))),
    )
    with pytest.raises(BudgetStop):
        gateway.complete(body())
    assert ledger.snapshot()["halt"] == "Returned model did not match pinned route"


def test_catalog_uses_maximum_time_rate_and_rejects_extra_billing():
    pricing = {"prompt": "0.000001", "completion": "0.000002", "overrides": [{"prompt": "0.000003"}]}
    assert prices(pricing) == {"input_per_million": "3.000000", "output_per_million": "2.000000"}
    with pytest.raises(ValueError):
        prices({**pricing, "request": "0.01"})


def test_catalog_preserves_unavailable_routes_and_float_noise(route):
    route = {**route, "name": "test", "price_source": "catalog", "output_per_million": 0.39999999999999997}
    endpoint = {
        "tag": "test/fp8",
        "provider_name": "Test",
        "status": 0,
        "pricing": {"prompt": "0.000001", "completion": "0.0000004"},
    }
    catalog = {"model": {"data": {"endpoints": [endpoint]}}}
    refreshed = inspect_routes([route], catalog, "now")
    assert refreshed["routes"][0]["price_changed"] is False
    endpoint["status"] = 1
    missing = inspect_routes([route], catalog, "now")
    assert len(missing["routes"]) == 1
    assert missing["routes"][0]["status"] == "missing_from_current_catalog"


def test_pilot_config_cannot_use_main_tasks_or_pass_upstream_keys(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("NETRA_API_KEY", "secret")
    assert "secret" not in json.dumps(child_environment("local-token"))
    assert child_environment("local-token")["PYTHON_DOTENV_DISABLED"] == "1"
    config = harbor_config("mvcc-lsm-compaction", "pilot", "http://127.0.0.1:1234/v1", "results/pilot")
    assert config["retry"]["max_retries"] == 0
    assert config["verifier"]["disable"] is False
    with pytest.raises(ValueError):
        harbor_config("roy-polymorph-cn", "main", "http://127.0.0.1:1234/v1", "results/pilot")
