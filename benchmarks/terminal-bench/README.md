# Terminal-Bench CPU provider comparison

Status: **preparation only; no Terminal-Bench trials have run**. The user selected
a CPU-only subset within the existing $30 ceiling. This directory contains a
candidate manifest, resource inventory, route prices and a draft protocol.
It is not a benchmark result or a completed preregistration.

Use a **headless Linux runner** with a supported container backend. Docker
Desktop is not part of this setup. No remote host, sandbox service or GPU
capacity has been provisioned. A pinned runtime, durable request-level spend
guard, loopback proxy and single-pilot adapter are now implemented. See the
[runtime instructions](runtime/README.md) and [latest catalog snapshot](readiness.json).
The fake-API checks are not evidence of container or paid-provider operation.
Linux resource screening, live-route pilots and final preregistration still
block main collection. The snapshot must be refreshed before any pilot.

## Study scope

- Terminal-Bench **4.0.0**, commit
  `452bf305c6daa62fc59061d22133a7cbc7c1572e`.
- Twelve deterministically selected tasks from the 63 tasks whose published
  agent and verifier environments request no GPUs. Three GPU tasks are excluded
  explicitly; CPU eligibility does not establish local resource compatibility.
- Three independent attempts per task, per endpoint: **468 agent episodes**.
- DeepSeek V4.1 Flash: seven providers. DeepSeek V4 Flash 0731: six providers.
  Exact proposed routes are in [routes.json](routes.json). Catalog availability
  is not proof that a paid request will follow that route.
- One fixed **Terminus-2** agent through Harbor. The inspected source revision is
  in [source-inspection.json](source-inspection.json); the corresponding runtime
  and transitive dependencies are pinned in [runtime/uv.lock](runtime/uv.lock).
- Official task instructions and verifier scoring remain unchanged. A subset
  and explicit agent budget make this a **budget-limited Terminal-Bench CPU
  subset**, not an official full-suite leaderboard score.

The candidate sample uses SHA-256 ordering of `20260928:<task-name>`. It is not
selected using provider scores or known task success rates. The next two eligible
tasks in that order are reserved for setup pilots if this candidate manifest is
frozen. Pilot results do not enter the main comparison. Resource/build screening
must precede the final manifest; any exclusions and their reasons must be public.
Do not swap out tasks after seeing provider performance.

## Cost and limits

The proposed equal episode ceilings are **150,000 cumulative input tokens** and
**20,000 cumulative output tokens**, including reasoning and billed retries.
Input means the sum over every API call, including repeatedly transmitted
history; it is not the context-window limit. Per-call output ceiling: 8,192
tokens or the remaining episode allowance, whichever is lower. The pilot adapter
now enforces these proposed limits through durable request reservations; their
effect on the agent still needs validation in the disjoint pilot.

At the **2026-09-28** recorded route prices, all 468 episodes reaching both cumulative ceilings
would total **$20.530152** in token charges. Reserve up to **$2** for setup pilots
and **$7.469848** for earlier campaign spend, unknown failed-call billing, fees
and contingency. This allocation stays within $30 only if an execution-time
spend guard verifies current prices and conservatively reserves every request.
These are historical planning prices, not current execution quotes. Current
catalog changes and unavailable routes are recorded separately in
[readiness.json](readiness.json), without silently changing the proposed roster.
No cache discount is assumed.

No paid sandbox is included. If the Linux runner incurs fees, include them in the
same $30 envelope before execution; do not provision it on an assumed free basis.
Pilot caps and episode limits must be enforced outside the agent, including
summarization calls and nested retries. Unknown usage keeps its reservation.
If a complete study no longer fits, stop before main collection and revise the
design; do not silently fund extra calls or publish a partial sample as complete.

Unrestricted episode costs are highly uncertain. The offline planner gives
scenarios, not empirical predictions:

| Total tokens per episode, input / output | 12-task subset API scenario |
|---|---:|
| 100,000 / 20,000 | $15.75 |
| 1,000,000 / 100,000 | $126.54 |
| 5,000,000 / 500,000 | $632.69 |

The $30 constraint is why the bounded profile matters. Exhaustion rates must be
reported; a high rate means this evaluates performance under a tight budget,
not unconstrained model capability. The full-suite plan is retained only as a
cost comparison and is not selected or authorized for execution.

