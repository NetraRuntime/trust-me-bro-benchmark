"""Bounded concurrent blocks; durable journal before dispatch, no API retries."""

import json
import os
import random
import uuid
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

from . import __version__
from .adapters import MockAdapter, OpenAIAdapter, now, payload, redact
from .choice_analysis import analyze_choices
from .datasets import PARSER, parse_choice, question_prompt
from .probes import Probe, digest
from .runner import atomic_json, estimate, run_lock
from .validation import CONSISTENCY_METHOD, dataset_items, require_unseeded, validate_manifest


def dataset_plan(config, package, repeats, seed):
    require_unseeded(config)
    rng = random.Random(seed)
    jobs = []
    for repeat in range(repeats):
        items = list(package["items"])
        rng.shuffle(items)
        for item in items:
            endpoints = list(config.endpoints)
            rng.shuffle(endpoints)
            for endpoint in endpoints:
                inp = len(question_prompt(item).encode("utf8")) + 64
                out = config.sampling.max_tokens[3]
                jobs.append(
                    {
                        "id": f"{item['id']}:{repeat}:{endpoint.name}",
                        "question_id": item["id"],
                        "endpoint": endpoint.name,
                        "repeat": repeat,
                        "reserved_input_tokens": inp,
                        "reserved_output_tokens": out,
                        "reserved_cost_usd": (
                            inp * endpoint.prices.input_per_million + out * endpoint.prices.output_per_million
                        )
                        / 1e6
                        if endpoint.prices
                        else None,
                    }
                )
    return jobs


