"""Run ONE disjoint setup pilot on an explicitly configured headless Linux host.

Main collection is intentionally gated until resource screening, route checks,
pilot review and final preregistration are complete.
"""

import argparse
import json
import os
import platform
import secrets
import subprocess
import sys
import threading
from pathlib import Path

from tmb.terminal_guard import Ledger, nano_usd
from tmb.terminal_proxy import Gateway, make_server, validate_route

REVISION = "452bf305c6daa62fc59061d22133a7cbc7c1572e"
PILOT_TASKS = {"mvcc-lsm-compaction", "rs-archive-clone"}


def harbor_config(task, episode_id, api_base, output_dir):
    if task not in PILOT_TASKS:
        raise ValueError("Use a disjoint candidate pilot task")
    return {
        "job_name": episode_id,
        "jobs_dir": str(output_dir),
        "n_attempts": 1,
        "n_concurrent_trials": 1,
        "retry": {"max_retries": 0},
        "environment": {"type": "docker", "delete": True},
        "verifier": {"disable": False},
        "tasks": [
            {
                "path": "tasks/" + task,
                "git_url": "https://github.com/harbor-framework/terminal-bench.git",
                "git_commit_id": REVISION,
            }
        ],
        "agents": [
            {
                "import_path": "tmb.terminal_agent:BoundedTerminus2",
                "model_name": "openai/tmb",
                "kwargs": {
                    "api_base": api_base,
                    "temperature": 0.6,
                    "enable_summarize": True,
                    "use_responses_api": False,
                    "model_info": {
                        "max_input_tokens": 150000,
                        "max_output_tokens": 8192,
                        "input_cost_per_token": 0,
                        "output_cost_per_token": 0,
                    },
                    "llm_kwargs": {"num_retries": 0},
                    "llm_call_kwargs": {"max_tokens": 8192, "stream": False},
                },
            }
        ],
    }


def child_environment(token):
    # Explicit allowlist: no upstream credentials or cloud account secrets enter
    # Harbor's process environment, which task env interpolation could expose.
    allowed = {"PATH", "HOME", "USER", "LANG", "LC_ALL", "TMPDIR", "VIRTUAL_ENV", "SSL_CERT_FILE"}
    child = {key: value for key, value in os.environ.items() if key in allowed}
    child.update(
        OPENAI_API_KEY=token,
        LITELLM_LOCAL_MODEL_COST_MAP="True",
        DO_NOT_TRACK="1",
        PYTHON_DOTENV_DISABLED="1",
    )
    return child


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--route", type=Path, required=True, help="One freshly verified route JSON object")
    parser.add_argument("--ledger", type=Path, required=True, help="The ONE durable campaign ledger")
    parser.add_argument("--task", choices=sorted(PILOT_TASKS), required=True)
    parser.add_argument("--episode-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--withheld-usd", required=True, help="Earlier spend + runner fees + contingency")
    args = parser.parse_args()
    if platform.system() != "Linux":
        parser.error("A headless Linux Docker host is required; Docker Desktop is not used")
    if nano_usd(args.withheld_usd) < nano_usd("7.469848"):
        parser.error("Preserve at least the candidate $7.469848 earlier-spend/runner/contingency reserve")
    if not args.episode_id or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for c in args.episode_id):
        parser.error("Episode ID must contain lowercase letters, digits, hyphens or underscores")
    route = json.loads(args.route.read_text(encoding="utf-8"))
    validate_route(route)
    key = os.environ.get(route["api_key_env"])
    if not key:
        parser.error("Required upstream credential is missing from the runner environment")
    docker = subprocess.run(
        ["docker", "info", "--format", "{{.OSType}}"], check=True, capture_output=True, text=True, timeout=30
    )
    if docker.stdout.strip() != "linux":
        parser.error("Docker must provide Linux containers")
    args.output.mkdir(parents=True, exist_ok=True)
    args.ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger = Ledger(args.ledger, withheld_usd=args.withheld_usd)
    # Reusing an ID preserves all existing reservations, and completed IDs cannot reopen.
    ledger.episode(args.episode_id, route)
    gateway = Gateway(ledger, args.episode_id, route, key)
    token = secrets.token_urlsafe(32)
    server = make_server(gateway, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    config = harbor_config(
        args.task, args.episode_id, f"http://127.0.0.1:{server.server_port}/v1", args.output
    )
    config_path = args.output / (args.episode_id + ".config.json")
    # Never overwrite an earlier invocation, including a crashed one.
    try:
        with config_path.open("x", encoding="utf-8") as stream:
            json.dump(config, stream, indent=2)
        result = subprocess.run(
            [sys.executable, "-c", "from harbor.cli.main import app; app()", "run", "-c", str(config_path)],
            env=child_environment(token),
            check=False,
        )
        ledger.close(args.episode_id)
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
        gateway.client.close()
        (args.output / (args.episode_id + ".accounting.json")).write_text(
            json.dumps(ledger.snapshot(), indent=2), encoding="utf-8"
        )
    raise SystemExit(result.returncode or (2 if ledger.snapshot()["halt"] else 0))


if __name__ == "__main__":
    main()
