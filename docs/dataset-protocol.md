# MMLU-Pro parsed-choice protocol v1

This protocol compares substantive answers on a published dataset. It is separate from the small `starter-1` suite and its levels. It implements neither KBF nor RUT, and it is not a full or official MMLU-Pro leaderboard evaluation.

The optional [descriptive baseline comparison](consistency.md) propagates missing-answer bounds relative to repeat variability while retaining this page's original distribution test and strict failure rules. Version 0.3 does not issue tolerance/equivalence verdicts from its uncalibrated bootstrap. It cannot be retroactively attached to an old run by the report command.

## Dataset and selection

`tmb prepare-dataset` downloads the test split of [TIGER-Lab/MMLU-Pro](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro), pins its full Hugging Face commit SHA, and records the Parquet SHA-256. Within each subject, sort question IDs by SHA-256 of the JSON-encoded selection seed, category and ID; take a fixed number from each category. This is reproducible and independent of model answers. The frozen JSON includes source provenance, selection rules, questions, options, gold labels and a content hash. It refuses overwrite.

The initial live protocol selects 10 questions from each of 14 subjects (140 total), seed 20260927. Results estimate performance for this equally weighted subject sample, not the original dataset's subject frequencies. Public questions may have appeared in training. They provide broad task coverage, not adversarial secrecy.

## Collection and parsing

Each request contains the question, labeled options and an instruction to return only the best option letter. Gold answers and dataset explanations never enter the prompt. This is zero-shot, direct-answer prompting, departing from the official benchmark's example/reasoning conventions. Scores must not be compared directly with its leaderboard.

Request 2–4 independent responses per question per endpoint. The initial run uses two, temperature 0.6, top-p 1, 256 output tokens, no request seed and reasoning requested disabled. Record provider routes, response IDs, metadata, timestamps and requested settings. Controls being accepted does not prove they were honored.

`choice-letter-v1` parses a complete string containing one valid option letter, ignoring letter case, surrounding whitespace, one simple Markdown wrapper, an optional `Answer:`/`Option:` prefix, parentheses and a final period. It does not extract a convenient letter from arbitrary prose. Ambiguous, invalid, empty, refused, truncated, cached and failed responses remain explicit failures. There is no normalization of question text or code identifiers.

Question order and endpoint submission order are randomized from the recorded seed. Endpoint requests within a question/repeat block may run concurrently, with a configurable worker bound. Every block is journaled before dispatch; the main thread atomically saves each result. The next block waits for the previous one. No API retries or provider fallback. Resume does not resend interrupted or failed observations. Already in-flight requests can finish after a reported budget overrun; no further blocks launch.

Statistical collection requires a null API request seed. A shared seed across endpoint aliases can couple observations; the separate local random seed still controls schedule and offline analysis reproducibility. Before reporting, validate unique planned question/endpoint/repeat slots, legal choices, status totals and the frozen protocol hash. New dataset manifests bind saved item metadata into that fingerprint. Supply the frozen dataset to verify original item linkage; without it reports explicitly mark that linkage unverified.

## Three separate outputs

1. **Capability:** correct responses divided by planned responses, per subject and overall. Missing/invalid answers are not credited; JSON also gives lower/upper accuracy bounds for missing answers. Coverage is always shown. Pointwise intervals resample whole questions within subjects, keeping repeats together.
2. **Answer disagreement:** for each question, the fraction of all cross-endpoint response pairs selecting different options, averaged across questions. This includes different wrong answers even when accuracy is identical. Report a paired accuracy gap separately, with question-cluster intervals. High disagreement is not itself a hypothesis-test verdict.
3. **Answer-distribution test:** unbiased categorical MMD squared with kernel k(a,b)=1 for the same parsed option and 0 otherwise. Compute within each question and average equally. Whitespace and capitalization cannot create a difference between identical parsed choices.

## Statistical procedure

