# Practical behavioral consistency

The practical question is whether a provider's answer disagreement is comparable to a repeat deployment of the claimed model, within a tolerance chosen before collecting evaluation responses. This protocol adds evidence for that question; it does not estimate the probability that a model is authentic.

## Design the run

Use four or more logical endpoints:

1. A designated reference, selected by the investigator.
2. A second independently queried alias of exactly the same endpoint configuration. This is the **repeat baseline**. It measures stochastic variability, not differences between all legitimate deployments.
3. One or more candidate providers.
4. A deliberately different model. This checks whether the protocol can distinguish at least that control under these conditions.

The baseline aliases must match in every setting except name and prices, including credential environment name, pinned route, model and reasoning controls. Shared infrastructure, caching, batching and temporal correlation can still violate independence. A remote reference is a designation, not certification.

Choose the dataset, parser, repeats, tolerance, minimum question count, missing-answer limit, and bootstrap count **before evaluation collection**. Use separate pilot questions to select these settings. Do not adjust the tolerance until a preferred provider passes. Do not repurpose old evaluation responses as a fresh confirmatory run. The tool freezes settings in the resumable manifest; it cannot establish that an investigator never saw a public question before.

```yaml
consistency:
  baseline: [reference, reference_repeat]
  margin: 0.05
  min_questions: 100
  max_missing_fraction: 0.05
sampling:
  bootstrap: 10000
  alpha: 0.05
```

`margin: 0.05` means **five percentage points of excess answer disagreement**, in either direction. It is an illustrative design choice, not a recommended universal threshold or an authenticity percentage. Justify it using the intended application and independent pilot data. At 140 questions, a tight tolerance can legitimately remain inconclusive. More independent questions generally help more than counting all cross-response pairs as independent trials.

Start with [the complete configuration](../examples/consistency-providers.yaml):

```sh
tmb prepare-dataset --output results/evaluation.json --per-category 20 --seed 78213
tmb compare-dataset --config providers.local.yaml --dataset results/evaluation.json --repeats 2 --workers 4 --output results/audit --dry-run
tmb compare-dataset --config providers.local.yaml --dataset results/evaluation.json --repeats 2 --workers 4 --output results/audit
tmb report results/audit/run.json
```

Copy and customize the configuration first. The example has placeholder hosts and no keys. Twenty questions per subject gives 280 questions and 560 requests per endpoint with two repeats. There is no extra network request for analysis. This workflow uses the existing zero-shot MMLU-Pro [prompt and parser](dataset-protocol.md), with temperature/output limits supplied by the configuration. It remains a subset adaptation, not the official leaderboard evaluation.

## What is estimated

For question q and endpoints X,Y, let d_q(X,Y) be the fraction of the n² cross-response comparisons selecting different options. Keep the n responses and all endpoints together within a question cluster.

For baseline aliases A,B, estimate:

```
excess(X,Y) = mean_q[d_q(X,Y) - d_q(A,B)]
```

This is a paired contrast: difficult or ambiguous questions contribute both the pair's disagreement and the baseline's disagreement. Baseline uncertainty is included in the same resampling operation. The baseline pair itself is displayed once as a control; all other N(N−1)/2−1 pair contrasts are in the correction family. Accuracy is reported independently and never contributes to a consistency verdict.

**Scope of the estimand:** this measures mean answer-disagreement behavior over the sampled subject mixture. It is not a distance between complete response distributions. Two different answer distributions can produce the same mean disagreement; opposing question-level effects can cancel. A sharper or less stochastic provider can also differ from the baseline. Inspect question-level observations and the separate categorical MMD test. Passing this tolerance is weaker than establishing distributional equivalence.

## Missing observations

Transport errors, truncation, refusal, parser failure, suspected cached responses and missing requests never become valid answers. With K observed cross-response comparisons and D observed disagreements, bound the complete question's disagreement by:

```
lower = D / n²
upper = (D + n² - K) / n²
```

For a pair's excess disagreement, subtract the baseline's upper bound from the pair's lower bound, and the baseline's lower bound from the pair's upper bound. Shared missing observations may make these bounds conservative. They require no missing-at-random assumption. A few failures widen the interval instead of automatically destroying the entire comparison; too many failures trigger the predeclared coverage gate. API errors are never automatically retried.

## Approximate uncertainty and decisions

Resample whole questions with replacement **within each subject**, retaining all endpoints, repeats and missingness in each selected cluster. Use the same resampling indices for every contrast. This preserves pairing and the empirical subject mixture. For M planned non-baseline contrasts and family alpha, take the alpha/(2M) quantile of resampled lower means and the 1−alpha/(2M) quantile of resampled upper means.

This is a **percentile cluster bootstrap with Bonferroni tail allocation**, not an exact test or a finite-sample coverage guarantee. Correction does not repair a poorly calibrated bootstrap. The implementation requires at least 20 expected bootstrap draws in each corrected tail, a configurable minimum of 100 questions by default, and rejects wholly degenerate contrast samples because their bootstrap cannot quantify unseen variation. These are safeguards, not proofs of adequate power or coverage. Within-subject question dependence, small subject strata, rare events and unrepresentative selection can still invalidate the approximation.

| Result | Rule and interpretation |
|---|---|
| **within baseline tolerance** | The entire approximate simultaneous interval lies inside [−margin,+margin], the run meets coverage/comparability gates, and a baseline-versus-different-model contrast demonstrates positive excess beyond the margin. Supports this specified observable and tolerance only. |
| **beyond baseline tolerance** | The interval lies wholly above +margin or below −margin and the run meets gates. Evidence of a practically different disagreement pattern; the cause could be serving configuration. |
| **inconclusive** | The interval crosses a boundary, sensitivity was not demonstrated for a proposed consistency result, or collection, coverage, sample size, bootstrap resolution, degeneracy or known-condition checks fail. |

One different-model control demonstrates sensitivity to **that control**, not all substitutions. Synthetic operating-characteristic tests validate representative code paths, not real-provider false-positive rates. Independent pilot studies with several configurations and alternative models are necessary before using results for consequential decisions.

The original Holm-corrected categorical MMD test remains separate and unchanged. It asks whether parsed answer distributions differ and retains its complete-protocol requirement. Thus a report may show an inconclusive MMD test and a usable practical-tolerance interval. It can also show a small detectable distribution difference that falls within a practical tolerance. These address different questions.

## Reproducibility and departures

`protocol.consistency` records method `paired-disagreement-bootstrap-v1`, the baseline, tolerance and coverage gates. Config, dataset hash, sampling settings and text-storage policy contribute to the resume fingerprint. Changing the margin requires a new run. `analysis.consistency` records all contrasts, baseline bounds, effect bounds, approximate simultaneous intervals, coverage and reasons. Old runs without this predeclaration retain their original analysis; offline reporting does not retrofit a tolerance verdict.

This is a repository-specific procedure. It borrows the principle of a prespecified practical bound from [Lakens (2017), Equivalence Tests](https://doi.org/10.1177/1948550617697177), but **does not implement that paper's parametric TOST procedures**. Whole-question resampling builds on [Efron's bootstrap framework](https://doi.org/10.1214/aos/1176344552); this particular interval's live-provider coverage has not been established. [Gao, Liang and Guestrin's Model Equality Testing](https://arxiv.org/abs/2410.20247) informs the separate distribution test, not a claim that this excess-disagreement rule reproduces their method or power results.
