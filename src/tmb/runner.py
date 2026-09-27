"""Sequential, randomized blocks with atomic manifests and conservative reservations."""

import json
import os
import random
import time
import uuid
from collections import Counter
from contextlib import contextmanager
from pathlib import Path

import httpx

from . import __version__
from .adapters import MockAdapter, OpenAIAdapter, now, payload, redact
from .analysis import analyze
from .probes import SUITE_VERSION, digest
from .validation import require_unseeded, validate_manifest


def plan(config, probes, level):
    if level >= 3:
        require_unseeded(config)
    rng = random.Random(config.sampling.random_seed)
    jobs = []
    for lev in range(min(level, 3) + 1):
        selected = [p for p in probes if p.level == lev]
        for repeat in range(config.sampling.repeats[lev]):
            ordered = list(selected)
            rng.shuffle(ordered)
            for probe in ordered:
                endpoints = list(config.endpoints)
                rng.shuffle(endpoints)
                for e in endpoints:
                    body = payload(e, probe, config.sampling, lev, repeat)
                    # UTF-8 byte count + framing allowance, a reservation, not a tokenizer claim.
                    inp = len(probe.prompt.encode("utf-8")) + 64
                    out = body["max_tokens"]
                    cost = (
                        (inp * e.prices.input_per_million + out * e.prices.output_per_million) / 1e6
                        if e.prices
                        else None
                    )
                    jobs.append(
                        {
                            "id": f"{probe.id}:{repeat}:{e.name}",
                            "endpoint": e.name,
                            "probe": probe.id,
                            "level": lev,
                            "repeat": repeat,
                            "reserved_input_tokens": inp,
                            "reserved_output_tokens": out,
                            "reserved_cost_usd": cost,
                        }
                    )
    return jobs


def estimate(jobs):
    return {
        "requests": len(jobs),
        "input_token_reservation": sum(j["reserved_input_tokens"] for j in jobs),
        "output_token_limit": sum(j["reserved_output_tokens"] for j in jobs),
        "cost_estimate_usd": (
            sum(j["reserved_cost_usd"] for j in jobs)
            if all(j["reserved_cost_usd"] is not None for j in jobs)
            else None
        ),
        "caveat": "Input token estimates and prices are user assumptions, not a billing guarantee",
    }


def atomic_json(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8"
    )
    # Windows readers/antivirus can briefly hold a destination without delete-sharing.
    # Retry only local replacement, never the paid API request or an entire job.
    for attempt in range(10):
        try:
            temporary.replace(path)
            return
        except PermissionError:
            if attempt == 9:
                raise
            time.sleep(0.05)


@contextmanager
def run_lock(output):
    path = output / ".run.lock"
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise ValueError("Run directory is locked; see resume guidance before removing .run.lock") from None
    try:
        os.close(fd)
        yield
    finally:
        path.unlink(missing_ok=True)


def benchmark(config, probes, suite_hash, level, output, resume=False, store_text=False, client=None):
    if config.consistency:
        raise ValueError("Practical consistency is a dataset protocol; use compare-dataset")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    with run_lock(output):
        return _benchmark(config, probes, suite_hash, level, output, resume, store_text, client)