Null: for every sampled question, endpoints have the same distribution over parsed choices under the requested conditions. For each question with n responses from each endpoint, pool 2n observations and enumerate all combinations assigning n observations to the left group. Randomly draw an assignment independently for each question, average the corresponding MMD statistics, and repeat B times. Use p=(1 + number of permuted statistics at least as large as observed)/(B+1), with a 1e-12 tie tolerance. This preserves question difficulty and conditional label exchangeability.

The initial run predeclares B=9,999, alpha=0.05 and Holm family-wise correction across **all 21 pairs** of seven logical endpoints. Untestable pairs count as p=1. Report a detectable difference only after correction. Any required failed or invalid sample makes that pair's complete-protocol inference inconclusive; do not silently analyze a selected complete-case subset. Insufficient permutation resolution also yields inconclusive.

Negative unbiased MMD estimates are retained. MMD effect intervals use 1,000 subject-stratified question-cluster bootstrap replicates; these are descriptive, not calibrated near the null. Accuracy, disagreement and effect intervals are pointwise rather than simultaneous. Correlated questions, provider drift and sample dependence can weaken the assumptions. Two repeats per question limit power; a non-rejection is not equivalence.

### Descriptive missing-answer supplement

Reports also bound finite-sample answer agreement without discarding failures. With Q questions and n repeats per endpoint, there are Q*n*n planned cross-response comparisons. Let K have two observed valid choices, and let D of those disagree. The disagreement fraction for the planned sample lies within [D/(Q*n*n), (D+Q*n*n-K)/(Q*n*n)]. Agreement bounds are the complements. These deliberately conservative bounds allow all missing comparisons to agree or disagree. They are not population confidence intervals, independent trial counts, significance tests or identity verdicts. The initial run's report added this supplement during collection; its frozen primary procedure and verdict rules were unchanged.

This adapts the two-sample framing and categorical/one-hot kernel discussed by [Gao, Liang and Guestrin](https://arxiv.org/abs/2410.20247) to parsed task answers and balanced question strata. It does not reproduce their preferred Hamming-kernel experiment or transfer their measured power. Synthetic null and alternate distributions test the implementation. Real-provider power remains uncalibrated.

## Controls and reference

The initial OpenRouter run uses five pinned DeepSeek routes, a Gemini different-model control and a second independently queried logical endpoint with identical DeepInfra settings. The latter is a same-configuration repeat control, not evidence of independently verified weights. Both aliases can be in flight together; hidden batching and response caching remain caveats. One such comparison cannot estimate a general false-positive rate. No thresholds are tuned using these results.

The user-designated DeepInfra reference is not certified truth. Known configuration mismatches make matched-reference attribution inconclusive. All provider comparisons remain relative behavioral evidence. No majority vote, capability score or non-rejection proves authenticity.

## Reproducible commands

```sh
python -m pip install -e '.[datasets]'
tmb prepare-dataset --output results/mmlu-140.json --per-category 10 --seed 20260927
tmb compare-dataset --config providers.local.yaml --dataset results/mmlu-140.json --repeats 2 --workers 2 --output results/mmlu --dry-run
tmb compare-dataset --config providers.local.yaml --dataset results/mmlu-140.json --repeats 2 --workers 2 --output results/mmlu
tmb report results/mmlu/run.json
```

Set `sampling.temperature`, `sampling.top_p`, `sampling.random_seed`, `sampling.permutations`, `sampling.bootstrap`, `sampling.alpha`, and `sampling.max_tokens[3]` in the normal provider config. Other legacy level budgets and `min_samples` do not apply to this separate protocol. Set request/token/cost limits large enough for the entire dry-run plan; over-budget plans fail before dispatch. Prices and byte-based input reservations are estimates, not billing guarantees.

Use `--same-configuration-pair NAME_A NAME_B` only for two entries with identical endpoint/control settings. Use `--store-text` to retain redacted original responses for parser review; the default stores parsed choices and hashes. The frozen local dataset file is required to recollect prompts. `run.json` holds the item IDs, gold labels, hashes, parsed samples, protocol and all statistics needed for offline analysis. API keys remain environment-only.