def compare_dataset(
    config,
    package,
    output,
    repeats=2,
    workers=1,
    resume=False,
    store_text=False,
    same_pair=None,
    client=None,
    progress=None,
):
    if repeats not in (2, 3, 4) or not 1 <= workers <= len(config.endpoints):
        raise ValueError("Use 2-4 repeats and workers between 1 and the endpoint count")
    require_unseeded(config)
    if config.probes_file:
        raise ValueError("Dataset comparison uses --dataset, not probes_file")
    endpoints = {e.name: e for e in config.endpoints}
    if config.consistency:
        if same_pair and set(same_pair) != set(config.consistency.baseline):
            raise ValueError("Same-configuration pair conflicts with consistency baseline")
        same_pair = list(config.consistency.baseline)
    if same_pair:
        if len(set(same_pair)) != 2 or not set(same_pair) <= endpoints.keys():
            raise ValueError("Same-configuration control must name two distinct configured endpoints")
        left, right = [endpoints[n].model_dump(exclude={"name", "prices"}) for n in same_pair]
        if left != right:
            raise ValueError("Same-configuration controls must have identical endpoint settings")
    items = dataset_items(package)
    protocol = {
        "items_hash": digest(items),
        "repeats": repeats,
        "workers": workers,
        "seed": config.sampling.random_seed,
        "permutations": config.sampling.permutations,
        "bootstrap": config.sampling.bootstrap,
        "alpha": config.sampling.alpha,
        "parser": PARSER,
        "prompt": "zero-shot-direct-choice-v1",
        "same_configuration_pair": same_pair,
        "schedule": "randomized question/endpoint blocks",
    }
    if config.consistency:
        protocol["consistency"] = config.consistency.model_dump(mode="json") | {
            "method": CONSISTENCY_METHOD,
        }
    secrets = [os.environ.get(e.api_key_env, "") for e in config.endpoints if e.api_key_env]
    safe_config = redact(config.model_dump(mode="json"), secrets)
    if not config.consistency:
        safe_config.pop("consistency", None)  # Preserve v1 manifest/resume fingerprints.
    fingerprint = digest([safe_config, package["content_hash"], protocol, store_text, __version__])
    jobs = dataset_plan(config, package, repeats, protocol["seed"])
    planned = estimate(jobs)
    if (
        len(jobs) > config.limits.max_requests
        or planned["input_token_reservation"] + planned["output_token_limit"] > config.limits.max_total_tokens
        or (
            config.limits.max_cost_usd is not None
            and planned["cost_estimate_usd"] > config.limits.max_cost_usd
        )
    ):
        raise ValueError(
            "Full dataset plan exceeds configured budget; adjust selection or limits before collection"
        )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    path = output / "run.json"
    with run_lock(output):
        if path.exists():
            if not resume:
                raise ValueError("Run exists; use a new directory or --resume")
            run = json.loads(path.read_text(encoding="utf8"))
            if run["protocol_hash"] != fingerprint:
                raise ValueError("Resume protocol differs from the recorded dataset/config/settings")
            validate_manifest(run, package, finalized=False)
            if run.get("stop_reason", "").startswith("reported usage"):
                raise ValueError("Usage exceeded reservation; start a new reviewed budget")
            for row in run["requests"]:
                if row["status"] == "in_flight":
                    row["status"] = "interrupted_unknown"
        elif resume:
            raise ValueError("No dataset run to resume")
        else:
            run = {
                "kind": "choice-dataset",
                "schema_version": 2,
                "tool_version": __version__,
                "run_id": str(uuid.uuid4()),
                "started_at": now(),
                "config": safe_config,
                "protocol": protocol,
                "protocol_hash": fingerprint,
                "dataset": {k: v for k, v in package.items() if k != "items"},
                "store_text": store_text,
                "items": items,
                "planned": planned,
                "requests": [],
            }
        item_map = {i["id"]: i for i in package["items"]}
        done = {r["id"] for r in run["requests"]}
        pending = [j for j in jobs if j["id"] not in done]

        # IDs are checked across aliases of the same endpoint, including the repeat control.
        def identity(name):
            e = endpoints[name]
            return e.base_url, e.model, e.provider

        seen = {(identity(r["endpoint"]), r["response_id"]) for r in run["requests"] if r.get("response_id")}
        owned = client is None
        if owned:
            client = httpx.Client(timeout=config.limits.timeout_seconds, follow_redirects=False)
        adapters = {"mock": MockAdapter(), "openai": OpenAIAdapter(client)}
        try:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                for start in range(0, len(pending), len(config.endpoints)):
                    block = pending[start : start + len(config.endpoints)]
                    dispatched = []
                    for job in block:
                        item = item_map[job["question_id"]]
                        e = endpoints[job["endpoint"]]
                        probe = Probe(id="q" + item["id"], level=3, prompt=question_prompt(item))
                        body = payload(e, probe, config.sampling, 3, job["repeat"])
                        row = job | {
                            "status": "in_flight",
                            "requested_at": now(),
                            "requested_settings": {k: v for k, v in body.items() if k != "messages"},
                        }
                        run["requests"].append(row)
                        dispatched.append((row, e, body, item))
                    atomic_json(path, redact(run, secrets))
                    futures = {
                        pool.submit(adapters[e.adapter].sample, e, body, row["id"]): (row, e, item)
                        for row, e, body, item in dispatched
                    }
                    for future in as_completed(futures):
                        row, e, item = futures[future]
                        try:
                            result = redact(future.result(), secrets)
                        except Exception:  # noqa: BLE001 -- preserve unknown delivery without exposing exception data
                            # Unknown delivery: do not retry or serialize exception text.
                            result = {"status": "adapter_error_unknown", "timestamp": now(), "usage": None}
                        text = result.pop("text", None)
                        if text is not None:
                            result["answer_hash"] = digest(text)
                            if store_text:
                                result["text"] = text
                        if result["status"] == "ok":
                            result["choice"] = parse_choice(text or "", len(item["options"]))
                            if result["choice"] is None:
                                result["status"] = "unparseable"
                        rid = result.get("response_id")
                        if rid and (identity(e.name), rid) in seen:
                            result["status"] = "cache_suspected"
                        if rid:
                            seen.add((identity(e.name), rid))
                        row.update(result)
                        usage = row.get("usage") or {}
                        actual_cost = (
                            (
                                usage.get("prompt_tokens", 0) * e.prices.input_per_million
                                + usage.get("completion_tokens", 0) * e.prices.output_per_million
                            )
                            / 1e6
                            if e.prices
                            else 0
                        )
                        if (
                            max(
                                usage.get("total_tokens", 0),
                                usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
                            )
                            > row["reserved_input_tokens"] + row["reserved_output_tokens"]
                            or usage.get("completion_tokens", 0) > row["reserved_output_tokens"]
                            or actual_cost > (row["reserved_cost_usd"] or float("inf"))
                        ):
                            run["stop_reason"] = "reported usage exceeded reservation; no further blocks sent"
                        atomic_json(path, redact(run, secrets))
                    if progress:
                        progress(len(run["requests"]), len(jobs))
                    if run.get("stop_reason"):
                        break
        finally:
            if owned:
                client.close()
            run["updated_at"] = now()
            run["request_counts"] = dict(Counter(r["status"] for r in run["requests"]))
            run["remaining_requests"] = len(jobs) - len(run["requests"])
            run["missing_usage"] = sum(
                not all(k in (r.get("usage") or {}) for k in ("prompt_tokens", "completion_tokens"))
                for r in run["requests"]
            )
            run["known_cost_usd"] = (
                sum(
                    (
                        (r.get("usage") or {}).get("prompt_tokens", 0)
                        * endpoints[r["endpoint"]].prices.input_per_million
                        + (r.get("usage") or {}).get("completion_tokens", 0)
                        * endpoints[r["endpoint"]].prices.output_per_million
                    )
                    / 1e6
                    for r in run["requests"]
                )
                if all(e.prices for e in config.endpoints)
                else None
            )
            run["analysis"] = analyze_choices(run)
            run["validation"] = validate_manifest(run, package, finalized=False)
            atomic_json(path, redact(run, secrets))
        return run
