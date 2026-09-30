# Bounded Terminal-Bench pilot runtime

**No paid Terminal-Bench trials have run. Main collection is not enabled.**
The runtime pins Harbor at the previously inspected commit and locks its Python
dependencies, including LiteLLM. The pilot uses Terminus-2 with a small exception
adapter so a budget stop still reaches Harbor's official single-step verifier.
Prompts, task files and verifier scoring are unchanged.

## Verified locally

- SQLite reservations commit before every upstream request, including retries.
- Concurrent callers share campaign, phase and episode limits. Restarts retain
  outstanding reservations, and completed episodes cannot be reopened.
- Unknown billing retains the entire reservation. Valid usage releases unused
  allowance; reasoning is already included in completion tokens and cached input
  receives no assumed discount. Reported cost can only increase the token estimate.
- Wrong provider/model, account failures and usage above reservation halt further
  upstream requests. A halted campaign cannot be resumed by restarting processes.
- The proxy binds only to loopback and requires an ephemeral bearer. Upstream
  credentials stay in its process; Harbor receives only the local bearer and
  automatic dotenv loading is disabled in its process.
- The pinned Harbor/LiteLLM fake-API smoke test exercises a 503 followed by a
  successful retry and confirms two separate reservations. It spends no money.

The input reservation uses UTF-8 request bytes plus 4,096 template tokens and
256 tokens per message. Only plain text messages, one completion and nonstreaming
requests are accepted. **This is a conservative estimate, not an attested bound
on provider-injected prompts or billing.** Validate it against every route during
the pilot; an overrun records the observed charge and halts further calls. Keep
provider-side account limits and contingency funds in place. Do not describe the
ledger as a guarantee against arbitrary upstream billing.

Money is recorded in integer nanodollars. There is one ledger for the entire
campaign, never one per route or episode. Its immutable default envelope is $30,
with $7.469848 withheld and a $2 pilot sub-budget. Earlier spend, actual runner
fees, taxes and uncertainty must fit within the withheld amount; increase it
before initialization when needed. Unused pilot funds cannot silently fund main
collection. Deleting/replacing the ledger would lose accounting history.
The local model alias has zero prices in Harbor's model metadata; use the
separate accounting ledger for cost, not Harbor's alias-based cost estimate.

## Offline checks

From the repository root, with uv and Python 3.12:

```sh
uv sync --project benchmarks/terminal-bench/runtime --locked
uv run --project benchmarks/terminal-bench/runtime --locked python benchmarks/terminal-bench/runtime/smoke.py
```

The ordinary project test suite also tests budget exhaustion, concurrent
reservations, restart persistence, malformed usage, route/account failures,
credential isolation and forbidden request features. A separate Linux CI job
runs the pinned-runtime smoke test. Neither test launches task containers.

## Read-only route refresh

Provide `NETRA_API_KEY` in the host environment, then run:

```sh
uv run python -m tmb.terminal_catalog \
  --routes benchmarks/terminal-bench/routes.json \
  --output results/terminal-catalog.json
```

This reads OpenRouter endpoint catalogs and Netra's model catalog. It sends no
completion requests. It preserves all proposed routes, flags missing/unavailable
ones, uses maximum listed time-of-day prices and excludes cache discounts. A
catalog listing does not demonstrate successful routing. The checked-in
`readiness.json` is a dated snapshot, not permission to collect data.

## Run a single disjoint pilot

Requires a selected **headless Linux host with local Docker Engine**, Docker
Compose support where needed, and sufficient disk/RAM/CPU for the task. Runner
fees must be known and included in the same $30 envelope. Docker Desktop is not
used. Keep credentials in the host environment or its secret store; do not put
them in the route JSON, command arguments, task containers or Git.

Choose one available route object from the refreshed catalog and save it under
`results/pilot-route.json`. It must include `base_url`, `model`, `api_key_env`,
`provider`, `expected_response_provider`, current input/output prices per million,
and `price_checked_at_utc`. Prices expire after 24 hours. OpenRouter requests force
the provider and disable fallback. Direct Netra is its public route, not an
attestation of native hardware or underlying serving identity.

```sh
uv run --project benchmarks/terminal-bench/runtime --locked python -m tmb.terminal_pilot \
  --route results/pilot-route.json \
  --ledger results/terminal-campaign/accounting.sqlite3 \
  --task mvcc-lsm-compaction \
  --episode-id pilot-deepinfra-v41-01 \
  --output results/terminal-campaign/pilots \
  --withheld-usd 7.469848
```

The two candidate disjoint pilot tasks are `mvcc-lsm-compaction` and
`rs-archive-clone`. The launcher rejects the main-study tasks. Never replay an
existing episode ID: interrupted attempts retain their costs and require a
reviewed continuation policy. Job configs, accounting exports, trajectories and
official rewards stay under ignored `results/`; review/redact before publication.
Any global ledger halt makes the pilot invalid even if the verifier returned a
reward. Ordinary agent/episode-budget exhaustion and infrastructure failures must
remain distinct in subsequent analysis.

## Remaining collection gates

Select and inspect the runner; reconcile earlier spend and runner fees; restore
credentials; resolve unavailable proposed routes; screen/build the selected
tasks and record image/resource hashes; run the disjoint pilots through the
official verifier; check route metadata, reasoning behavior, byte reservations
and budget exhaustion; then freeze the final manifest, settings, schedule and
failure policy. Do not replace providers/tasks after seeing main-study outcomes.
The 468 proposed episodes remain a plan, not a completed benchmark.