def _benchmark(config, probes, suite_hash, level, output, resume, store_text, client):
    secrets = [os.environ.get(e.api_key_env, "") for e in config.endpoints if e.api_key_env]
    safe_config = redact(config.model_dump(mode="json"), secrets)
    safe_config.pop("consistency", None)  # This option is dataset-only; preserve legacy fingerprints.
    fingerprint = digest(
        {
            "config": safe_config,
            "suite": suite_hash,
            "level": level,
            "store_text": store_text,
            "version": __version__,
        }
    )
    jobs = plan(config, probes, level)
    path = output / "run.json"
    if path.exists():
        if not resume:
            raise ValueError("Output already contains a run; choose another directory or use --resume")
        run = json.loads(path.read_text(encoding="utf-8"))
        if run["protocol_hash"] != fingerprint:
            raise ValueError(
                "Resume protocol changed: config, suite, level, version and text policy must match"
            )
        validate_manifest(run, finalized=False)
        if run.get("stop_reason", "").startswith("reported usage"):
            raise ValueError("Usage exceeded reservation; inspect the run and start a new budgeted protocol")
        for row in run["requests"]:
            if row["status"] == "in_flight":
                row["status"] = "interrupted_unknown"
    elif resume:
        raise ValueError("No manifest to resume")
    else:
        run = {
            "schema_version": 1,
            "tool_version": __version__,
            "run_id": str(uuid.uuid4()),
            "started_at": now(),
            "updated_at": now(),
            "level": level,
            "config": safe_config,
            "protocol_hash": fingerprint,
            "suite_version": "private" if config.probes_file else SUITE_VERSION,
            "suite_hash": suite_hash,
            "store_text": store_text,
            "probes": [
                {
                    "id": p.id,
                    "level": p.level,
                    "role": p.role,
                    "prompt_hash": digest(p.prompt),
                    **({"prompt": redact(p.prompt, secrets)} if not config.probes_file else {}),
                }
                for p in probes
            ],
            "planned": estimate(jobs),
            "requests": [],
            "comparability": [
                "Controls are requested, not proven honored. Unsupported controls are recorded per endpoint.",
                "Unknown tokenizer, template, hidden system prompt, reasoning and deployment settings limit interpretation.",
                "Response IDs and cache headers detect some reuse; sample independence cannot be guaranteed.",
            ],
        }
    endpoints = {e.name: e for e in config.endpoints}
    probe_map = {p.id: p for p in probes}
    done = {r["id"] for r in run["requests"]}
    tokens = sum(r["reserved_input_tokens"] + r["reserved_output_tokens"] for r in run["requests"])
    cost = sum(r["reserved_cost_usd"] or 0 for r in run["requests"])
    seen = {(r["endpoint"], r.get("response_id")) for r in run["requests"] if r.get("response_id")}
    owned_client = client is None
    if owned_client:
        client = httpx.Client(timeout=config.limits.timeout_seconds, follow_redirects=False)
    adapters = {"mock": MockAdapter(), "openai": OpenAIAdapter(client)}
    try:
        for job in jobs:
            if job["id"] in done:
                continue
            reserved = job["reserved_input_tokens"] + job["reserved_output_tokens"]
            if (
                len(run["requests"]) >= config.limits.max_requests
                or tokens + reserved > config.limits.max_total_tokens
                or (
                    config.limits.max_cost_usd is not None
                    and cost + (job["reserved_cost_usd"] or 0) > config.limits.max_cost_usd
                )
            ):
                run["stop_reason"] = "configured budget exhausted; remaining requests not sent"
                break
            e, p = endpoints[job["endpoint"]], probe_map[job["probe"]]
            body = payload(e, p, config.sampling, job["level"], job["repeat"])
            row = job | {
                "status": "in_flight",
                "requested_at": now(),
                "requested_settings": {k: v for k, v in body.items() if k != "messages"},
                "prompt_hash": digest(p.prompt),
            }
            run["requests"].append(row)
            atomic_json(path, redact(run, secrets))
            result = redact(adapters[e.adapter].sample(e, body, job["id"]), secrets)
            text = result.pop("text", None)
            if text is not None:
                result["answer_hash"] = digest(text)
                if store_text:
                    result["text"] = text
            response_id = result.get("response_id")
            if response_id and (e.name, response_id) in seen:
                result["status"] = "cache_suspected"
            if response_id:
                seen.add((e.name, response_id))
            row.update(result)
            tokens += reserved
            cost += job["reserved_cost_usd"] or 0
            usage = result.get("usage") or {}
            # Actual reported overruns stop subsequent calls; billing cannot be enforced remotely.
            reported_cost = (
                (
                    usage.get("prompt_tokens", 0) * e.prices.input_per_million
                    + usage.get("completion_tokens", 0) * e.prices.output_per_million
                )
                / 1e6
                if e.prices
                else None
            )
            if (
                max(
                    usage.get("total_tokens", 0),
                    usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
                )
                > reserved
                or usage.get("completion_tokens", 0) > job["reserved_output_tokens"]
                or (reported_cost is not None and reported_cost > job["reserved_cost_usd"])
            ):
                run["stop_reason"] = "reported usage exceeded reservation; stopped for budget review"
                atomic_json(path, redact(run, secrets))
                break
            atomic_json(path, redact(run, secrets))
    finally:
        if owned_client:
            client.close()
        run["updated_at"] = now()
        run["request_counts"] = dict(Counter(r["status"] for r in run["requests"]))
        run["remaining_requests"] = len(jobs) - len(run["requests"])
        run["usage"] = {
            name: sum((r.get("usage") or {}).get(name, 0) for r in run["requests"])
            for name in ("prompt_tokens", "completion_tokens")
        }
        run["usage"]["requests_without_complete_usage"] = sum(
            not all(k in (r.get("usage") or {}) for k in ("prompt_tokens", "completion_tokens"))
            for r in run["requests"]
        )
        run["reserved_cost_usd"] = cost if all(e.prices for e in config.endpoints) else None
        complete_usage = run["usage"]["requests_without_complete_usage"] == 0
        run["estimated_reported_cost_usd"] = (
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
            if complete_usage and all(e.prices for e in config.endpoints)
            else None
        )
        run["analysis"] = analyze(run)
        run["validation"] = validate_manifest(run, finalized=False)
        atomic_json(path, redact(run, secrets))
    return run
