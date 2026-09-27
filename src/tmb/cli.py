"""Small standard-library CLI with privacy-safe errors."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import yaml
from pydantic import ValidationError

from . import __version__
from .adapters import now
from .analysis import analyze
from .config import load_config
from .probes import load_probes
from .report import render
from .runner import atomic_json, benchmark, estimate, plan
from .validation import validate_manifest


def main():
    parser = argparse.ArgumentParser(
        prog="tmb", description="Compare behavior. Never certify model identity."
    )
    parser.add_argument("--version", action="version", version=__version__)
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo", help="Run synthetic distribution tests and baseline diagnostics offline")
    demo.add_argument("--output", type=Path, default=Path("results/demo"))
    demo.add_argument("--prepare-only", action="store_true", help="Write fixtures for CLI/MCP use without collecting")
    bench = commands.add_parser("benchmark", help="Run cumulative test levels")
    bench.add_argument("--config", type=Path, required=True)
    bench.add_argument("--level", type=int, choices=range(5), default=1)
    bench.add_argument("--output", type=Path, default=Path("results/quick"))
    bench.add_argument("--resume", action="store_true")
    bench.add_argument(
        "--dry-run", action="store_true", help="Show request/token/cost plan without API calls"
    )
    bench.add_argument(
        "--store-text", action="store_true", help="Save redacted response text; may contain sensitive data"
    )
    report = commands.add_parser("report", help="Recompute analysis and Markdown offline")
    report.add_argument("manifest", type=Path)
    report.add_argument("--output", type=Path)
    report.add_argument("--dataset", type=Path, help="Verify saved item metadata against the frozen dataset")
    report.add_argument(
        "--reference", help="Designate a reference offline; write a separate derived JSON/report"
    )
    prepare = commands.add_parser("prepare-dataset", help="Download and freeze a balanced MMLU-Pro subset")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--per-category", type=int, default=10)
    prepare.add_argument("--seed", type=int, default=20260927)
    prepare.add_argument("--revision")
    dataset = commands.add_parser("compare-dataset", help="Compare parsed answers on a frozen dataset")
    dataset.add_argument("--config", type=Path, required=True)
    dataset.add_argument("--dataset", type=Path, required=True)
    dataset.add_argument("--output", type=Path, required=True)
    dataset.add_argument("--repeats", type=int, choices=(2, 3, 4), default=2)
    dataset.add_argument("--workers", type=int, default=1)
    dataset.add_argument("--same-configuration-pair", nargs=2)
    dataset.add_argument("--resume", action="store_true")
    dataset.add_argument("--store-text", action="store_true")
    dataset.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    try:
        if args.command == "demo":
            from .choice_analysis import render_choices
            from .dataset_runner import compare_dataset
            from .demo import prepare_demo

            config, package = prepare_demo(args.output)
            if args.prepare_only:
                print(f"Synthetic fixtures: {args.output}")
                return 0
            run = compare_dataset(config, package, args.output / "run", workers=4)
            destination = args.output / "run" / "report.md"
            destination.write_text(render_choices(run), encoding="utf8")
            print(f"Synthetic demonstration (no real providers): {destination}")
            return 0
        if args.command == "prepare-dataset":
            from .datasets import prepare_dataset

            result = prepare_dataset(args.output, args.per_category, args.seed, args.revision)
            print(f"Frozen {len(result['items'])} questions; hash {result['content_hash']}")
            return 0
        if args.command == "compare-dataset":
            from .choice_analysis import render_choices
            from .dataset_runner import compare_dataset, dataset_plan
            from .datasets import load_dataset

            config = load_config(args.config)
            package = load_dataset(args.dataset)
            if args.dry_run:
                print(
                    json.dumps(
                        estimate(dataset_plan(config, package, args.repeats, config.sampling.random_seed)),
                        indent=2,
                    )
                )
                return 0
            run = compare_dataset(
                config,
                package,
                args.output,
                args.repeats,
                args.workers,
                args.resume,
                args.store_text,
                args.same_configuration_pair,
                progress=lambda n, total: print(f"{n}/{total} requests", flush=True),
            )
            (args.output / "report.md").write_text(render_choices(run), encoding="utf8")
            print(f"Report: {args.output / 'report.md'}; statuses: {run['request_counts']}")
            return int(run["remaining_requests"] > 0 or any(r["status"] != "ok" for r in run["requests"]))
        if args.command == "report":
            run = json.loads(args.manifest.read_text(encoding="utf-8"))
            if args.output and args.output.resolve() == args.manifest.resolve():
                raise ValueError("Report output must not overwrite the evidence manifest")
            package = None
            if args.dataset:
                from .datasets import load_dataset

                if run.get("kind") != "choice-dataset":
                    raise ValueError("--dataset verification requires a dataset manifest")
                package = load_dataset(args.dataset)
            run["validation"] = validate_manifest(run, package)
            if run.get("kind") == "choice-dataset":
                from .choice_analysis import analyze_choices, render_choices

                if args.reference:
                    raise ValueError(
                        "Dataset reference is frozen in collection config; do not redesignate offline"
                    )
                run["analysis"] = analyze_choices(run)
                destination = args.output or args.manifest.with_name("report.md")
                destination.write_text(render_choices(run), encoding="utf8")
                print(f"Report: {destination}")
                return 0
            default_name = (
                "report.md" if args.manifest.name == "run.json" else args.manifest.with_suffix(".md").name
            )
            destination = args.output or args.manifest.with_name(
                "reference-report.md" if args.reference else default_name
            )
            if args.reference:
                eligible = {
                    e["name"] for e in run["config"]["endpoints"] if e.get("role", "candidate") == "candidate"
                }
                if args.reference not in eligible or run["level"] < 3:
                    raise ValueError("Reference must be a candidate endpoint in a run with level-3 samples")
                if (
                    destination.suffix != ".md"
                    or destination.with_suffix(".json").exists()
                    or destination.exists()
                ):
                    raise ValueError("Choose an unused .md output path for the separate reference audit")
                run["derived_from"] = {
                    "manifest": args.manifest.name,
                    "sha256": hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
                }
                run["reference_designation"] = {
                    "endpoint": args.reference,
                    "designated_at": now(),
                    "kind": "post-collection user designation",
                }
                run["collection_level"] = run["level"]
                run["level"] = 4
            run["analysis"] = analyze(run)
            if args.reference:
                atomic_json(destination.with_suffix(".json"), run)
        else:
            config = load_config(args.config)
            probes, suite_hash = load_probes(config, args.config)
            if args.dry_run:
                print(json.dumps(estimate(plan(config, probes, args.level)), indent=2))
                return 0
            run = benchmark(config, probes, suite_hash, args.level, args.output, args.resume, args.store_text)
            destination = args.output / "report.md"
        destination.write_text(render(run), encoding="utf-8")
        print(f"Report: {destination}")
        print(f"Requests: {run['request_counts']}; remaining: {run['remaining_requests']}")
        return int(
            args.command == "benchmark"
            and (run["remaining_requests"] > 0 or any(r["status"] != "ok" for r in run["requests"]))
        )
    except ValidationError as exc:
        # Pydantic's default exception text includes input values, potentially credentials.
        fields = [".".join(map(str, e["loc"])) for e in exc.errors(include_input=False)]
        print("Invalid configuration fields: " + ", ".join(fields), file=sys.stderr)
        return 2
    except (OSError, yaml.YAMLError, json.JSONDecodeError):
        print("Could not read/write configuration or report; check paths and file syntax.", file=sys.stderr)
        return 2
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted. Manifest saved; rerun the same command with --resume.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