## Draft analysis and execution protocol

The primary outcome is the official binary task reward for each agent episode.
For each provider, average repeats within each task, then weight the 12 tasks
equally. Compare all provider pairs within each model (21 + 15 = **36 pairs**).
Report success rates, paired percentage-point differences, task-level results,
and descriptive intervals obtained by resampling whole tasks with all repeats
and providers kept together. With only 12 tasks, interval coverage and precision
are limited; repeated attempts are not 36 independent tasks.

Use a paired task-block permutation test, swapping the entire three-attempt
vectors between a provider pair within each task, and enumerate all 4,096 swaps.
The statistic is the absolute equal-task-weighted success-rate difference.
This tests provider-label exchangeability within the sampled task blocks; it is
not an assumption-free test of equal overall means. Apply Holm correction across
the 36 planned pairs. Report adjusted p-values with effects, without ranking
providers solely by significance. These are exploratory subset comparisons;
there is no equivalence claim or promise of sensitivity to small differences.

Randomize provider execution order within task/attempt blocks using a recorded
seed, interleave providers over time, and hold sandbox resources, network policy,
agent prompts, parser, reasoning settings, context handling and limits constant.
Freeze those settings after the disjoint pilot, before main collection. Match
requested reasoning controls across endpoints and verify they reach each route;
do not carry over the MMLU reasoning-disabled setting without agent validation.

Use explicit OpenRouter `provider.only` routing with fallbacks disabled, and
validate returned route metadata throughout the run. Direct Netra remains a
separate endpoint. Avoid sharing response caches across episodes. The same
request settings do not establish identical model weights or serving software.

Run the official verifier after the agent stops, including budget/time exhaustion
where a usable artifact remains. Its reward determines success. Service failure,
refusal or agent failure that prevents completing a valid episode counts as an
unsuccessful delivered task, with its failure reason also reported. One failed
episode does not invalidate all provider pairs.

Infrastructure/evaluator failure, wrong routing, invalid credentials and account
exhaustion are not model failures. Keep them as missing/invalid observations with
reasons. Fix the cause before continuing. Any rerun policy must be frozen before
collection and preserve original attempts; do not retry only low-scoring providers.
Report planned coverage, complete-block exploratory estimates and worst-case
missing-outcome bounds. Do not claim a completed main comparison if missingness
prevents it. Budget exhaustion across the campaign is an interrupted study.

Harbor trial retries and internal LLM retries are distinct. At the inspected
revision, both the LiteLLM call wrapper and Terminus-2 query wrapper can retry up
to three attempts, in addition to any SDK behavior. A zero Harbor job-retry count
does not disable these. The final request accounting must observe actual calls,
bound retry spending and retain every error and attempt. Test these controls with
a local fake API before using paid endpoints.

Retain task/config/image hashes, raw model outputs, official rewards, API attempt
records, token/cost reservations, errors and ATIF trajectories locally. Keep
credentials outside task containers and redact secrets before publishing reviewed
evidence. Preserve benchmark canaries and licensing; do not publish task solutions
as training data. Final reports distinguish measured cost from estimated charges.

## Reproduce the offline plan

From the repository root (Python 3.11+):

```sh
uv run python -m tmb.terminal_plan \
  --inventory benchmarks/terminal-bench/inventory.json \
  --routes benchmarks/terminal-bench/routes.json \
  --tasks 12 --repeats 3
```

This performs no network requests and launches no jobs. Its output matches
[cpu-12.plan.json](cpu-12.plan.json). Resource metadata was fetched at the pinned
Git commit and each original task configuration matched its Git blob hash.
The inventory contains metadata, not task instructions or solutions.

## Upstream references

- [Terminal-Bench run guide](https://www.tbench.ai/run)
- [Terminal-Bench 4.0 release](https://github.com/harbor-framework/terminal-bench/releases/tag/v4.0.0)
- [Harbor agents](https://docs.harborframework.com/core-concepts/agents/pre-integrated-agents)
- [Harbor job configuration](https://docs.harborframework.com/core-concepts/jobs/configs)

No official leaderboard submission is implied. Existing MMLU-Pro reports and
their frozen protocol are unchanged.
