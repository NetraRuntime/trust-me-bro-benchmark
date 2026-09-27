# Changelog

## 0.3.0

- Keep MMD/permutation/Holm as the primary significance test. Reject shared request seeds for new statistical collections and mark historical seeded inference inconclusive.
- Validate manifests in CLI, MCP and resume paths: protocol/config agreement, fingerprint, unique planned repeat slots, valid choices and consistent status totals. Bind new dataset item metadata into the protocol fingerprint (schema 2).
- Add optional original-dataset verification to CLI `report --dataset` and MCP `read_report(dataset_path=...)`. Explicitly report when original dataset linkage is unverified. Prevent reports from overwriting their input manifest.
- Include missing-answer questions in detailed tables even when surviving answers agree; show coverage and failure statuses.
- Make new repeat-baseline bootstrap results descriptive only (`paired-disagreement-descriptive-v2`). Rare-question undercoverage prevents calibrated tolerance/equivalence verdicts from this method. Preserve historical 0.2 calculations with an explicit warning; do not relabel historical paid observations as a new study.
- Add offline regression coverage for the audit counterexamples. The primary unseeded distribution-test formulas, correction family and failure policy are unchanged.

## 0.2.0

- Add optional predeclared practical consistency against an independent same-configuration repeat baseline.
- Propagate worst-case missing-answer bounds through paired, subject-stratified bootstrap contrasts; use Bonferroni tail allocation across planned contrasts and explicit sensitivity/coverage gates.
- Keep categorical MMD distribution testing separate. Do not derive equivalence from non-rejection or change historical paid-run verdicts.
- Add the official-SDK MCP stdio server for planning, bounded background dataset runs, status and offline reports.
- Add a no-key synthetic consistency demo, interpretation guide, architecture documentation and MCP setup instructions.
- Preserve offline rendering of version 0.1 manifests. Resume requires the original collection version; a new tolerance or protocol requires a new collection.

The practical interval is an approximate question-cluster bootstrap, not a finite-sample coverage guarantee or general model-authentication test. Mean disagreement can conceal distribution differences. This release has synthetic validation, not certified live-provider operating characteristics.

## 0.1.0

- Establish the Python CLI, OpenAI-compatible adapter, cumulative diagnostic levels, exact-string MMD permutation testing and designated-reference reports.
- Add pinned MMLU-Pro subset collection, parsed-choice categorical tests, explicit failure statuses, budget estimates and offline reproducible reports.
- Add privacy guidance, threat model, MIT license and offline tests.
