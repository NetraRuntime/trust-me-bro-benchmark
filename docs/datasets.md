# Datasets and broader audits

Reviewed 2026-09-27. `starter-1` is a smoke-test suite: four short fingerprint prompts and six tasks at each of levels 2 and 3. Repeating six tasks improves estimation on those tasks; it does not create broad task coverage. There is no universal dataset whose score proves remote model identity.

## Available resources

| Resource | Useful for | What is available | Limits for this project |
|---|---|---|---|
| [Model Equality Testing (MET), ICLR 2025](https://github.com/i-gao/model-equality-testing) | Testing the statistical engine on known serving changes | 1.6 million completions, 540 prompts, five models; multiple precision and provider configurations; code and development/test data | Historical samples, not a DeepSeek V4.1 Flash reference. Full archive is about 37 GB. |
| [KBF, May 2026 preprint](https://arxiv.org/abs/2605.29524) | Model-specific reference auditing using numerical knowledge boundaries | [Code and 16 reference probe sets](https://github.com/Ooo0ption/KBF); domain-specific numerical parsers and self-noise calibration | Bundled DeepSeek set is V3.2, with 364 probes. A V4.1 audit needs new enrollment and calibration. Promising recent work, not an independently validated guarantee. |
| [LiveBench, ICLR 2025](https://github.com/LiveBench/LiveBench) | Broad capability comparisons | Public tasks covering reasoning, math, coding, language, data analysis and instruction following; objective task scoring | Accuracy differences do not identify weights. Pin the exact public release: the newest leaderboard questions are not necessarily public. Code execution needs an isolated evaluator. |
| [MMLU-Pro](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro) | Broad knowledge and reasoning comparisons | Over 12,000 multiple-choice questions across 14 domains; [official evaluation code](https://github.com/TIGER-AI-Lab/MMLU-Pro) | Compare parsed choices and per-item disagreement, with accuracy separate. Match prompt/scoring conventions; a direct-answer subset is not the official evaluation protocol. |
| [IFEval](https://github.com/google-research/google-research/tree/master/instruction_following_eval) | Instruction adherence under explicit constraints | Public prompts and programmatic strict/loose validators | Formatting is part of the intended task here. Blanket case/whitespace normalization can erase the behavior being measured. |
| [LLMmap, USENIX Security 2025](https://www.usenix.org/conference/usenixsecurity25/presentation/pasquini) | Learned behavioral fingerprints across configurations | [Code](https://github.com/pasquini-dario/LLMmap), dataset-generation tooling and classifier training | New models require suitable training/reference data and held-out validation; a pretrained classifier is not automatic V4.1 support. |

**Implemented:** `tmb prepare-dataset` explicitly downloads and freezes an MMLU-Pro subset; `tmb compare-dataset` compares parsed option choices, accuracy and question-level disagreements. Read the [separate dataset protocol](dataset-protocol.md). This is a direct-answer adaptation, not the official full evaluator.

The other resources are linked, not bundled or automatically downloaded. Their licenses and data terms apply separately from this repository's MIT license. No LiveBench or IFEval evaluator, KBF enrollment/calibration, LLMmap classifier or MET dataset loader is currently implemented in `tmb`.

## A recent paper directly addresses formatting sensitivity

[Zhu et al., Rank-Based Uniformity Test, latest revision April 2026](https://arxiv.org/html/2506.06975v5) reports a provider that omitted a leading space. Its Hamming-based MMD comparison was highly sensitive to that formatting change; restoring the space greatly reduced the reported signal (§5.7). This is a concrete warning against attributing string differences to substituted weights.

The published RUT samples target and reference completions, scores their tokens using the reference model's vocabulary probability ranks, then tests randomized ranks for uniformity. Ordinary chat responses from OpenRouter do not provide that scoring access. A locally accessible reference or equivalent scoring interface is required. Merely ranking text lengths or embedding distances would be a different method. RUT is not implemented here.

## Recommended development path

This is a proposed protocol, not a claim that the following experiment has run:

1. **Validate the engine.** Use MET development data to choose the statistic and budgets, then measure false-positive rates and power on untouched test conditions. Report uncertainty across repeated trials. Older-model power estimates do not transfer automatically to DeepSeek.
2. **Enroll the checkpoint.** For a KBF-style audit, build numerical probes against the designated V4.1 reference. Select stable probes using separate reference calls and fixed domain parsers. Then collect fresh self-calibration responses. Keep target evaluation out of selection and tuning.
3. **Broaden task coverage.** Select a fixed, versioned, domain-stratified subset of public capability tasks. Use their intended scoring rules. Report per-domain accuracy and paired disagreements separately from distribution tests. Do not run long-form prose through the current exact-match kernel and expect useful power.
4. **Control ordinary variation.** Collect independent same-endpoint repeats, then comparisons across explicitly recorded configurations. Five providers claiming one checkpoint are useful comparisons, but are not known same-weight controls. Include a separately labeled different-model control.
5. **Freeze and evaluate.** Publish dataset revision, item IDs, selection seed, prompt templates, parsers, output limits, sample allocation, statistical family and budgets before the final run. Preserve failures. Report raw-format and task-answer differences separately, plus per-domain contributions.

KBF calibrates a reference mismatch rate and tests target discrepancies against it; its binomial model assumes independent trials with a common rate. Related prompts can violate those assumptions. Repeated controls and domain-level robustness checks remain necessary. A non-rejection would retain this project's wording: “consistent with reference under this protocol,” never “verified authentic.” See [the paper's calibration and dependence discussion](https://arxiv.org/html/2605.29524v1).

## Why simply removing capitalization is insufficient

Case folding can merge equivalent word answers. It can also merge different program identifiers, damage exact-formatting tests, and conceal useful distributional changes. Parsers must be task-specific and chosen in advance. Keep the original response distribution as an observable, and add a separate parsed-answer analysis with a clearly stated estimand.

Dropping a probe because it produced an inconvenient result is post-hoc selection. Such an analysis can explain a result, but cannot supply a replacement confirmatory verdict. Fresh held-out samples are needed to evaluate a revised protocol.

## Using other custom prompts

`probes_file` accepts a YAML list of `id`, `level`, `prompt` and optional `role`, with at least one probe in each level 0–3. See [configuration](configuration.md). The suite hash records the exact converted prompts. Custom prompt text stays out of results; retain the source YAML privately to reproduce collection.

This imports prompts only. It does not import ground-truth answers, evaluation code, numerical tolerances, dataset provenance or a paper's statistical procedure. Preserve those in a separate experiment manifest and do not describe the result as the original benchmark's score. The current exact-string MMD remains appropriate only where repeated strings provide informative collisions.
