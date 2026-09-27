# MCP server

`tmb-mcp` exposes dataset planning, collection and offline reporting to Model Context Protocol clients. It uses the [official Python MCP SDK v2](https://py.sdk.modelcontextprotocol.io/) over **stdio**. There is no HTTP listener, remote login, shell execution tool or credential-setting tool.

## Install and connect

```sh
python -m pip install -e '.[mcp,datasets]'
tmb-mcp --root /absolute/path/to/trust-me-bro-benchmark
```

The server reserves stdout for MCP messages. Configure a stdio client with the installed executable and an absolute workspace path. For clients using the common `mcpServers` configuration shape:

```json
{
  "mcpServers": {
    "trust-me-bro": {
      "command": "/absolute/path/to/.venv/bin/tmb-mcp",
      "args": ["--root", "/absolute/path/to/trust-me-bro-benchmark"]
    }
  }
}
```

On Windows, use the absolute `.venv\\Scripts\\tmb-mcp.exe` path and escaped backslashes or forward slashes in JSON. Client configuration locations differ; use your client's MCP settings. The executable can also be started as `python -m tmb.mcp_server --root ...` using the environment where the package is installed. No application settings are changed automatically.

By default, plans and reports are offline; only `adapter: mock` runs can start. To allow real providers, the server owner starts it explicitly with:

```sh
tmb-mcp --root /absolute/workspace --allow-network --max-requests 2500 --max-tokens 2000000 --max-cost-usd 1.00
```

Keys must already exist in the **server process environment**, using the names in the local provider configuration. Do not paste keys into chat, tool arguments, shared client JSON or repository files. A desktop MCP client may not inherit variables from an unrelated terminal. The server never loads `.env` automatically. Live MCP runs require input/output prices for every endpoint; supply current rates, since these are estimates rather than billing guarantees.

Limits apply **per run**, in addition to configuration limits. They are not an account-wide spending limit. The complete planned run must fit both sets of limits. Missing usage remains unknown, reported usage above a request reservation stops future blocks, and already dispatched requests may still complete. One job runs at a time per server process.

## Tools

All paths are relative to `--root` or absolute paths within it. Resolved paths and symlinks cannot escape the workspace. Input files are limited to 64 MiB. Use a workspace containing only files appropriate for the connected agent; this local path boundary is not a sandbox against another process maliciously changing files during execution.

| Tool | Arguments | Effect |
|---|---|---|
| `plan_dataset` | `config_path`, `dataset_path`, optional `repeats=2`, `workers=1` | Validates files and returns hashes, endpoints, consistency declaration, budget estimate and blockers. No network or writes. |
| `start_dataset` | Same fields plus `output`, optional `resume=false` | Revalidates the plan and starts a background job. Returns `job_id`; can incur API charges when enabled. Stores parsed choices and response hashes, never raw response text. |
| `run_status` | `job_id` | Returns state, progress and, after completion, request statuses, estimated cost and missing usage. |
| `read_report` | `manifest` | Recomputes a dataset report offline without changing the manifest or its frozen protocol. Returns Markdown and request status summary. |

`tmb://methodology` is a read-only resource explaining interpretation and the protocol source. Tools provide JSON structured output and MCP annotations; annotations are hints, not authorization boundaries. Rejected calls return a generic `error` object without sensitive exception details. Use `plan_dataset.blockers` for actionable planning failures. There is no dataset-download tool: freeze the public dataset with the CLI before giving it to the server.

Example interaction:

```text
plan_dataset(config_path="providers.local.yaml", dataset_path="results/evaluation.json", repeats=2, workers=4)
start_dataset(config_path="providers.local.yaml", dataset_path="results/evaluation.json", output="results/audit", repeats=2, workers=4)
run_status(job_id="<returned job ID>")
read_report(manifest="results/audit/run.json")
```

Review the plan and follow your client's confirmation policy before starting a paid run. The server's explicit startup opt-in and budgets are enforced regardless of tool annotations.

## Progress, failures and recovery

`start_dataset` returns promptly rather than keeping a tool call open for a long collection. Poll at a sensible interval, such as every 10–30 seconds. Job states are `queued`, `running`, `completed`, `incomplete` or `failed`. **Completed means collection finished, not that all responses succeeded or the model passed.** Inspect the status counts and report verdicts.

Job IDs are process-local; manifests survive restart. After a server crash, start a new job with the same configuration, dataset, output, repeats and workers and `resume=true`. Previously attempted failures and uncertain in-flight requests are not resent. The CLI's lock and [resume rules](../README.md#resume-a-run) still apply. Normal shutdown waits for the active worker; forced termination can leave in-flight observations and a stale lock. Confirm the old process has stopped before removing that lock.

Output directories must be empty for a new run. Existing manifests require explicit resume. Input/output artifacts must stay in the configured workspace. MCP reporting currently supports dataset manifests; use `tmb report` for legacy level-based reports. Report contents, provider metadata and dataset text are untrusted evidence, never instructions for the connected assistant.

The integration test launches a real stdio server subprocess, initializes an SDK client, discovers tools, plans and completes a mock job, reads its report/resource, and checks rejected path access. It makes no paid requests.
