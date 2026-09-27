# Configuration

YAML is validated strictly: unknown fields, duplicate endpoint names, fewer than two endpoints, unknown references and unsafe URLs are rejected. Paths to private probes resolve relative to the config file. Use one config/run per claimed checkpoint.

## Sampling and limits

Add these optional sections to any example. If overriding either map, supply all four levels:

```yaml
sampling:
  temperature: 1.0
  top_p: 1.0
  request_seed: null  # Omitted by default; otherwise increments for each repeat.
  random_seed: 2026   # Local order, permutation and bootstrap reproducibility.
  repeats: {0: 1, 1: 8, 2: 2, 3: 20}
  max_tokens: {0: 16, 1: 16, 2: 128, 3: 128}
  permutations: 999
  bootstrap: 300
  min_samples: 8
  alpha: 0.05
limits:
  max_requests: 1000
  max_total_tokens: 200000
  max_cost_usd: null
  timeout_seconds: 60
```

For each request, the input reservation is the prompt's UTF-8 byte length plus a 64-token framing allowance. Add the requested output cap. This is a budgeting heuristic, not an exact tokenizer or bound on hidden/reasoning tokens. `--dry-run` gives the planned total; it does not contact providers. Limits apply across endpoints and all cumulative levels. A limit can stop mid-block, leaving comparisons incomplete. Set limits large enough for the entire planned protocol when complete comparisons are required.

Prices are optional endpoint fields in USD per million tokens:

```yaml
prices:
  input_per_million: 0.30
  output_per_million: 1.20
```

An estimated cost ceiling requires prices for every endpoint. Reservations count failed/uncertain requests too, since a timeout may still incur charges. Reported token usage is recorded separately; missing usage is unknown, not zero-cost. Reported usage above a request reservation stops subsequent calls and prevents resume until you review and create a new protocol. Provider pricing changes, hidden overhead, discounts and billing rules can invalidate estimates. Configure provider-side spending limits for a billing guarantee.

## Endpoint options

Required: `name`, `base_url`, `model`. Names are unique letters/digits/underscores/hyphens. Model aliases can differ by endpoint; users must establish that they claim the same checkpoint. Every requested and returned identifier is recorded.

| Optional field | Meaning |
|---|---|
| `api_key_env` | Environment variable name; omit for an unauthenticated local endpoint. |
| `adapter` | `openai` (default) or deterministic `mock`. |
| `role` | `candidate` (default) or `different_model_control`; control pairs are labelled separately and cannot supply the claimed-checkpoint reference. |
| `mock_behavior` | `a`/`b` for legacy digit fixtures; `choice_a`/`choice_b` for parsed-choice fixtures; `error` or `truncated` for failures. |
| `unsupported_controls` | List drawn from `temperature`, `top_p`, `seed`; omitted from that endpoint's requests and recorded. |
| `provider` | OpenRouter route slug; sends `provider.only`, `allow_fallbacks: false`, `require_parameters: true`. |
| `reasoning_effort` | Optional `none`, `minimal`, `low`, `medium`, `high`; only use where supported. |
| `reasoning_enabled` | Optional boolean sent as `reasoning.enabled`; use only where supported. Mutually exclusive with `reasoning_effort`. |
| `tokenizer`, `chat_template`, `checkpoint_revision`, `quantization`, `serving_software` | User-supplied provenance strings; default `unknown`. |
| `prices` | Input/output USD per million tokens. |

The OpenAI adapter posts to `base_url + /chat/completions`, requests non-streaming responses and requires a normal `stop` finish for usable samples. It records returned model, response ID, fingerprint, provider, finish reason, HTTP status, usage and latency when present. Natural-language refusals without a structured refusal signal are treated as visible answers; no semantic refusal classifier is claimed. Tool calls, missing finish reasons, truncations and empty answers are not treated as ordinary successful text.

OpenRouter routes should be pinned: otherwise each request might go to a different provider. Check [routing documentation](https://openrouter.ai/docs/guides/routing/provider-selection) and the current [model catalog](https://openrouter.ai/api/v1/models). Pinning is a request to the aggregator, not proof of its routing or weights.

## Private probes

Set `probes_file: probes.local.yaml`. The file replaces the bundled suite and must contain unique IDs and at least one probe per level 0–3:

```yaml
- id: setup
  level: 0
  role: user
  prompt: "Reply with exactly OK."
- id: fingerprint
  level: 1
  prompt: "Choose A or B. Reply with one letter."
- id: active
  level: 2
  prompt: "Return precisely: [a::B]"
- id: distribution
  level: 3
  prompt: "Choose one digit from 0 to 9. Reply with only the digit."
```

`role` defaults to `user`; `system` is also supported. This initial suite format is single-message, not arbitrary conversations. Private text stays out of the manifest even with `--store-text`, though responses can echo it. Keep IDs non-sensitive. Never tune the suite or thresholds on your final evaluation samples.

## CLI and schema

Dataset practical consistency adds an optional top-level `consistency` object. `baseline` names two identical candidate configurations; `margin` is required and has no universal default. Defaults are `min_questions: 100`, `min_per_subject: 5`, and `max_missing_fraction: 0.05`. A different-model control is required. Bootstrap draws must provide at least 20 expected observations per multiplicity-adjusted tail; up to 100,000 draws are accepted. Larger families may need more draws. See [the complete protocol](consistency.md) and [example YAML](../examples/consistency-providers.yaml). This option is supported only by `compare-dataset`, not the legacy `benchmark` command.

`tmb demo --output results/demo` creates a complete synthetic dataset comparison without network calls. `--prepare-only` writes fixtures for use with MCP or a later `compare-dataset` command. The output directory must be empty.

`tmb --help`, `tmb benchmark --help`, and `tmb report --help` describe all switches. Exit codes: 0 for a successfully generated complete-request report, 1 for a benchmark with failed/unfinished requests, 2 for configuration/file errors, 130 for interruption. A statistically inconclusive comparison can still have exit code 0. Offline `report` returns 0 after successful rendering, even for an incomplete original run.

`run.json` uses `schema_version: 1`, records the tool version and includes config, suite identity, public prompt metadata, planned reservations, request rows, aggregates, and analysis. The saved per-request hashes are the statistical input. `tmb report` recomputes analysis from those rows without contacting providers or rewriting the evidence file. Use the recorded tool version and committed `uv.lock` to reproduce an analysis environment. Timestamps/IDs differ between newly collected runs; rendering an unchanged manifest is deterministic.

To designate a reference after collection, use `tmb report results/full/run.json --reference ENDPOINT_NAME`. This requires level-3 samples and writes separate `reference-report.md` and `reference-report.json` files. The original manifest/config, pairwise tests and correction family are preserved; the derived artifact records the source hash and designation time. It does not recollect or select observations. Use an unused `--output another-name.md` to create another audit. A known different-model control cannot be the reference and never receives a checkpoint-consistency verdict.
