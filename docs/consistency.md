# Descriptive repeat-baseline comparison

The primary benchmark asks whether providers have statistically distinguishable response distributions. The categorical MMD permutation test, with Holm correction, answers that question. It does not require an equivalence margin or a trusted original-weights deployment.

The optional `consistency` configuration adds a descriptive comparison with repeat variability. **New runs always report this view as descriptive only.** A percentile bootstrap interval is not a calibrated equivalence test, even with Bonferroni tail allocation. Version 0.3 therefore stops producing within/beyond-tolerance verdicts from this method.

## Configure the optional view

Use two independently queried aliases of exactly the same endpoint settings as the baseline, candidate endpoints, and a different-model control. Baseline aliases must match except for name and prices. Shared infrastructure, caching and temporal correlation remain limitations. Statistical collection requires `sampling.request_seed: null`; common API seeds can couple the aliases. The separate local `random_seed` controls reproducible scheduling and analysis.

```yaml
consistency:
  baseline: [reference, reference_repeat]
  margin: 0.05
  min_questions: 100
  min_per_subject: 5
  max_missing_fraction: 0.05
sampling:
  request_seed: null
  bootstrap: 10000
  alpha: 0.05
```

The margin is a recorded comparison aid in percentage points of excess disagreement, not a significance threshold or a certified acceptance rule. Choose it before inspecting results and explain its practical meaning. The complete [example configuration](../examples/consistency-providers.yaml) uses placeholder hosts.

## Observable and missing-answer bounds

For each question q and endpoints X,Y, calculate the fraction of all n² cross-response pairs selecting different options. For baseline aliases A,B:

```
excess(X,Y) = mean_q[d_q(X,Y) - d_q(A,B)]
```

This estimates mean disagreement relative to the observed repeat baseline. It is not a distance between full answer distributions. Opposing question-level differences can cancel, and distinct distributions can have equal disagreement rates. Accuracy stays separate.

With K observed cross-response comparisons and D observed disagreements on a question:

```
lower = D / n²
upper = (D + n² - K) / n²
```

Bound the excess using pair-lower minus baseline-upper and pair-upper minus baseline-lower. These bounds preserve failures without assuming missing-at-random. They are conservative finite-sample bounds, not confidence intervals. The n² cross-response pairs are not independent samples.

## Descriptive bootstrap

Resample whole questions within subjects, keeping all endpoints, repeats and failures together. Use the same cluster indices for all contrasts. For M planned non-baseline contrasts, report the alpha/(2M) quantile of resampled lower means and the 1-alpha/(2M) quantile of resampled upper means.

The report records `descriptive_bootstrap_interval`, its `interval_position` relative to the margin, missingness and quality-gate reasons. `control_separation_observed` describes a separated control interval, not an established power or sensitivity guarantee. Every new pair has `verdict: descriptive only`.

The numerical checks retain a minimum question count, minimum subject count, missing-answer limit, nondegeneracy diagnostic and at least 20 expected bootstrap draws per allocated tail. They do not establish statistical coverage. Increasing bootstrap draws only improves Monte Carlo resolution.

A rare-question counterexample explains the limitation: with 100 questions and one observed disagreeing question, a nondegenerate bootstrap can place its upper endpoint at 5% even when the population disagreement exceeds 5%. Across several candidates, misleading inside-margin intervals can occur more often than nominal family alpha. Bonferroni allocation cannot repair undercoverage of each interval.

For significance, inspect the separate categorical MMD test. It retains its strict complete-protocol rule. Missing required answers yield **inconclusive**, not a nonsignificant result. This descriptive supplement does not override that verdict.

## Reproducibility and historical reports

New collections record method `paired-disagreement-descriptive-v2`. Configuration, dataset hash, saved item-metadata hash, protocol, text policy and tool version determine the resume fingerprint. Changing the recorded margin requires a new collection. CLI and MCP validate this fingerprint before reporting; local hashes do not prove external preregistration.

Old 0.2 manifests retain method `paired-disagreement-bootstrap-v1`. Their original calculations and labels can be reproduced for traceability, but reports explicitly warn that these historical tolerance labels have unestablished calibration. They are not validated equivalence conclusions. Old runs without a declared baseline do not acquire one retrospectively. Historical seeded inference is marked inconclusive.

This is a repository-specific descriptive procedure. [Efron's bootstrap framework](https://doi.org/10.1214/aos/1176344552) motivates resampling; it does not establish coverage of this particular construction. [Lakens on equivalence](https://doi.org/10.1177/1948550617697177) discusses prespecified bounds, but this code does not implement parametric TOST. [Model Equality Testing](https://arxiv.org/abs/2410.20247) informs the separate distribution test, not a claim that this baseline comparison reproduces that paper's method or power.
