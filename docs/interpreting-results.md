# Reading a benchmark report

Read the protocol and coverage before the verdict. A comparison with different requested reasoning modes or a large number of failed responses does not isolate a checkpoint difference.

## Three different questions

**Accuracy** measures correct choices against dataset labels. Two models can have the same accuracy while making entirely different mistakes. The report includes observed correct/planned, valid coverage, question-cluster uncertainty and best/worst accuracy bounds for unavailable answers.

**Distribution testing** asks whether the parsed-choice distributions differ under the tested prompts. The categorical MMD statistic accounts for within-endpoint variation; its permutation p-value is Holm-adjusted across all planned pairs. A negative unbiased MMD estimate is allowed. A nonsignificant p-value means no difference was detected at this sample size and sensitivity, not that the models are equal. The original complete-protocol test remains inconclusive when any required response is unusable.

**Practical consistency** asks whether mean answer disagreement is close enough to a concurrent same-configuration repeat baseline. Its approximate interval includes baseline uncertainty, question variation, multiplicity allocation and worst-case missing-answer bounds. This optional analysis must be declared before collection. It is an observable-specific tolerance assessment, not a replacement for the distribution test.

## Worked example (illustrative, not a provider measurement)

Suppose a repeat baseline disagrees on 8% of cross-response comparisons. A candidate pair disagrees on 10%, giving **+2 percentage points** of excess disagreement. The prespecified tolerance is ±5 points.

| Approximate simultaneous interval for excess | Interpretation |
|---|---|
| [−1, +4] points | Within tolerance, if coverage/comparability gates pass and the different-model control demonstrates sensitivity. |
| [+7, +12] points | Beyond tolerance: the pair disagrees more than the repeat baseline by a practically meaningful amount. |
| [−12, −7] points | Beyond tolerance: the pair disagrees substantially less; a change in stochastic behavior also matters. |
| [+2, +8] points | Inconclusive: it crosses the tolerance boundary. |
| [−20, +20] points | Inconclusive: little precision, even though zero is included. |

The distribution test can detect a small difference while practical consistency remains within tolerance; they test different claims. Conversely, two distinct distributions can have the same disagreement rate. Inspect the per-question tables, including different wrong answers, to understand the result.

## Missing answers and uncertainty

An agreement range such as 90–92% can be a **finite-sample missing-answer bound**: it allows unavailable answers to agree or disagree in every possible way. It is not a population confidence interval. The practical-consistency section separately labels its approximate simultaneous bootstrap interval. The number of n² cross-response comparisons is not the independent sample size; the inference resamples whole questions.

A completed run can contain truncations, refusals, network errors, invalid formatting or suspected cache hits. Check the status counts. Missing usage is unknown spend, not free requests. A parser failure can reflect formatting rather than a wrong substantive answer; it still cannot silently become a successful observation.

## What to say

Use: “Within the predeclared baseline tolerance for mean answer disagreement on this dataset, with the reported approximate uncertainty and control sensitivity.” Name the baseline, margin, dataset, sample size and limitations.

Use: “Detectably different under this parsed-choice distribution test,” or “No difference detected at the tested sensitivity.” Serving configuration, precision, revision, instructions, caching and provider drift can all affect the result.

Avoid “verified authentic,” “95% real,” “same weights,” or interpreting the largest cluster as truth. A remote reference remains designated by the investigator. One different-model control supports discrimination against that model under this setup, not against all possible substitutions.

If results are inconclusive, a **new preplanned study** can use more independent questions, more repeats, better matched controls or adequate output limits. Keep its result distinct from earlier runs. Do not delete difficult questions, relabel prose after seeing answers, increase the tolerance until the provider passes, or retry only failed observations and treat the replacement set as the original experiment.
