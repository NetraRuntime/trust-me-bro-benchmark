# Reading a benchmark report

Read the statistical verdict, protocol and coverage together. The primary question is whether providers' response distributions differ on the tested prompts under the requested settings.

## Primary outcomes

| Outcome | Meaning |
|---|---|
| **detectably different** | A valid completed categorical MMD permutation test has Holm-adjusted p at or below the recorded alpha. The tested answer distributions are statistically distinguishable under the sampling assumptions. |
| **no difference detected** | A valid completed test has adjusted p above alpha. It did not detect a difference at this sample size and sensitivity; this does not establish equality. |
| **inconclusive** | The required test could not support a verdict: for example, missing answers, insufficient permutation resolution or seeded sample coupling. This is not a nonsignificant completed test. |

A small statistically detectable difference can have little practical importance. Read MMD effect size, question-level differences and coverage as well as the p-value. Serving configuration, hidden instructions, precision and routing can affect answers; the test does not isolate weights as the cause.

The correction family contains every planned pair, including untestable pairs as p=1. Repeated studies need a separate cross-run multiplicity plan. A designated reference is simply an endpoint selected by the investigator; no majority vote establishes truth.

## Accuracy and disagreement

Accuracy is correct choices divided by planned responses. Missing answers receive no credit, while worst/best accuracy bounds show what unknown answers could change. A formatting failure is not automatically a substantive knowledge error. Accuracy intervals resample whole questions within subjects, retaining repeats; they are pointwise and do not establish a simultaneous provider ranking.

An agreement range such as 90–92% can be a finite-sample missing-answer bound: unavailable cross-response comparisons are allowed to agree or disagree. It is not a population confidence interval. The n² cross-response comparisons are not n² independent observations. Two providers can have equal accuracy while choosing different wrong answers.

Detailed tables include every disagreement and every question missing a planned response, including cases where the surviving choices agree. Valid/planned counts and failure statuses help explain inconclusive pairs.

## Optional repeat-baseline view

Version 0.3 reports excess disagreement and descriptive bootstrap intervals relative to a repeat baseline. An interval inside a recorded margin is a descriptive observation, not an equivalence/tolerance verdict. The bootstrap lacks calibrated simultaneous coverage, and control separation alone does not repair that limitation. Use the primary MMD test for significance.

Historical version 0.2 within/beyond-tolerance labels are displayed with an explicit calibration warning for traceability. They must not be used as validated equivalence conclusions. See the [baseline method](consistency.md).

## Evidence validation

Reports reject inconsistent protocol hashes, conflicting configuration, duplicate/out-of-range observation slots, invalid successful choices and stale final status totals. New dataset runs bind saved item metadata into the protocol fingerprint. To check original dataset linkage, use `tmb report RUN/run.json --dataset FROZEN.json`, or pass `dataset_path` to MCP `read_report`. Without it, linkage is explicitly unverified. Local hashes detect inconsistent edits; they do not prove actual API delivery or externally timestamped preregistration.

## Reporting a conclusion

Use: “Detectably different under this parsed-choice distribution test,” or “No difference detected on these prompts at the tested sample size.” Include the effect, adjusted p-value, alpha, planned comparison family and valid/planned sample counts.

For failed tests, say: “Inconclusive because required observations were unavailable,” naming the failures. Do not replace it with “not significantly different.” Avoid converting non-rejection into an identity or equivalence claim.

If coverage or power is inadequate, design a new study with independent pilot questions, a justified sample size, suitable controls, adequate output limits and a prespecified failure policy. Do not silently drop difficult questions, change parsers after seeing answers or retry only failures and present the replacements as the original experiment.
