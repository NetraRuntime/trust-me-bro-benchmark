> **Trust but verify.** — Old Russian proverb

# Trust Me Bro Benchmark

**Your providers claim to serve the same model. Compare the evidence.**

Trust Me Bro (`tmb`) compares **two or more API endpoints claiming to serve the same model** and produces reproducible evidence about whether their behavior is consistent. Start with DeepSeek, or point the same model-agnostic engine at any OpenAI-compatible chat API.

No leaderboard. No authenticity percentage. No majority vote that declares a winner.

[Quick start](#quick-start) · [Dataset comparison](#compare-a-published-dataset) · [Real providers](#compare-real-providers) · [Test levels](#choose-your-test-budget) · [Methodology](docs/methodology.md) · [Threat model](docs/threat-model.md) · [Configuration](docs/configuration.md)

## What the result means

An API-only test **cannot conclusively prove which weights a remote provider loaded**. Similar behavior does not establish authenticity. Agreement among most providers does not establish ground truth.

| Question | What `tmb` can say |
|---|---|
| Which providers behave differently? | **Relative comparison:** all N(N−1)/2 pairs, with samples and evidence. |
| Does a provider behave like a separately trusted deployment? | **Reference comparison:** consistency with your designated reference under this protocol. |
| Is this definitely the original checkpoint? | **Identity proof:** outside the scope of black-box behavioral testing. |

Statistical verdicts are **detectably different**, **no difference detected**, or **inconclusive**. A nonsignificant result is not proof of equality. Every comparison includes its effect estimate, sample counts, uncertainty or its absence, and limitations. Early levels are explicitly descriptive.

**The bundled suite is a smoke test.** Its six statistical prompts are too narrow for a comprehensive checkpoint audit. An exact-string test can detect capitalization alone, such as `Biru` versus `biru`, even when both answers mean the same thing. Reports expose each probe's contribution so a narrow formatting signal is visible. See [datasets and stronger audit protocols](docs/datasets.md) before interpreting a live comparison.

## Quick start

Python 3.11 or newer. No API key, GPU, or paid request required for this example.

```sh
git clone https://github.com/NetraRuntime/trust-me-bro-benchmark.git
cd trust-me-bro-benchmark
python -m pip install -e .

tmb benchmark --config examples/mock.yaml --level 1 --output results/quick
tmb report results/quick/run.json
```

Open `results/quick/report.md`. The adjacent `run.json` is the machine-readable manifest and evidence bundle.

The mock config has three endpoints: two sample the same synthetic distribution and one samples a different distribution. These are test fixtures, **not DeepSeek measurements**.

Try the complete statistical workflow, including a designated mock reference:

```sh
tmb benchmark --config examples/mock.yaml --level 4 --output results/full
tmb report results/full/run.json
```

Using uv? Run `uv sync --extra dev`, then prefix commands with `uv run`.

## Compare a published dataset

For broader provider comparisons, use the **MMLU-Pro parsed-choice workflow**. It freezes a balanced selection across 14 subjects and compares actual selected answers. Letter case and simple formatting wrappers do not change a parsed answer. Accuracy, answer disagreement and statistical evidence are reported separately.

```sh
python -m pip install -e '.[datasets]'
# Copy examples/dataset-providers.yaml to providers.local.yaml and configure your endpoints.
tmb prepare-dataset --output results/mmlu-140.json --per-category 10 --seed 20260927
tmb compare-dataset --config providers.local.yaml --dataset results/mmlu-140.json --repeats 2 --workers 2 --output results/mmlu --dry-run
tmb compare-dataset --config providers.local.yaml --dataset results/mmlu-140.json --repeats 2 --workers 2 --output results/mmlu
tmb report results/mmlu/run.json
```

With 140 questions and two repeats, the plan uses **280 requests per configured endpoint**. Set limits and inspect the dry-run estimate before collection. Dataset download requires the optional `datasets` extra; offline reporting does not. With uv, use `uv sync --extra datasets --extra dev`.

The report includes per-subject accuracy, coverage, all pairwise answer comparisons, question-level disagreements, corrected p-values and uncertainty. A second identically configured endpoint can serve as an independent repeat control via `--same-configuration-pair NAME_A NAME_B`. This measures baseline variation without treating provider consensus as truth.

This is a sampled, zero-shot direct-answer adaptation, **not an official full MMLU-Pro score or an identity certificate**. Read the [complete frozen protocol](docs/dataset-protocol.md), [sample configuration](examples/dataset-providers.yaml), and [dataset selection guide](docs/datasets.md). The original cumulative levels remain available for smoke tests and diagnostic fingerprints.

## Compare real providers

Copy [`examples/providers.yaml`](examples/providers.yaml) to `providers.local.yaml`, replace the placeholder URLs and model identifiers, and set credentials in your shell. These are intentionally **not working hosts or real checkpoint names**.

```yaml
claimed_model: deepseek/example-checkpoint
endpoints:
  - name: netra
    base_url: https://example-netra.invalid/v1
    model: deepseek/example-checkpoint
    api_key_env: NETRA_API_KEY
  - name: provider_b
    base_url: https://example-b.invalid/v1
    model: deepseek/example-checkpoint
    api_key_env: PROVIDER_B_API_KEY
  - name: provider_c
    base_url: https://example-c.invalid/v1
    model: deepseek/example-checkpoint
    api_key_env: PROVIDER_C_API_KEY
# reference: provider_c  # Your designation, not independently certified truth.
```

Keys are read **only from environment variables**. `.env.example` lists their names; `.env` files are not automatically loaded. In Bash, read keys without echoing them or placing them in shell history:

```sh
read -rs -p 'Netra API key: ' NETRA_API_KEY; export NETRA_API_KEY; echo
read -rs -p 'Provider B API key: ' PROVIDER_B_API_KEY; export PROVIDER_B_API_KEY; echo
read -rs -p 'Provider C API key: ' PROVIDER_C_API_KEY; export PROVIDER_C_API_KEY; echo
```

In PowerShell 7, use `$env:NETRA_API_KEY = Read-Host 'Netra API key' -MaskInput` and repeat for the other names.

```sh
tmb benchmark --config providers.local.yaml --level 1 --dry-run
tmb benchmark --config providers.local.yaml --level 1 --output results/quick-live
tmb benchmark --config providers.local.yaml --level 3 --output results/full-live
tmb report results/full-live/run.json
```

Add as many endpoints as needed. A local reference uses the same adapter, for example `http://127.0.0.1:8000/v1`; omit `api_key_env` if it does not require authentication. A remote reference is always **user-designated**, never independently certified by this tool.

### DeepSeek through OpenRouter

[`examples/openrouter-v4-flash.yaml`](examples/openrouter-v4-flash.yaml) and [`examples/openrouter-v4.1-flash.yaml`](examples/openrouter-v4.1-flash.yaml) pin two provider routes with fallbacks disabled. Set `OPENROUTER_API_KEY`, inspect the dry run, then start at level 0 or 1. Check current availability and prices before running.

Compare each checkpoint in its **own run**. V4 Flash versus V4.1 Flash is a different-model control, not a same-checkpoint audit. Provider routing, aliases, and returned model IDs are claims to record, not evidence of weight identity.

## Choose your test budget

`--level K` runs levels **0 through K**. Defaults below are **per endpoint** for the bundled suite; multiply by N endpoints. Output caps exclude the input reservation shown by `--dry-run`.

| Level | Method and interpretation | New requests | New output cap | Cumulative requests |
|---|---|---:|---:|---:|
| **0 · Sanity** | Compatibility probe; requested controls, IDs, metadata and failures. Setup evidence only. | 1 | 16 tokens | 1 |
| **1 · Quick fingerprint** | Four multilingual constrained prompts × 8 repeats; empirical JSD and within-endpoint split halves. Descriptive, no universal threshold. | 32 | 512 tokens | 33 |
| **2 · Active probes** | Six formatting, language, reasoning and version-sensitive tasks × 2 repeats. Describe disagreements; no accuracy-based identity score. | 12 | 1,536 tokens | 45 |
| **3 · Distribution test** | Six fixed prompts × 20 repeats; exact-string MMD permutation test, effect estimate and Holm-adjusted p-value. | 120 | 15,360 tokens | 165 |
| **4 · Reference audit** | Separate reference view of level-3 comparisons; reuses samples and correction. Optional. | 0 | 0 tokens | 165 |

Level 1 uses short **constrained answers**, not a claim that all answers occupy one token. Truncated responses make affected comparisons inconclusive. The optional rank-based uniformity test is **not implemented**.

Default run limits are 1,000 requests and 200,000 reserved input-plus-output tokens. Limits, repeats, output caps, timeouts, prices and estimated cost ceilings are [configurable](docs/configuration.md). There are no automatic API retries. Requests are sequential, with randomized endpoint order inside prompt/repeat blocks.

Token reservations and price estimates are not remote billing guarantees. Missing prices or usage are reported as unknown. Latency and spend stay separate from behavioral conclusions.

## Read the evidence

Each run writes:

* **`run.json`** — run ID, version, sanitized config, suite hash, settings, UTC timestamps, request statuses, response IDs, hashes, token usage, costs and statistical results.
* **`report.md`** — standalone report with an N × N matrix for every requested level, pairwise evidence, per-probe observations, response representatives, and a separate reference section at level 4.

Failures never disappear from a pair. Transport failures, HTTP errors, missing credentials, refusals, truncations, empty responses and suspected cached completions have explicit statuses. Any missing or invalid required sample makes that pair inconclusive. No string collisions or insufficient permutation resolution also yields an inconclusive level-3 result.

Reports retain response hashes by default. They preserve exact equality, permitting offline reproduction of this implementation's JSD and MMD analysis. Use `--store-text` to inspect redacted response wording; this is necessary for semantic disagreement review, and can still expose personal data. Private prompts are never saved automatically. Read the [privacy guidance](docs/privacy.md).

### Resume a run

```sh
tmb benchmark --config providers.local.yaml --level 3 --output results/full-live --resume
```

Keep the config, suite, level, tool version and `--store-text` policy unchanged. Completed and failed requests are not resent. An interrupted in-flight request becomes `interrupted_unknown`; the server may already have billed it, so resume does not silently resend it. That pair remains inconclusive. Start a new run to recollect a complete protocol.

The manifest is replaced atomically after each request. Brief local file locks receive a bounded replacement retry; this never resends an API request. A lock prevents concurrent writers. After a hard process kill, remove `results/full-live/.run.lock` **only after confirming no runner still uses it**. Budget exhaustion cannot be bypassed by resume; changing the budget requires a new run.

## Scientific scope

This is an initial working implementation, not a calibrated model-authentication product. Synthetic controls test the procedure; they do not establish power for DeepSeek or any live endpoint. The small public suite is deliberately inspectable and can be recognized by a provider.

* **Relative evidence:** compare every pair; never crown the largest cluster as ground truth.
* **Reference evidence:** match checkpoint revision, tokenizer, template, reasoning mode and requested controls. Known differences limit attribution; unknown settings remain caveats.
* **Statistical evidence:** distinguish significance from effect size. A lack of rejection may reflect insufficient samples or an insensitive kernel.
* **Adversarial limits:** hidden probes do not guarantee robustness against selective routing, spoofing, shared upstreams or drift.

See [the exact procedure and departures from the papers](docs/methodology.md) and [the threat model](docs/threat-model.md).

## Research

1. Gao, Liang & Guestrin. **Model Equality Testing: Which Model Is This API Serving?** ICLR 2025. [Paper](https://arxiv.org/abs/2410.20247) · [Research code](https://github.com/i-gao/model-equality-testing). Informs the two-sample framing and MMD test.
2. Zhu et al. **Auditing Black-Box LLM APIs with a Rank-Based Uniformity Test.** [Paper](https://arxiv.org/abs/2506.06975). An additional reference-audit method; not implemented here.
3. Bruckner. **One Token Is Enough: Fingerprinting and Verifying Large Language Models from Single-Token Output Distributions.** [Paper](https://arxiv.org/abs/2607.10252). Motivates short-output fingerprints; its verification thresholds are not transferred here.
4. Pasquini, Kornaropoulos & Ateniese. **LLMmap: Fingerprinting for Large Language Models.** USENIX Security 2025. [Paper and presentation](https://www.usenix.org/conference/usenixsecurity25/presentation/pasquini). Motivates varied active probes; this repo does not reproduce its trained classifier.
5. Zhang, Li & Wang. **Your “Pro” LLM Subscription May Actually Be “Free”: Exposing Fingerprint Spoofing Risks in LLM Inference Services.** [Paper](https://arxiv.org/abs/2606.16100). Informs the limits of fingerprinting under adversarial providers.
6. **KBF: Knowledge Boundary as Fingerprint for Language Model and Black-Box API Auditing.** May 2026 preprint. [Paper](https://arxiv.org/abs/2605.29524) · [Code and reference probe sets](https://github.com/Ooo0ption/KBF). A candidate for calibrated numerical-answer audits; not implemented here.

For available datasets, scope, and integration requirements, read the [dataset guide](docs/datasets.md).

## Contribute

```sh
python -m pip install -e '.[dev]'
python -m pytest -q
ruff check .
```

The code separates [adapters](src/tmb/adapters.py), [probes](src/tmb/probes.py), [orchestration](src/tmb/runner.py), [statistics](src/tmb/statistics.py), [analysis](src/tmb/analysis.py) and [reporting](src/tmb/report.py). Offline tests require no credentials and make no network requests.

See [CONTRIBUTING.md](CONTRIBUTING.md) for protocol changes and reproducibility requirements. Never commit credentials, private probes, or real paid API results. See [SECURITY.md](SECURITY.md) for private vulnerability reporting.

Licensed under the OSI-approved [MIT License](LICENSE).
