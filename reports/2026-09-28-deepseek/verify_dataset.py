"""Independently reconstruct the frozen selection from pinned upstream data.

Requires the datasets extra. Downloads the pinned public dataset only; no
inference API is contacted and no credentials are used.
"""

import hashlib
import io
import json
from collections import Counter
from pathlib import Path

import httpx
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent


def main():
    evaluation = json.loads((ROOT / "dataset.json").read_text(encoding="utf8"))
    pilot = json.loads((ROOT / "pilot-dataset.json").read_text(encoding="utf8"))
    response = httpx.get(evaluation["source_url"], follow_redirects=True, timeout=90)
    response.raise_for_status()
    sha = hashlib.sha256(response.content).hexdigest()
    assert sha == evaluation["source_sha256"] == pilot["source_sha256"]
    rows = pq.read_table(io.BytesIO(response.content)).to_pylist()
    selected, held_out = [], []
    for category in sorted({r["category"] for r in rows}):

        def order(row, category=category):
            text = json.dumps([20260928, category, row["question_id"]], sort_keys=True, ensure_ascii=False)
            return hashlib.sha256(text.encode("utf8")).hexdigest(), row["question_id"]

        pool = sorted([r for r in rows if r["category"] == category], key=order)[:21]
        for index, row in enumerate(pool):
            item = {
                "id": str(row["question_id"]),
                "category": category,
                "question": row["question"],
                "options": row["options"],
                "answer": row["answer"],
            }
            assert ord(row["answer"]) - 65 == row["answer_index"]
            (selected if index < 20 else held_out).append(item)
    assert selected == evaluation["items"]
    assert held_out == pilot["items"]
    assert not {r["id"] for r in selected} & {r["id"] for r in held_out}
    prompts = [(r["question"], tuple(r["options"])) for r in selected]
    pilot_prompts = {(r["question"], tuple(r["options"])) for r in held_out}
    assert not set(prompts) & pilot_prompts
    result = {
        "source_url": evaluation["source_url"],
        "source_sha256": sha,
        "upstream_rows": len(rows),
        "evaluation_items_exactly_verified": len(selected),
        "pilot_items_exactly_verified": len(held_out),
        "disjoint": True,
        "evaluation_subject_counts": dict(Counter(i["category"] for i in selected)),
        "selected_gold_indices_match": True,
        "duplicate_evaluation_question_texts": sum(
            n - 1 for n in Counter(i["question"] for i in selected).values()
        ),
        "duplicate_evaluation_full_prompts": len(prompts) - len(set(prompts)),
        "pilot_evaluation_full_prompt_overlap": 0,
    }
    (ROOT / "dataset-verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
