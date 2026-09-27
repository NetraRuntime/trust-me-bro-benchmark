# Documentation

Start with the [README quick start](../README.md#quick-start), then choose the question you want to answer.

| Task | Guide |
|---|---|
| Compare a provider with normal repeat variability | [Practical consistency](consistency.md) |
| Understand a verdict, interval or failure | [Interpreting reports](interpreting-results.md) |
| Collect reproducible task answers | [Frozen MMLU-Pro protocol](dataset-protocol.md) |
| Configure routes, controls, budgets and credentials | [Configuration](configuration.md) |
| Use the benchmark from an assistant | [MCP server](mcp.md) |
| Choose a broader probe source | [Dataset guide](datasets.md) |
| Understand the original levels 0–4 | [Smoke-test methodology](methodology.md) |
| Understand spoofing and attribution limits | [Threat model](threat-model.md) |
| Decide what to retain and share | [Privacy](privacy.md) |
| Extend or test the implementation | [Architecture](architecture.md) and [contributing](../CONTRIBUTING.md) |

**Recommended sequence:** run the synthetic demo, inspect its JSON/report, select independent pilot and evaluation questions, justify a tolerance, configure a repeat baseline and different-model control, inspect the budget, then collect a frozen evaluation. Preserve inconclusive results and failed requests. The tool does not choose a threshold that makes a provider pass.

Published results should state the dataset revision and selection, protocol version, endpoint controls, baseline/reference provenance, planned and valid samples, failure counts, effect and uncertainty, comparison correction, and known limitations. Include both the distribution test and the practical-tolerance result when enabled. Do not publish private prompts, secrets or unreviewed raw responses.
