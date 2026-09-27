# DeepSeek provider comparison: evaluation protocol

This protocol is frozen after a separate setup pilot and before the main
evaluation. The two studies compare DeepSeek V4.1 Flash and DeepSeek V4 Flash
0731 across explicitly pinned OpenRouter routes and a direct Netra endpoint.
Each model will have its own report. This is one main evaluation per model,
with a 2,048-token output ceiling; there is no separate 512-token experiment.

## Sample and controls

- 280 MMLU-Pro test questions, 20 per subject across 14 subjects, from revision
  `b189ec765aa7ed75c8acfea42df31fdae71f97be`.
- Hash-order selection seed 20260928 selects 21 questions per subject. The
  first 20 are evaluation questions; the 21st is reserved for the setup pilot.
  The 14 pilot questions do not enter the main evaluation.
- Four independently requested responses per question per logical endpoint.
  A second DeepInfra alias is the same-configuration repeat control.
- Temperature 0.6, top-p 1, reasoning requested disabled, no API request seed,
  non-streaming requests, and a 120-second timeout. The output cap includes
  any reasoning the provider nevertheless generates.
- Randomized question/endpoint blocks; endpoints within a block run
  concurrently. Both model studies may run concurrently. No API retry or
  provider fallback. The two DeepInfra aliases can be in flight together.
- Seven distinct providers for V4.1 Flash and six for V4 Flash 0731, plus one
  repeat alias in each study: 8,960 and 7,840 planned requests respectively.

Provider names, exact model IDs, route tags, requested controls and price
assumptions are in [configs](configs). Providers are a curated available
roster, not a random or exhaustive sample of the market. The endpoint catalog
does not certify identical weights, precision, templates or serving software.
V4 Flash uses **0731 on both sides**; it is not silently substituted with
V4.1 or the unsuffixed OpenRouter V4 Flash catalog entry.

## Pilot decisions

The pilot checked routing, formatting, completion and cost, not evaluation
accuracy or significance. V4.1 completed 224/224 pilot requests with valid
choices. V4 Flash 0731 had 204 valid choices, 14 formatting failures and six
HTTP 429 responses. All six HTTP failures came from its Parasail route, which
was excluded before evaluation. Parasail remains in the V4.1 roster, where
its pilot succeeded. The [pilot summary](pilot-summary.json) preserves these
counts; no difficult evaluation questions are removed.

Some V4 Flash pilot responses included option text after the letter. The
existing strict parser is retained unchanged: these are formatting failures,
not silently extracted answers. Neither the prompt nor parser is tuned on
main-evaluation outputs.

## Prespecified analysis

**Primary: answer-choice distribution.** The null is equal distributions over
parsed choices for every sampled question. Average the unbiased categorical
MMD squared equally over questions. Enumerate balanced label assignments
within each question and draw 99,999 permutations. Use the plus-one p-value.
Any required invalid or failed answer makes this complete-protocol test
inconclusive; it is not a nonsignificant completed test.

**Supplement: API-outcome distribution.** Encode each recorded attempt as its
parsed choice, or its recorded failure status when no valid choice is
delivered. Apply the same categorical statistic and question-stratified
permutation procedure. This tests the delivered service, including formatting,
refusal, truncation, HTTP errors, transport errors and timeouts. It does not
isolate semantic answer differences. Unknown delivery, local credential
failure, suspected cached completions or missing attempts invalidate the
affected comparison. Account-credit exhaustion or confirmed misrouting also
invalidates affected inference rather than being attributed to model behavior.

Use **one Holm family across all 98 planned tests**: 49 endpoint pairs across
the two models, each with an answer-choice and an API-outcome test. Invalid
tests enter the family as p=1. Family alpha is 0.05. The campaign reports use
these combined adjusted values, superseding the tool's narrower per-run
adjustment. Tests involving the repeat aliases stay in the family.

Report effect sizes, corrected p-values, coverage, exact failure counts,
accuracy bounds and finite-sample agreement bounds. Resample whole questions
within subjects for 2,000 descriptive bootstrap draws; intervals are pointwise
and do not establish equivalence. Per-subject scores, latency and listed-price
usage costs are descriptive. No threshold is selected after viewing evaluation
results, and no failing observations are retried or dropped.

## Interpretation and reproducibility

A significant API-outcome result can be caused by delivery or formatting
behavior. It must not be relabeled as proof of different model weights or
different substantive answers. Non-rejection does not establish equality.
The repeat control is diagnostic; a single control does not estimate a general
false-positive rate. No live different-model positive control or calibrated
power guarantee is claimed. Public benchmark contamination, hidden routing,
provider drift and dependence remain limitations.

Latency is non-streaming request latency from this client, not time to first
token or isolated inference throughput. API usage estimates omit unknown
failed-request billing, cache discounts and platform fees. Requests are
reserved conservatively against a $30 campaign budget; missing usage is
reported as unknown, not free.

The [machine-readable protocol](protocol.json), [frozen evaluation
dataset](dataset.json), [pilot dataset](pilot-dataset.json), configurations and
analysis source are committed before main collection. Approved public reports
will include reviewed parsed-observation evidence, without credentials, raw
response text or provider response IDs. Source manifest hashes will identify
the local originals; local hashes are not API-delivery attestations.
