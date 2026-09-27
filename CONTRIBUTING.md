# Contributing

Keep the first run simple and the scientific claims narrow. A behavioral benchmark is useful only when a reader can inspect its assumptions and reproduce its analysis.

1. Install Python 3.11+ and run `python -m pip install -e '.[dev]'` (or `uv sync --extra dev`).
2. Run `python -m pytest -q` and `ruff check .` before submitting changes.
3. Explain the observable change and include relevant offline evidence. Never add real credentials, private prompts or paid API results to a contribution.

Adapters normalize observations; they must not silently change controls, retry billed calls, omit failed providers or retain credentials. Extend the `Adapter` protocol for other transports. Keep probe selection, collection, statistics and presentation independently testable.

Statistical changes need a written null hypothesis, estimator, resampling procedure, correction family and limitations, plus synthetic null/alternative regression tests. Do not transfer paper accuracy or power claims to a new implementation. Document departures from cited procedures. Preserve the distinction between no detected difference and equivalence.

Version changes to probes and statistical interpretation; preserve enough evidence to reproduce old reports. Separate calibration and final evaluation sets. Protocol/config changes must reject resume rather than mix experiments.

Useful next contributions include calibrated same-configuration controls, additional adapters, richer string kernels, explicit capability discovery, multi-message probes and independently tested rank-based audits. Discuss scientific scope before adding an identity verdict.
