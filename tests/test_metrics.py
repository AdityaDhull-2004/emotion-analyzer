"""Metrics (spec §10.1, §10.2 R0, §10.4b)."""

import numpy as np
import pytest

from emotion_analyzer import config, metrics

MELD_TEST_COUNTS = {"anger": 345, "disgust": 68, "fear": 50, "joy": 402, "neutral": 1256,
                    "sadness": 208, "surprise": 281}


def test_majority_baseline_matches_spec_r0():
    y_true = np.concatenate([[config.LABEL_TO_ID[l]] * n for l, n in MELD_TEST_COUNTS.items()])
    y_pred = np.full_like(y_true, config.LABEL_TO_ID["neutral"])
    s = metrics.summary(y_true, y_pred)
    assert s["accuracy"] == pytest.approx(48.1, abs=0.05)
    assert s["weighted_f1"] == pytest.approx(31.3, abs=0.05)


def test_basic_scores_and_reports():
    y_true = np.array([0, 0, 1, 1, 2, 2])
    y_pred = np.array([0, 1, 1, 1, 2, 0])
    assert metrics.accuracy(y_true, y_pred) == pytest.approx(100 * 4 / 6)
    report = metrics.per_class(y_true, y_pred)
    assert list(report) == config.LABELS
    assert report["joy"]["support"] == 0
    cm = metrics.confusion(y_true, y_pred)
    assert cm.shape == (7, 7) and cm.sum() == 6 and cm[0, 1] == 1


def test_bootstrap_ci_is_deterministic_and_brackets_point():
    rng = np.random.default_rng(1)
    y_true = rng.integers(0, 7, 400)
    y_pred = np.where(rng.random(400) < 0.6, y_true, rng.integers(0, 7, 400))
    lo, hi = metrics.bootstrap_ci(y_true, y_pred, n=200)
    assert (lo, hi) == metrics.bootstrap_ci(y_true, y_pred, n=200)
    assert lo <= metrics.weighted_f1(y_true, y_pred) <= hi


def test_mean_sd():
    assert metrics.mean_sd([40.0, 42.0, 44.0]) == pytest.approx((42.0, 2.0))


def test_ece():
    rng = np.random.default_rng(0)
    n = 20000
    conf = rng.uniform(0.2, 1.0, n)
    y_pred = rng.integers(0, 7, n)
    correct = rng.random(n) < conf
    y_true = np.where(correct, y_pred, (y_pred + 1) % 7)
    probs = np.full((n, 7), 0.0)
    probs[np.arange(n), y_pred] = conf
    probs[np.arange(n), (y_pred + 1) % 7] += (1 - conf)
    assert metrics.ece(probs, y_true) < 1.5          # calibrated by construction
    sharp = probs ** 4 / (probs ** 4).sum(1, keepdims=True)
    assert metrics.ece(sharp, y_true) > 5.0          # overconfident
    bins = metrics.reliability(probs, y_true)
    assert len(bins) == config.ECE_BINS and sum(b["count"] for b in bins) == n


@pytest.mark.slow
def test_wer_uses_whisper_normaliser():
    out = metrics.wer(["Hello, Mr. Smith! It's 10 o'clock."], ["hello mister smith it is ten o'clock"])
    assert out["wer"] < 30
    assert metrics.wer(["a b c d"], ["a b x d e"])["wer"] == pytest.approx(50.0)


def test_run_summary_and_final_block(tmp_path):
    """S8's metrics.json rows (seed means of R1-R6, R0) and the final results block."""
    from emotion_analyzer import evaluate
    from emotion_analyzer.sound_model import save_predictions

    rng = np.random.default_rng(0)
    ids = {sp: np.array([f"{sp}_dia{i}_utt0" for i in range(80)]) for sp in ("dev", "test")}
    labels = {sp: rng.integers(0, 7, 80) for sp in ("dev", "test")}

    def probs(y, acc):
        pred = np.where(rng.random(len(y)) < acc, y, rng.integers(0, 7, len(y)))
        p = np.full((len(y), 7), 0.05)
        p[np.arange(len(y)), pred] = 0.7
        return p

    for seed in (0, 1):
        for sp in ("dev", "test"):
            d = tmp_path / "runs" / "sound" / f"main_seed{seed}"
            d.mkdir(parents=True, exist_ok=True)
            save_predictions(d / f"pred_{sp}.npz", ids[sp], labels[sp], probs(labels[sp], 0.4))
            d = tmp_path / "runs" / "text" / f"main_seed{seed}"
            d.mkdir(parents=True, exist_ok=True)
            for kind, acc in (("real", 0.7), ("whisper", 0.6)):
                save_predictions(d / f"pred_{sp}_{kind}.npz", ids[sp], labels[sp], probs(labels[sp], acc))
    s = evaluate.summarize_runs(tmp_path / "runs")
    rows = s["rows"]
    assert rows["R1/test"]["n_seeds"] == 2 and rows["R4/test"]["weighted_f1_mean"] > rows["R1/test"]["weighted_f1_mean"]
    assert "R2/test" not in rows and "R0/test" in rows
    pf = evaluate.provisional_fusion(tmp_path / "runs")
    assert len(pf["per_seed"]) == 2
    block = evaluate.final_block({"decision": {"window_s": 10, "case": "a"}, "runs": s,
                                  "provisional_fusion": pf, "wer": {}, "skipped": ["S6_A_seed0"]})
    assert "R1 sound main" in block and "R7 fused Whisper" in block and "skipped" in block
