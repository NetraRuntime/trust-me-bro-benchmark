"""Exact-string delta-kernel MMD, stratified permutation, Holm correction."""

import math
from collections import Counter

import numpy as np


def jsd(a, b):
    a, b = Counter(a), Counter(b)
    na, nb = sum(a.values()), sum(b.values())
    if not na or not nb:
        return None
    result = 0.0
    # Stable category order prevents process hash randomization changing final float bits.
    for key in sorted(a.keys() | b.keys()):
        p, q = a[key] / na, b[key] / nb
        mid = (p + q) / 2
        result += (p * math.log2(p / mid) if p else 0) / 2
        result += (q * math.log2(q / mid) if q else 0) / 2
    return result


def mmd2(a, b):
    """Unbiased U statistic; negative estimates are legitimate."""
    ca, cb = Counter(a), Counter(b)
    n, m = len(a), len(b)
    return (
        sum(v * (v - 1) for v in ca.values()) / (n * (n - 1))
        + sum(v * (v - 1) for v in cb.values()) / (m * (m - 1))
        - 2 * sum(v * cb[k] for k, v in ca.items()) / (n * m)
    )


def holm(pvalues):
    """Family-wise error control, including untestable comparisons as p=1."""
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    result, previous = [1.0] * len(pvalues), 0.0
    for rank, i in enumerate(order):
        previous = min(1.0, max(previous, (len(order) - rank) * pvalues[i]))
        result[i] = previous
    return result


def permutation_test(groups, permutations=999, bootstrap=300, seed=2026):
    """Equal-weight prompt strata; labels permute only inside each prompt."""
    rng = np.random.default_rng(seed)
    groups = [(list(a), list(b)) for a, b in groups]
    observed = float(np.mean([mmd2(a, b) for a, b in groups]))
    exceed = 0
    for _ in range(permutations):
        stats = []
        for a, b in groups:
            shuffled = rng.permutation(a + b).tolist()
            stats.append(mmd2(shuffled[: len(a)], shuffled[len(a) :]))
        exceed += float(np.mean(stats)) >= observed - 1e-12
    boot = []
    for _ in range(bootstrap):
        boot.append(
            float(
                np.mean(
                    [mmd2(rng.choice(a, len(a)).tolist(), rng.choice(b, len(b)).tolist()) for a, b in groups]
                )
            )
        )
    return {
        "statistic": observed,
        "effect_size": observed,
        "effect_name": "mean unbiased exact-string MMD squared",
        "p_value": (exceed + 1) / (permutations + 1),
        "uncertainty": {
            "bootstrap_percentile_95": np.quantile(boot, [0.025, 0.975]).tolist(),
            "warning": "Descriptive only; bootstrap coverage is unreliable near the null.",
            "permutation_resolution": 1 / (permutations + 1),
        },
        "method": "prompt-stratified exact-string MMD permutation test",
        "null_hypothesis": "Equal response distributions for every tested prompt under requested settings",
    }
