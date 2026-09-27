# Dataset attribution and selection

The question material comes from **MMLU-Pro**, by Yubo Wang and colleagues:
[dataset card](https://huggingface.co/datasets/TIGER-Lab/MMLU-Pro),
[paper](https://arxiv.org/abs/2406.01574), and
[upstream project](https://github.com/TIGER-AI-Lab/MMLU-Pro).
The Hugging Face dataset card labels the dataset MIT. The upstream evaluation
code repository carries its own license; that evaluation code is not copied
into this campaign.

The [frozen dataset](dataset.json) retains the exact source URL, revision and
SHA-256. Questions, options and gold labels are unchanged from that source;
the package selects a balanced subset and stores only fields needed for this
evaluation. Gold labels are inherited from the dataset, not independently
adjudicated expert answers.

[Independent verification](dataset-verification.json) reconstructed the
selection directly from the pinned Parquet file. It checked every field and
gold-answer index for all 280 evaluation and 14 pilot questions. There are no
duplicate full prompts or pilot/evaluation full-prompt overlaps. Two evaluation
questions share a question stem but have different option sets; correlated
items remain a generalization limitation.

This campaign uses zero-shot direct answers and a strict option-letter parser.
Its scores are not comparable to the upstream full-dataset, reasoning-enabled
leaderboard without accounting for the different protocol.

To repeat the source check, install the dataset extra and run:

```sh
python -m pip install -e '.[datasets]'
python reports/2026-09-28-deepseek/verify_dataset.py
```

This downloads the pinned public dataset and makes no inference requests.
