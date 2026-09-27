"""Validate evidence before inference. Local hashes detect edits, not forgery."""

from collections import Counter

from .adapters import payload
from .config import Config
from .probes import Probe, digest

SUPPORTED_VERSIONS = {"0.1.0", "0.2.0", "0.3.0"}
CONSISTENCY_METHOD = "paired-disagreement-descriptive-v2"
STATUSES = {
    "ok",
    "http_error",
    "transport_error",
    "timeout",
    "missing_api_key",
    "invalid_response",
    "refusal",
    "truncated",
    "empty",
    "unparseable",
    "unexpected_finish",
    "cache_suspected",
    "in_flight",
    "interrupted_unknown",
    "adapter_error_unknown",
}


def require_unseeded(config):
    if config.sampling.request_seed is not None:
        raise ValueError("Statistical collection requires request_seed: null for independent sampling")


def validate_observations(run, *, dataset, require_gold=True):
    """Also usable on analysis fixtures: no fingerprint needed to reject bad samples."""
    try:
        names = [e["name"] for e in run["config"]["endpoints"]]
        if len(names) < 2 or len(names) != len(set(names)):
            raise ValueError("Observation endpoints must be distinct")
        items = run["items"] if dataset else run["probes"]
        item_map = {i["id"]: i for i in items}
        if not items or len(item_map) != len(items):
            raise ValueError("Observation items must be nonempty and distinct")
        if dataset:
            n = run["protocol"]["repeats"]
            if type(n) is not int or n not in (2, 3, 4):
                raise ValueError("Dataset observations require 2-4 repeats")
            for item in items:
                if not isinstance(item["id"], str) or not item["id"]:
                    raise ValueError("Invalid item ID")
                count = item["option_count"]
                if type(count) is not int or not 2 <= count <= 10:
                    raise ValueError("Invalid item option count")
                if require_gold and item["answer"] not in list("ABCDEFGHIJ"[:count]):
                    raise ValueError("Invalid item answer")
                if require_gold and (not isinstance(item["category"], str) or not item["category"]):
                    raise ValueError("Invalid item category")
        seen, ids = set(), set()
        for row in run["requests"]:
            name, item_id = row["endpoint"], row["question_id" if dataset else "probe"]
            if name not in names or item_id not in item_map:
                raise ValueError("Observation references an unplanned endpoint or item")
            item = item_map[item_id]
            if not dataset:
                level = item["level"]
                if row["level"] != level or level > min(run["level"], 3):
                    raise ValueError("Observation references an unplanned level")
                n = run["config"]["sampling"]["repeats"][str(level)]
            repeat = row["repeat"]
            key = name, item_id, repeat
            if type(repeat) is not int or repeat not in range(n) or key in seen:
                raise ValueError("Duplicate or out-of-range observation repeat")
            seen.add(key)
            if "id" in row:
                if row["id"] != f"{item_id}:{repeat}:{name}" or row["id"] in ids:
                    raise ValueError("Invalid or duplicate observation ID")
                ids.add(row["id"])
            if row["status"] not in STATUSES:
                raise ValueError("Unknown observation status")
            if row["status"] == "ok":
                if dataset and row.get("choice") not in list("ABCDEFGHIJ"[: item["option_count"]]):
                    raise ValueError("Successful observation has an invalid choice")
                if not dataset and not isinstance(row.get("answer_hash"), str):
                    raise ValueError("Successful observation has no answer hash")
            if "text" in row and digest(row["text"]) != row.get("answer_hash"):
                raise ValueError("Observation text does not match its answer hash")
            if dataset and row["status"] == "ok" and "text" in row:
                from .datasets import parse_choice

                if parse_choice(row["text"], item["option_count"]) != row["choice"]:
                    raise ValueError("Stored choice does not match the response text")
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed observation evidence") from exc


def dataset_items(package):
    from .datasets import question_prompt

    return [
        {k: v for k, v in item.items() if k not in ("question", "options")}
        | {"option_count": len(item["options"]), "prompt_hash": digest(question_prompt(item))}
        for item in package["items"]
    ]


