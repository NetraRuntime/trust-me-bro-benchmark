"""Pinned public dataset acquisition, deterministic selection and answer parsing."""

import hashlib
import io
import json
import re
from collections import Counter
from pathlib import Path

import httpx

from .probes import digest
from .runner import atomic_json

DATASET = "TIGER-Lab/MMLU-Pro"
PROTOCOL = "mmlu-choice-v1"
PARSER = "choice-letter-v1"


def select_items(rows, per_category, seed):
    categories = sorted({r["category"] for r in rows})
    items = []
    for category in categories:
        candidates = [r for r in rows if r["category"] == category]
        if len(candidates) < per_category:
            raise ValueError("Not enough questions in every category")
        candidates.sort(key=lambda r: (digest([seed, category, r["question_id"]]), r["question_id"]))
        for r in candidates[:per_category]:
            items.append(
                {
                    "id": str(r["question_id"]),
                    "category": category,
                    "question": r["question"],
                    "options": r["options"],
                    "answer": r["answer"],
                }
            )
    return items


def prepare_dataset(output, per_category=10, seed=20260927, revision=None):
    if not 1 <= per_category <= 1000:
        raise ValueError("per-category must be between 1 and 1000")
    output = Path(output)
    if output.exists():
        raise ValueError("Dataset output already exists; use a new path")
    try:
        import pyarrow.parquet as pq
    except ImportError:
        raise ValueError("Install dataset support: pip install -e '.[datasets]'") from None
    with httpx.Client(timeout=90, follow_redirects=True) as client:
        if revision is None:
            response = client.get(f"https://huggingface.co/api/datasets/{DATASET}")
            response.raise_for_status()
            revision = response.json()["sha"]
        if not re.fullmatch(r"[a-f0-9]{40}", revision):
            raise ValueError("Dataset revision must be a full commit SHA")
        url = f"https://huggingface.co/datasets/{DATASET}/resolve/{revision}/data/test-00000-of-00001.parquet"
        response = client.get(url)
        response.raise_for_status()
    rows = pq.read_table(io.BytesIO(response.content)).to_pylist()
    items = select_items(rows, per_category, seed)
    package = {
        "protocol": PROTOCOL,
        "dataset": DATASET,
        "revision": revision,
        "split": "test",
        "source_url": url,
        "source_sha256": hashlib.sha256(response.content).hexdigest(),
        "license": "MIT (dataset card)",
        "selection_seed": seed,
        "per_category": per_category,
        "population_counts": dict(sorted(Counter(r["category"] for r in rows).items())),
        "items": items,
    }
    package["content_hash"] = digest(package)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(output, package)
    return load_dataset(output)


def load_dataset(path):
    package = json.loads(Path(path).read_text(encoding="utf-8"))
    unsigned = {k: v for k, v in package.items() if k != "content_hash"}
    if package.get("protocol") != PROTOCOL or digest(unsigned) != package.get("content_hash"):
        raise ValueError("Dataset protocol or content hash is invalid")
    items = package["items"]
    if not items or len({i["id"] for i in items}) != len(items):
        raise ValueError("Dataset must contain distinct question IDs")
    for item in items:
        if (
            not isinstance(item["question"], str)
            or not item["question"]
            or not 2 <= len(item["options"]) <= 10
            or not all(isinstance(o, str) for o in item["options"])
            or item["answer"] not in list("ABCDEFGHIJ"[: len(item["options"])])
        ):
            raise ValueError("Invalid multiple-choice dataset item")
    return package


def question_prompt(item):
    options = "\n".join(f"{chr(65 + i)}. {value}" for i, value in enumerate(item["options"]))
    return (
        "Select the single best answer to this multiple-choice question.\n\n"
        + item["question"]
        + "\n\n"
        + options
        + "\n\nReturn only the option letter. Do not include an explanation."
    )


def parse_choice(text, option_count):
    """Full-match grammar: cosmetic wrappers are ignored, ambiguous prose is rejected."""
    text = text.strip()
    # Permit one Markdown wrapper and an explicit Answer prefix; never hunt inside prose.
    if text.startswith("**") and text.endswith("**"):
        text = text[2:-2].strip()
    elif text.startswith("`") and text.endswith("`"):
        text = text[1:-1].strip()
    text = re.sub(r"^(?:answer|option)\s*:\s*", "", text, flags=re.IGNORECASE)
    match = re.fullmatch(r"(?:\(([A-Ja-j])\)|([A-Ja-j]))[.]?", text)
    if not match:
        return None
    choice = (match.group(1) or match.group(2)).upper()
    return choice if ord(choice) - 65 < option_count else None
