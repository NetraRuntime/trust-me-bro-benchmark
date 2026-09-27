import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "reports/2026-09-28-deepseek/analyze.py"
spec = importlib.util.spec_from_file_location("campaign_report", SCRIPT)
campaign = importlib.util.module_from_spec(spec)
spec.loader.exec_module(campaign)


def test_campaign_uses_full_prespecified_family_not_only_testable_pairs():
    family = [{"valid_for_campaign": True, "p_value": 0.001}]
    family += [{"valid_for_campaign": False} for _ in range(97)]
    campaign.correct_family(family, 0.05)
    # It would pass a 28-pair correction, but must not pass this 98-test family.
    assert family[0]["campaign_adjusted_p_value"] == pytest.approx(0.098)
    assert family[0]["campaign_verdict"] == "no difference detected"
    assert all(p["campaign_verdict"] == "inconclusive" for p in family[1:])
    with pytest.raises(ValueError, match="98 planned"):
        campaign.correct_family(family[:-1], 0.05)


def test_report_does_not_certify_conflicting_provider_metadata():
    run = {
        "config": {"endpoints": [{"name": "deepinfra", "model": "expected", "provider": "deepinfra/fp8"}]},
        "requests": [
            {
                "endpoint": "deepinfra",
                "http_status": 200,
                "returned_model": "expected",
                "provider": "Different",
            }
        ],
    }
    assert "deepinfra" in campaign.provenance_issues(run)
    run["requests"][0]["provider"] = "DeepInfra"
    assert not campaign.provenance_issues(run)
