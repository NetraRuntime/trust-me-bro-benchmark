"""Workspace-scoped service shared by MCP tools; no keys in tool arguments."""

import json
import math
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .adapters import redact
from .choice_analysis import analyze_choices, render_choices
from .config import load_config
from .dataset_runner import compare_dataset, dataset_plan
from .datasets import load_dataset
from .probes import digest
from .runner import estimate
from .validation import validate_manifest


class BenchmarkService:
    def __init__(self, root, allow_network=False, max_requests=2500, max_tokens=2000000, max_cost_usd=1.0):
        self.root = Path(root).resolve(strict=True)
        if not self.root.is_dir() or not all(
            math.isfinite(x) and x > 0 for x in (max_requests, max_tokens, max_cost_usd)
        ):
            raise ValueError("Use an existing workspace and positive server limits")
        self.allow_network = allow_network
        self.max_requests, self.max_tokens, self.max_cost_usd = max_requests, max_tokens, max_cost_usd
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="tmb")
        self.lock = threading.Lock()
        self.jobs = {}

    def path(self, value, exists=True):
        path = (self.root / value).resolve(strict=exists)
        if path == self.root or not path.is_relative_to(self.root):
            raise ValueError("Path must stay inside the configured workspace")
        if exists and (not path.is_file() or path.stat().st_size > 64 * 1024 * 1024):
            raise ValueError("Expected a regular file no larger than 64 MiB")
        return path

    def inputs(self, config_path, dataset_path, repeats, workers):
        config = load_config(self.path(config_path))
        data = load_dataset(self.path(dataset_path))
        if repeats not in (2, 3, 4) or not 1 <= workers <= len(config.endpoints):
            raise ValueError("Use 2-4 repeats and workers between 1 and endpoint count")
        return config, data

    def clean(self, value, config):
        return redact(value, [os.environ.get(e.api_key_env, "") for e in config.endpoints if e.api_key_env])

    def plan(self, config_path, dataset_path, repeats=2, workers=1):
        config, data = self.inputs(config_path, dataset_path, repeats, workers)
        return self.plan_inputs(config, data, repeats, workers)

    def plan_inputs(self, config, data, repeats, workers):
        budget = estimate(dataset_plan(config, data, repeats, config.sampling.random_seed))
        live = any(e.adapter != "mock" for e in config.endpoints)
        blockers = []
        if budget["requests"] > min(self.max_requests, config.limits.max_requests):
            blockers.append("Request plan exceeds server or configuration limit")
        if budget["input_token_reservation"] + budget["output_token_limit"] > min(
            self.max_tokens, config.limits.max_total_tokens
        ):
            blockers.append("Token plan exceeds server or configuration limit")
        if live and not self.allow_network:
            blockers.append("Live requests disabled; server owner must opt in with --allow-network")
        if live and any(e.prices is None for e in config.endpoints):
            blockers.append("Live MCP runs require configured prices for every endpoint")
        cost = budget["cost_estimate_usd"]
        if cost is not None and cost > min(
            self.max_cost_usd, config.limits.max_cost_usd or self.max_cost_usd
        ):
            blockers.append("Estimated cost exceeds server or configuration limit")
        if config.probes_file:
            blockers.append("Dataset runs cannot use probes_file")
        return self.clean(
            {
                "dataset_hash": data["content_hash"],
                "questions": len(data["items"]),
                "config_hash": digest(config.model_dump(mode="json")),
                "repeats": repeats,
                "workers": workers,
                "endpoints": [e.model_dump(exclude={"mock_behavior"}) for e in config.endpoints],
                "consistency": config.consistency.model_dump() if config.consistency else None,
                "estimate": budget,
                "can_start": not blockers,
                "blockers": blockers,
                "limits_scope": "Per run; estimated prices and token reservations are not billing guarantees",
            },
            config,
        )

    def start(self, config_path, dataset_path, output, repeats=2, workers=1, resume=False):
        config, data = self.inputs(config_path, dataset_path, repeats, workers)
        planned = self.plan_inputs(config, data, repeats, workers)
        if planned["blockers"]:
            raise ValueError("; ".join(planned["blockers"]))
        if any(
            e.adapter != "mock" and e.api_key_env and not os.environ.get(e.api_key_env)
            for e in config.endpoints
        ):
            raise ValueError("Required credentials are missing from the server environment")
        target = self.path(output, exists=False)
        if target.exists() and not target.is_dir():
            raise ValueError("Output must be a directory")
        if (target / "run.json").exists() != resume:
            raise ValueError("Existing manifest requires resume; new output requires resume=false")
        # Refuse report symlinks and occupied outputs before allowing the runner to write.
        if target.exists() and not resume and any(target.iterdir()):
            raise ValueError("Choose an empty output directory")
        for name in ("run.json", "run.tmp", "report.md", ".run.lock"):
            child = target / name
            if child.is_symlink() or (child.exists() and not child.resolve().is_relative_to(self.root)):
                raise ValueError("Output artifacts must not be symlinks or escape the workspace")
        with self.lock:
            if any(j["state"] in {"queued", "running"} for j in self.jobs.values()):
                raise ValueError("A run is already active; inspect its status before starting another")
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {
                "job_id": job_id,
                "state": "queued",
                "output": str(target.relative_to(self.root)),
                "completed": 0,
                "planned": planned["estimate"]["requests"],
            }
            self.pool.submit(self._run, job_id, config, data, target, repeats, workers, resume)
        return self.status(job_id)

    def _run(self, job_id, config, data, target, repeats, workers, resume):
        def update(**values):
            with self.lock:
                self.jobs[job_id].update(values)

        update(state="running")
        try:
            run = compare_dataset(
                config,
                data,
                target,
                repeats=repeats,
                workers=workers,
                resume=resume,
                progress=lambda n, total: update(completed=n, planned=total),
            )
            (target / "report.md").write_text(render_choices(run), encoding="utf8")
            update(
                state="completed" if run["remaining_requests"] == 0 else "incomplete",
                statuses=run["request_counts"],
                estimated_cost_usd=run["known_cost_usd"],
                remaining=run["remaining_requests"],
                missing_usage=run["missing_usage"],
            )
        except Exception:  # noqa: BLE001 -- exception text may contain credentials or provider data
            update(
                state="failed",
                error="Run failed; inspect the local manifest and configuration. No automatic retries.",
            )

    def status(self, job_id):
        with self.lock:
            if job_id not in self.jobs:
                raise ValueError("Unknown job ID in this server session")
            return dict(self.jobs[job_id])

    def report(self, manifest, dataset_path=None):
        run = json.loads(self.path(manifest).read_text(encoding="utf8"))
        if run.get("kind") != "choice-dataset":
            raise ValueError("Expected a supported dataset manifest")
        package = load_dataset(self.path(dataset_path)) if dataset_path is not None else None
        run["validation"] = validate_manifest(run, package)
        run["analysis"] = analyze_choices(run)
        # Return only analysis/report data, never stored raw response text or credentials.
        from .config import Config

        config = Config.model_validate(run["config"])
        return self.clean(
            {
                "run_id": run["run_id"],
                "statuses": run["request_counts"],
                "remaining": run["remaining_requests"],
                "report_markdown": render_choices(run),
            },
            config,
        )

    def close(self):
        self.pool.shutdown(wait=True)