def validate_manifest(run, package=None, *, finalized=True):
    """Check declared protocol, observation structure, and optional frozen dataset.

    Journal checkpoints may have stale derived totals while calls are in flight;
    resume validates their primary evidence and recomputes totals on completion.
    """
    try:
        version = run["tool_version"]
        if version not in SUPPORTED_VERSIONS or run["schema_version"] not in (1, 2):
            raise ValueError("Unsupported manifest version; use its recorded tool version")
        config = Config.model_validate(run["config"])
        dataset = run.get("kind") == "choice-dataset"
        validate_observations(run, dataset=dataset)
        warnings = [
            "Local hashes detect inconsistent edits; they do not prove preregistration or API delivery."
        ]
        if dataset:
            protocol = run["protocol"]
            settings = config.sampling
            expected = {
                "seed": settings.random_seed,
                "permutations": settings.permutations,
                "bootstrap": settings.bootstrap,
                "alpha": settings.alpha,
                "parser": "choice-letter-v1",
                "prompt": "zero-shot-direct-choice-v1",
                "schedule": "randomized question/endpoint blocks",
            }
            if any(protocol[k] != v for k, v in expected.items()):
                raise ValueError("Protocol settings disagree with collection configuration")
            if type(protocol["workers"]) is not int or not 1 <= protocol["workers"] <= len(config.endpoints):
                raise ValueError("Invalid protocol worker count")
            spec = protocol.get("consistency")
            if bool(spec) != bool(config.consistency):
                raise ValueError("Consistency declaration disagrees with collection configuration")
            if spec:
                method = CONSISTENCY_METHOD if version == "0.3.0" else "paired-disagreement-bootstrap-v1"
                if spec != config.consistency.model_dump(mode="json") | {"method": method}:
                    raise ValueError("Consistency declaration disagrees with collection configuration")
                if protocol.get("same_configuration_pair") != list(config.consistency.baseline):
                    raise ValueError("Repeat control disagrees with declared baseline")
            same = protocol.get("same_configuration_pair")
            if same:
                endpoints = {e.name: e for e in config.endpoints}
                if len(same) != 2 or len(set(same)) != 2 or not set(same) <= endpoints.keys():
                    raise ValueError("Invalid same-configuration control")
                if endpoints[same[0]].model_dump(exclude={"name", "prices"}) != endpoints[same[1]].model_dump(
                    exclude={"name", "prices"}
                ):
                    raise ValueError("Repeat-control endpoint configurations differ")
            fingerprint = digest(
                [
                    run["config"],
                    run["dataset"]["content_hash"],
                    protocol,
                    run["store_text"],
                    version,
                ]
            )
            if (version == "0.3.0" or "items_hash" in protocol) and protocol.get("items_hash") != digest(
                run["items"]
            ):
                raise ValueError("Dataset item metadata does not match its protocol-bound hash")
            if package is not None:
                if (
                    digest({k: v for k, v in package.items() if k != "content_hash"})
                    != package["content_hash"]
                ):
                    raise ValueError("Supplied frozen dataset has an invalid content hash")
                if run["dataset"] != {k: v for k, v in package.items() if k != "items"}:
                    raise ValueError("Supplied dataset does not match the manifest provenance")
                if dataset_items(package) != run["items"]:
                    raise ValueError("Manifest items do not match the supplied frozen dataset")
                dataset_check = "Items verified against the supplied frozen dataset."
            else:
                dataset_check = "Original dataset linkage unverified; supply the frozen dataset to verify it."
                warnings.append(dataset_check)
            planned = len(run["items"]) * protocol["repeats"] * len(config.endpoints)
        else:
            public = all("prompt" in p for p in run["probes"])
            if public:
                probes = [
                    Probe.model_validate({k: p[k] for k in ("id", "level", "role", "prompt")})
                    for p in run["probes"]
                ]
                if digest([p.model_dump() for p in probes]) != run["suite_hash"]:
                    raise ValueError("Saved public probes do not match the suite hash")
                if any(digest(p["prompt"]) != p["prompt_hash"] for p in run["probes"]):
                    raise ValueError("Saved public prompt does not match its hash")
            else:
                warnings.append(
                    "Original private prompt linkage unverified; private text is not in the manifest."
                )
            fingerprint = digest(
                {
                    "config": run["config"],
                    "suite": run["suite_hash"],
                    "level": run.get("collection_level", run["level"]),
                    "store_text": run["store_text"],
                    "version": version,
                }
            )
            planned = len(config.endpoints) * sum(
                config.sampling.repeats[p["level"]]
                for p in run["probes"]
                if p["level"] <= min(run["level"], 3)
            )
            dataset_check = "Not a dataset run."
        if fingerprint != run["protocol_hash"]:
            raise ValueError("Manifest protocol hash does not match the recorded collection settings")
        endpoints = {e.name: e for e in config.endpoints}
        for row in run["requests"]:
            level = 3 if dataset else row["level"]
            expected_settings = payload(
                endpoints[row["endpoint"]],
                Probe(id="validation", level=level, prompt="not sent"),
                config.sampling,
                level,
                row["repeat"],
            )
            expected_settings.pop("messages")
            if row["requested_settings"] != expected_settings:
                raise ValueError("Recorded request settings disagree with the frozen configuration")
        if finalized:
            if any(r["status"] == "in_flight" for r in run["requests"]):
                raise ValueError("Run has in-flight observations; resume collection before reporting")
            if run["remaining_requests"] != planned - len(run["requests"]):
                raise ValueError("Manifest remaining-request total is inconsistent")
            if run["request_counts"] != dict(Counter(r["status"] for r in run["requests"])):
                raise ValueError("Manifest status totals disagree with observations")
        return {"protocol_hash": "verified", "dataset": dataset_check, "warnings": warnings}
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError("Malformed run manifest") from exc


def sampling_issue(run):
    """Historical seeded data can be displayed, but cannot silently support inference."""
    if run["config"].get("sampling", {}).get("request_seed") is not None:
        return "Shared request seeds violate the independent-sampling design; descriptive results only"
    return None
