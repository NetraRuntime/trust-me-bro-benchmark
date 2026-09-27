# DeepSeek provider benchmark — 28 September 2026

One main evaluation per model, using 280 questions across 14 subjects and four independently requested responses per question per route. Both use a 2,048-token ceiling. The setup pilot is excluded.

| Report | Distinct providers | Valid / planned answers | Known-usage estimate |
|---|---:|---:|---:|
| [DeepSeek V4.1 Flash](deepseek-v4.1-flash.md) | 7 + repeat control | 8,673/8,960 | $0.4076 |
| [DeepSeek V4 Flash 0731](deepseek-v4-flash-0731.md) | 6 + repeat control | 7,657/7,840 | $0.2684 |

Read the primary **answer-choice** result separately from the **API-outcome** supplement. API outcomes include formatting and delivery failures; significance there does not by itself establish different substantive answers. Incomplete answer-only comparisons remain inconclusive. Non-rejection does not prove equivalence.

Both reports share one Holm correction across all 98 planned tests, at alpha 0.05. The protocol and endpoint configurations were published before main collection. Provider selection was curated, not exhaustive.

- [Protocol and limitations](PROTOCOL.md)
- [Frozen plan](protocol.json) and [route catalog](route-catalog.json)
- [Independent dataset verification](dataset-verification.json)
- [Dataset attribution](DATASET.md)
- [Recorded runtime versions](runtime.json)
- [Reviewed evidence checksums](checksums.json)
- [Independent result verification](result-verification.json)
- [Machine-readable campaign analysis](campaign-analysis.json.gz)

## Reproduce offline

```sh
python -m pip install -e .
python reports/2026-09-28-deepseek/analyze.py
python reports/2026-09-28-deepseek/verify_results.py
```

Optional figures: `uv run --no-project --with matplotlib==3.10.3 python reports/2026-09-28-deepseek/plot.py`.

Costs are estimates from known token usage at recorded prices, not billing receipts. Missing usage, cache discounts and platform fees are not resolved. These reports are API observations, not independent certification of weights or provider internals.
