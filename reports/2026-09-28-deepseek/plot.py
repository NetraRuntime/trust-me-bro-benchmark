"""Optional figures: uv run --no-project --with matplotlib==3.10.3 python PATH/plot.py."""

import gzip
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parent
LABELS = {
    "dekallm": "DekaLLM",
    "deepinfra": "DeepInfra",
    "deepinfra_repeat": "DeepInfra repeat",
    "novita": "Novita",
    "fireworks": "Fireworks",
    "together": "Together",
    "parasail": "Parasail",
    "netra": "Netra",
    "coreweave": "CoreWeave",
    "nebius": "Nebius",
}


def main():
    with gzip.open(ROOT / "campaign-analysis.json.gz", "rt", encoding="utf8") as f:
        analysis = json.load(f)
    bound = max(
        0.05,
        max(
            abs(p.get("effect_size", 0))
            for s in analysis["studies"].values()
            for p in s["api_outcomes"]["pairs"]
        ),
    )
    (ROOT / "figures").mkdir(exist_ok=True)
    for slug, study in analysis["studies"].items():
        with gzip.open(ROOT / "evidence" / f"{slug}.json.gz", "rt", encoding="utf8") as f:
            run = json.load(f)
        names = [e["name"] for e in run["config"]["endpoints"]]
        labels = [LABELS[n] for n in names]
        n = len(names)
        effects = np.full((n, n), np.nan)
        stars = np.full((n, n), False)
        for pair in study["api_outcomes"]["pairs"]:
            i, j = names.index(pair["left"]), names.index(pair["right"])
            if pair["valid_for_campaign"]:
                effects[i, j] = effects[j, i] = pair["effect_size"]
                stars[i, j] = stars[j, i] = pair["campaign_verdict"] == "detectably different"
        fig, (ax, bx) = plt.subplots(1, 2, figsize=(15, 7.5), gridspec_kw={"width_ratios": [1, 1.6]})
        fig.patch.set_facecolor("white")
        fig.suptitle(run["config"]["claimed_model"], fontsize=19, weight="bold", y=0.99)
        valid = np.asarray([study["answers"]["scores"][name]["coverage"] * 100 for name in names])
        yy = np.arange(n)
        ax.barh(yy, valid, color="#187a8a", label="Valid choice")
        ax.barh(yy, 100 - valid, left=valid, color="#db8654", label="Invalid / failed")
        ax.set(yticks=yy, yticklabels=labels, xlim=(0, 100), xlabel="Share of planned responses (%)")
        ax.invert_yaxis()
        ax.set_title("Answer coverage", fontsize=13, pad=18)
        for i, v in enumerate(valid):
            ax.text(2, i, f"{v:.1f}%", va="center", color="white", fontsize=10)
        ax.spines[["top", "right"]].set_visible(False)
        ax.legend(loc="lower left", bbox_to_anchor=(0, -0.2), frameon=False, fontsize=10)
        cmap = plt.get_cmap("RdBu_r").copy()
        cmap.set_bad("#edf0f2")
        im = bx.imshow(effects, cmap=cmap, vmin=-bound, vmax=bound)
        bx.set(xticks=yy, yticks=yy, xticklabels=labels, yticklabels=labels)
        plt.setp(bx.get_xticklabels(), rotation=45, ha="right", rotation_mode="anchor", fontsize=9)
        plt.setp(bx.get_yticklabels(), fontsize=9)
        bx.set_title("API-outcome differences (MMD²)", fontsize=13, pad=18)
        for i in range(n):
            for j in range(n):
                text = (
                    "—" if np.isnan(effects[i, j]) else f"{effects[i, j]:.3f}" + ("*" if stars[i, j] else "")
                )
                color = (
                    "white" if not np.isnan(effects[i, j]) and abs(effects[i, j]) > 0.6 * bound else "#18212a"
                )
                bx.text(j, i, text, ha="center", va="center", fontsize=8, color=color)
        fig.colorbar(im, ax=bx, shrink=0.65, pad=0.025, label="Unbiased effect estimate")
        fig.text(
            0.02,
            0.015,
            "* Holm-significant across all 98 planned tests. API outcomes include failures; this is not an answer-only or model-identity test.",
            fontsize=10,
        )
        fig.tight_layout(rect=[0, 0.075, 1, 0.96])
        fig.savefig(ROOT / "figures" / f"{slug}.png", dpi=160, facecolor="white")
        plt.close(fig)


if __name__ == "__main__":
    main()
