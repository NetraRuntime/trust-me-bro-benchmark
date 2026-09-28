import pytest

from tmb.terminal_plan import build_plan


def inventory():
    return {
        "revision": "fixed",
        "tasks": [
            {"name": "cpu", "environment": {"gpus": 0}, "verifier": {}},
            {"name": "agent-gpu", "environment": {"gpus": 1}, "verifier": {}},
            {"name": "verifier-gpu", "environment": {}, "verifier": {"environment": {"gpus": 1}}},
        ],
    }


def routes():
    return [{"model": "m", "name": "a", "input_per_million": 1, "output_per_million": 2}]


def test_cpu_selection_excludes_verifier_and_agent_gpus():
    plan = build_plan(inventory(), routes(), task_count=1)
    assert plan["selected_tasks"] == ["cpu"]
    assert plan["excluded_gpu_tasks"] == ["agent-gpu", "verifier-gpu"]
    assert plan["episodes"] == 3
    assert plan["cost_scenarios"][0]["api_usd_total"] == 0.42


def test_selection_independent_of_input_order_and_scales_cost():
    inv = inventory()
    first = build_plan(inv, routes(), task_count=2, cpu_only=False)
    inv["tasks"].reverse()
    second = build_plan(inv, routes(), task_count=2, cpu_only=False)
    assert first == second
    assert first["cost_scenarios"][0]["api_usd_total"] == 0.84


@pytest.mark.parametrize("count,repeats", [(0, 1), (1, 0), (True, 1), (1.5, 1), (4, 1)])
def test_invalid_counts_fail(count, repeats):
    with pytest.raises(ValueError):
        build_plan(inventory(), routes(), task_count=count, repeats=repeats)


@pytest.mark.parametrize("price", [-1, float("nan"), float("inf"), True])
def test_invalid_price_fails(price):
    data = routes()
    data[0]["input_per_million"] = price
    with pytest.raises(ValueError):
        build_plan(inventory(), data, task_count=1)


def test_duplicate_routes_fail():
    with pytest.raises(ValueError):
        build_plan(inventory(), routes() * 2, task_count=1)
