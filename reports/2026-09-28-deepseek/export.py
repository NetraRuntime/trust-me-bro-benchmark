"""Export authorized public evidence without changing original run manifests."""

import argparse
import gzip
import hashlib
import json
import os
import re
from pathlib import Path

from tmb.datasets import load_dataset
from tmb.validation import validate_manifest

ROOT = Path(__file__).resolve().parent
SLUGS = ("deepseek-v4.1-flash", "deepseek-v4-flash-0731")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "source", type=Path, help="Directory containing the two completed model run directories"
    )
    args = parser.parse_args()
    dataset = load_dataset(ROOT / "dataset.json")
    exports = []
    for slug in SLUGS:
        source = args.source / slug / "run.json"
        original = source.read_bytes()
        run = json.loads(original)
        validate_manifest(run, dataset)
        if run["remaining_requests"]:
            raise ValueError("Collection is incomplete; do not publish a completed-study report")
        run.pop("analysis", None)  # Recompute with the prespecified cross-study correction.
        for row in run["requests"]:
            row.pop("response_id", None)
            row.pop("text", None)
        run["publication"] = {
            "original_manifest_sha256": hashlib.sha256(original).hexdigest(),
            "collection_source_commit": "4ecc14fe32cebd0fbb4528c3b331c92ad5211ca2",
            "excluded_fields": ["analysis", "requests[].response_id", "requests[].text"],
            "note": "Reviewed public derivative; credentials and raw response text are excluded. Local original remains unchanged.",
        }
        payload = json.dumps(run, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
        if re.search(r"\b(?:sk[-_][A-Za-z0-9_-]{12,}|ghp_[A-Za-z0-9]{20,})\b|Bearer\s+\S+", payload):
            raise ValueError("Potential credential in publication evidence")
        for key in ("NETRA_API_KEY", "OPENROUTER_API_KEY"):
            secret = os.environ.get(key)
            if secret and secret in payload:
                raise ValueError("Environment credential found in publication evidence")
        validate_manifest(run, dataset)
        assert source.read_bytes() == original
        exports.append((slug, payload.encode("utf8"), run["publication"]))
    (ROOT / "evidence").mkdir(exist_ok=True)
    checksums = {}
    for slug, payload, publication in exports:
        output = ROOT / "evidence" / f"{slug}.json.gz"
        output.write_bytes(gzip.compress(payload, mtime=0))
        checksums[slug] = publication | {
            "public_json_sha256": hashlib.sha256(payload).hexdigest(),
            "public_gzip_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        }
    (ROOT / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf8")
    print("Exported two reviewed evidence bundles; original manifests are unchanged.")


if __name__ == "__main__":
    main()
