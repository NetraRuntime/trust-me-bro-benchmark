# Contributing

Keep the first run simple and the scientific claims narrow. A behavioral benchmark is useful only when a reader can inspect its assumptions and reproduce its analysis.

1. Install Python 3.11+ and run `python -m pip install -e '.[dev,mcp]'` (or `uv sync --extra dev --extra mcp`).
2. Run `python -m pytest -q` and `ruff check .` before submitting changes.
3. Explain the observable change and include relevant offline evidence. Never add real credentials, private prompts or paid API results to a contribution.

Adapters normalize observations; they must not silently change controls, retry billed calls, omit failed providers or retain credentials. Extend the `Adapter` protocol for other transports. Keep probe selection, collection, statistics and presentation independently testable.

Statistical changes need a written null hypothesis, estimator, resampling procedure, correction family and limitations, plus synthetic null/alternative regression tests. Do not transfer paper accuracy or power claims to a new implementation. Document departures from cited procedures. Preserve the distinction between no detected difference and equivalence.

Version changes to probes and statistical interpretation; preserve enough evidence to reproduce old reports. Separate calibration and final evaluation sets. Protocol/config changes must reject resume rather than mix experiments.

Useful next contributions include independent live calibration studies, richer dataset/task adapters, additional protocols, explicit capability discovery and independently tested rank-based audits. The baseline bootstrap is descriptive only because rare-question cases expose undercoverage. A new tolerance test needs justified coverage and operating-characteristic studies near both boundaries, including dependence and missingness. See [architecture](docs/architecture.md) and the [descriptive baseline method](docs/consistency.md).
