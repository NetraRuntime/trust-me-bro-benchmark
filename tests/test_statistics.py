import numpy as np
import pytest

from tmb.statistics import holm, jsd, mmd2, permutation_test


def test_jsd_and_unbiased_estimator():
    assert jsd(["a"] * 5, ["a"] * 8) == 0
    assert jsd(["a"] * 5, ["b"] * 8) == 1
    assert jsd([], ["a"]) is None
    assert mmd2(["a"] * 5, ["b"] * 5) == 2
    assert mmd2(["a", "b"], ["a", "b"]) < 0


def test_holm_known_values():
    assert holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm([0.01, 1, 0.03]) == pytest.approx([0.03, 1, 0.06])


def test_jsd_reproducible_across_hash_seeds():
    import os
    import subprocess
    import sys

    script = "from tmb.statistics import jsd; print(repr(jsd(['a','a','b','c'], ['c','d','d','d'])))"
    outputs = [
        subprocess.check_output(
            [sys.executable, "-c", script], env=os.environ | {"PYTHONHASHSEED": str(seed)}
        )
        for seed in (1, 2, 42, 987)
    ]
    assert len(set(outputs)) == 1


def test_extreme_same_and_different():
    same = permutation_test([(["a"] * 20, ["a"] * 20)], 199, 100)
    different = permutation_test([(["a"] * 20, ["b"] * 20)], 199, 100)
    assert same["p_value"] == 1
    assert different["p_value"] == 0.005
    assert different["effect_size"] == 2
    assert different == permutation_test([(["a"] * 20, ["b"] * 20)], 199, 100)


def test_prompt_stratification():
    assert permutation_test([(["a"] * 10, ["a"] * 10), (["b"] * 10, ["b"] * 10)], 199, 100)["p_value"] == 1


def test_fixed_synthetic_null_and_alternative_controls():
    # Predeclared distributions/seeds, broad finite-Monte-Carlo guard; not real-provider calibration.
    rng = np.random.default_rng(9173)
    false_positives = detections = 0
    for seed in range(40):
        a = rng.choice(["a", "b"], 40).tolist()
        b = rng.choice(["a", "b"], 40).tolist()
        c = rng.choice(["a", "b"], 40, p=[0.98, 0.02]).tolist()
        false_positives += permutation_test([(a, b)], 199, 100, seed)["p_value"] <= 0.05
        detections += permutation_test([(a, c)], 199, 100, seed)["p_value"] <= 0.05
    assert false_positives <= 6
    assert detections >= 30
