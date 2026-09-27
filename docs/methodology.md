# Methodology: protocol v0.1

This page describes the legacy cumulative smoke-test suite. For substantive dataset comparisons, use the [parsed-choice protocol](dataset-protocol.md) and optional [practical consistency protocol](consistency.md). Practical tolerance evidence is separate from non-rejection of a distribution test.

## Estimand and observations

For a fixed prompt, compare the distributions of successful, untruncated visible assistant strings under the requested settings. Whitespace, punctuation and Unicode are not normalized. Reasoning traces and tool calls are not analyzed. All endpoints receive identical prompts, roles and output limits; omitted controls are recorded. Accepting a setting does not prove it was honored.

Endpoint order is randomized within each prompt/repeat block, with randomized prompt order each repeat. There is one call per observation and no transparent retries. Optional request seeds vary by repeat and match across endpoints; seeds can be ignored or induce dependence. Behavior can drift within a run or resumed session. Inspect the time window.

## Levels 0–2

Level 0 records compatibility and metadata. Tokenizer, template, quantization and revision details come from config, not forensic verification. Unsupported controls are user-declared. HTTP 400 remains a failure; the adapter never silently drops controls and retries.

Level 1 calculates empirical Jensen–Shannon divergence in bits per prompt, then averages equally. For P, Q and M=(P+Q)/2, JSD = [KL(P||M)+KL(Q||M)]/2, using base-2 logs. Range: 0–1. No pseudocounts or learned threshold. Even/odd repeat split halves describe within-endpoint variability; they are not confidence intervals or calibrated null distributions. Small-sample plug-in JSD is biased. No significance verdict is made.

Level 2 reports descriptive distances, frequency counts and cross-sample disagreement rates with representative hashes or opt-in text. There is no accuracy or speed-derived identity score. These are fixed starter tasks, not an optimized classifier.

## Level 3: implemented statistical procedure

Use the positive-definite **exact-string / one-hot kernel** k(x,y)=1 when complete strings match and 0 otherwise. SHA-256 hashes preserve equality up to negligible collision risk. Credential redaction precedes hashing: the estimand concerns credential-redacted strings.

For n observations X and m observations Y per prompt, compute:

```text
U = sum(i != j) k(Xi, Xj) / [n(n-1)]
  + sum(i != j) k(Yi, Yj) / [m(m-1)]
  - 2 sum(i,j) k(Xi, Yj) / (nm)
T = arithmetic mean of U across the fixed prompts
```

This unbiased squared-MMD estimate can be negative; retain negative estimates. No conversion to an authenticity probability exists.

Reports show each prompt's U statistic and its contribution U / number-of-prompts to T. The largest absolute contribution share is max(|U|) / sum(|U|), or unavailable when all contributions are zero. This is descriptive attribution, not a prompt-level hypothesis test. A single formatting convention can drive the entire result. Neither significance nor contribution size identifies its cause as a checkpoint change.

Normalization changes the question being tested. Case folding may be reasonable for a translated color, but destroys meaningful information in case-sensitive code or an exact-formatting task. Choose task-specific parsers before collection and preserve raw observations. Any normalization or prompt exclusion chosen after inspecting a result is exploratory sensitivity analysis; it must not replace the original test or be sold as a newly calibrated verdict. See the [dataset and protocol guide](datasets.md).

**Null:** response distributions are equal at every tested prompt under requested settings. Pool both samples separately within each prompt; randomly reassign labels while retaining group sizes. Recompute T each time. With B permutations, p=(1 + count(permuted T >= observed T))/(B+1). A 1e-12 tolerance counts near-ties conservatively. This one-sided difference test requires within-prompt exchangeability. It is not an equivalence test.

Apply **Holm step-down family-wise error correction**, default alpha=0.05, across all planned N(N−1)/2 level-3 pairs. Untestable pairs count as p=1. There are no prompt-level significance claims. Level 4 reuses this family. Additional runs require an externally specified multiplicity plan.

Reject when adjusted p <= alpha; otherwise report “no difference detected.” Return **inconclusive** if a required observation is invalid/missing, a prompt has fewer than the configured minimum (default 8) valid samples per endpoint, every prompt lacks string collisions, or permutation resolution cannot reach the strictest Holm threshold. Eight is an engineering floor, not a power guarantee.

Descriptive uncertainty: independently bootstrap samples within each endpoint/prompt, recompute T, and report the 2.5th/97.5th percentiles of 300 replicates. **These are not calibrated confidence guarantees**: the ordinary bootstrap can have poor coverage for degenerate MMD near the null. It does not drive verdicts. Permutation resolution is reported separately; decisions close to alpha warrant more preplanned permutations.

## Reference audit

Level 4 adds a reference view of existing level-3 comparisons, with no extra requests. No reference means an explicit skip. Known control, tokenizer, template, revision, quantization or reasoning mismatches make the reference conclusion inconclusive. Unknown settings still limit comparability. New runs phrase non-rejection as “no difference detected against designated reference.” Historical v0.1 reports retain their original “consistent with reference under this protocol (no difference detected)” wording for reproducibility; this was not a tolerance/equivalence result. Reference provenance must be established externally, even for a local deployment. The rank-based uniformity test is not implemented.

## Research relationship and departures

[Gao, Liang & Guestrin (2025)](https://arxiv.org/abs/2410.20247) supplies the two-sample framing. We implement its one-hot alternative (equation 6), not the empirically preferred token-position Hamming kernel. We use balanced fixed prompt strata, average per-prompt U statistics and stratified permutations. We do not reproduce its suite, experimental design or power claims. Exact matches suit constrained answers but often lack power for prose.

[Bruckner (2026)](https://arxiv.org/abs/2607.10252) motivates short-answer fingerprints. We use four original digit prompts, a 16-token cap and descriptive JSD; we do not implement its full battery, one-token sampling, lineage classification or verification error rates.

[LLMmap (2025)](https://www.usenix.org/conference/usenixsecurity25/presentation/pasquini) motivates varied active probes; our tasks do not reproduce its query selection or classifier. [Zhu et al.](https://arxiv.org/abs/2506.06975) is a future independent option requiring its own reference sampling/scoring protocol and validation.

## Calibration and power

Offline tests use predeclared identical point masses, disjoint distributions, Bernoulli samples under a common null, and a shifted alternative. Fixed seeds make regressions reproducible; this is not real-provider calibration.

Before operational claims, pre-register the suite, sample size, alpha, permutations, kernel and practical effect of interest. Calibrate on separately collected known same-configuration and different-model controls. Repeat controls to estimate false-positive rate and power with binomial uncertainty. Keep final evaluation data held out; never tune cutoffs on final results. Publish control conditions and uncertainties with the report. This release does not automatically estimate real-model power or certify equivalence.
