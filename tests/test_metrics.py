"""Metrics (spec §10.1, §10.2 R0, §10.4b)."""

import re

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


def _pred_files(tmp_path, rng, n=120):
    """Kaggle-style prediction files (S8 names) for three text seeds and one sound seed."""
    from emotion_analyzer import evaluate
    from emotion_analyzer.sound_model import save_predictions

    ids = np.array([f"dev_dia{i}_utt0" for i in range(n)])
    y = rng.integers(0, 7, n)

    def probs(acc):
        pred = np.where(rng.random(n) < acc, y, rng.integers(0, 7, n))
        p = np.full((n, 7), 0.05)
        p[np.arange(n), pred] = 0.7
        return p / p.sum(1, keepdims=True)

    for s in (0, 1, 2):
        save_predictions(evaluate.kaggle_pred("text", "main", s, "dev", "whisper", tmp_path), ids, y, probs(0.55))
    save_predictions(evaluate.kaggle_pred("sound", "main", 1, "dev", None, tmp_path), ids, y, probs(0.5))
    return ids, y


def test_text_ensemble_rule(tmp_path):
    """§8.3: the ensemble is chosen only if it adds at least ENSEMBLE_MIN_GAIN points."""
    from emotion_analyzer import evaluate

    _pred_files(tmp_path, np.random.default_rng(0))
    r = evaluate.text_ensemble_rule(tmp_path)
    assert set(r["single"]) == {0, 1, 2} and r["best_seed"] in (0, 1, 2)
    assert r["gain"] == pytest.approx(r["ensemble"] - r["single"][r["best_seed"]], abs=0.02)
    assert r["passes_f1"] == (r["gain"] >= config.ENSEMBLE_MIN_GAIN)
    assert evaluate.text_ensemble_rule(tmp_path, min_gain=-100)["passes_f1"] is True
    assert evaluate.text_ensemble_rule(tmp_path, min_gain=100)["passes_f1"] is False


def test_parity_report(tmp_path):
    """§10.5: same probabilities on both paths give zero gaps; a degraded CPU text branch
    is caught by the 1.5-point rule."""
    import pandas as pd

    from emotion_analyzer import evaluate, fusion

    ids, y = _pred_files(tmp_path, np.random.default_rng(1))
    sound_f = [evaluate.kaggle_pred("sound", "main", 1, "dev", None, tmp_path)]
    text_f = [evaluate.kaggle_pred("text", "main", 0, "dev", "whisper", tmp_path)]
    _, _, ps = fusion.load_predictions(*sound_f)
    _, _, pt = fusion.load_predictions(*text_f)
    rows = pd.DataFrame({"id": ids, "label_id": y, "transcript": [str(i) for i in range(len(ids))],
                         **{c: ps[:, k] for k, c in enumerate(evaluate.PROB_COLS)}})
    params = {"t_sound": 1.0, "t_text": 1.0, "w_sound": 0.5}

    class Same:  # returns Kaggle's text probabilities for the transcript index
        def predict_proba(self, texts):
            return pt[[int(t) for t in texts]]

    class Uniformish:
        def predict_proba(self, texts):
            return np.tile(np.linspace(1, 2, 7) / np.linspace(1, 2, 7).sum(), (len(texts), 1))

    p = evaluate.parity(rows, Same(), params, sound_f, text_f)
    assert p["pass"] and all(r["gap"] == 0 for r in p["rows"].values())
    assert p["label_agreement"] == {"sound": 100.0, "text": 100.0}
    bad = evaluate.parity(rows, Uniformish(), params, sound_f, text_f)
    assert not bad["rows"]["text"]["pass"] and not bad["pass"]
    sub = evaluate.parity(rows.head(30), Same(), params, sound_f, text_f)  # a smoke-run subset
    assert sub["n"] == 30
    assert "AC-07: pass" in evaluate.parity_markdown(p, 30)
    assert "AC-07: FAIL" in evaluate.parity_markdown(bad, 30)


def test_latency_report_verdicts():
    """§10.4: AC-08 on the median end-to-end time, AC-09 on peak memory."""
    from emotion_analyzer import latency

    runs = [{"decode": 100, "encode": 900, "transcribe": 300, "sound": 3, "text": 20, "fusion": 1,
             "total": 1330 + 10 * i} for i in range(20)]
    st = latency.summarize(runs)
    assert st["total"]["median"] == pytest.approx(1425.0) and st["encode"]["p90"] == 900
    report = {"stages_ms": st, "peak_memory_gb": 1.9, "mains_power": True, "clip": "x.wav",
              "clip_s": 4.97, "warmup": 2, "runs": 20, "date": "2026-10-20", "load_s": 5.0,
              "models": {"asr": "faster-whisper small.en int8", "window_s": 30, "sound": "attnpool-v1",
                         "text": "roberta-base-meld-v1", "fusion_w_sound": 0.75, "text_precision": "fp32"}}
    md = latency.markdown(report)
    assert "**AC-08**" in md and "1.43 s, **pass**" in md and "stretch target is not met" in md
    assert "1.90 GB, **pass**" in md
    report["peak_memory_gb"] = 2.6
    assert "2.60 GB, **FAIL**" in latency.markdown(report)


def test_weighted_f1_counts_matches_sklearn():
    rng = np.random.default_rng(3)
    for _ in range(5):
        y, p = rng.integers(0, 7, 300), rng.integers(0, 5, 300)
        assert metrics.weighted_f1_counts(y, p) == pytest.approx(metrics.weighted_f1(y, p))
    lo, hi = metrics.bootstrap_ci_seeds(y, [p, p], n=100)
    assert (lo, hi) == pytest.approx(metrics.bootstrap_ci(y, p, n=100))


def _kaggle_outputs(tmp_path, monkeypatch, n=150):
    """Every exported prediction file of a small fake Kaggle run, plus sound_head.json."""
    import json

    from emotion_analyzer import evaluate
    from emotion_analyzer.sound_model import save_predictions

    rng = np.random.default_rng(0)
    head = tmp_path / "models" / "sound_head.pt"
    head.parent.mkdir()
    head.with_suffix(".json").write_text(json.dumps({"seed": 1, "run": "main"}))
    monkeypatch.setattr(config, "SOUND_HEAD_PATH", head)
    pred = tmp_path / "predictions"
    pred.mkdir()
    for split in ("dev", "test"):
        ids = np.array([f"{split}_dia{i}_utt0" for i in range(n)])
        y = rng.integers(0, 7, n)

        def probs(acc):
            pick = np.where(rng.random(n) < acc, y, rng.integers(0, 7, n))
            p = rng.dirichlet(np.ones(7), n) * 0.5
            p[np.arange(n), pick] += 0.5
            return p

        for s in config.SEEDS:
            for run, acc in (("main", 0.5), ("A", 0.45), ("W", 0.45)):
                save_predictions(evaluate.kaggle_pred("sound", run, s, split, None, pred), ids, y, probs(acc))
            for run in ("main", "T"):
                for kind, acc in (("real", 0.7), ("whisper", 0.55)):
                    save_predictions(evaluate.kaggle_pred("text", run, s, split, kind, pred), ids, y, probs(acc))
    return pred


def test_results_rows_and_report_parts(tmp_path, monkeypatch):
    """§10.2 rows R0-R9 with seed means and intervals; §10.1/§10.4b/§10.8 report parts."""
    from emotion_analyzer import evaluate, fusion

    pred = _kaggle_outputs(tmp_path, monkeypatch)
    params = {"t_sound": 0.9, "t_text": 0.8, "w_sound": 0.5}
    t_int8 = fusion.load_predictions(evaluate.kaggle_pred("text", "main", 0, "test", "whisper", pred))
    rows = evaluate.results_rows(params, t_int8, pred_dir=pred)
    by = {r["row"]: r for r in rows}
    assert list(by) == list(evaluate.ROW_NAMES)
    assert by["R0"]["n_seeds"] == 1 and by["R9"]["n_seeds"] == 1 and by["R1"]["n_seeds"] == 3
    for r in rows:
        assert r["ci_low"] <= r["weighted_f1_mean"] + 1e-6 or r["n_seeds"] > 1
        assert r["ci_low"] < r["ci_high"]
    assert by["R4"]["weighted_f1_mean"] > by["R5"]["weighted_f1_mean"] > by["R0"]["weighted_f1_mean"]
    assert "dev_weighted_f1_mean" in by["R7"] and "dev_weighted_f1_mean" not in by["R9"]
    md = evaluate.results_table_markdown(rows, params)
    assert len(re.findall(r"\n\| R\d \|", md)) == 10

    parts = evaluate.deployed_test_parts(params, t_int8, pred_dir=pred)
    assert evaluate.per_class_report(parts, tmp_path).count("| anger |") == 3
    assert {p.name for p in tmp_path.glob("confusion_*.png")} == {
        "confusion_sound.png", "confusion_text.png", "confusion_fused.png"}
    cal_md, cal = evaluate.calibration_report(parts, params, tmp_path)
    assert (tmp_path / "reliability.png").exists() and "AC-16" in cal_md and cal["ece_before"] >= 0
    import pandas as pd
    tr = pd.DataFrame({"id": parts["ids"], "hypothesis": "words", "reference": "Words!"})
    tr.to_csv(tmp_path / "test_30s.csv", index=False)
    err_md, err = evaluate.error_analysis(parts, tmp_path / "test_30s.csv")
    assert err["flagged"] > 0 and err_md.count("“words”") == min(10, err["flagged"])
    assert err_md.count("\n| ") >= 7


def test_own_recordings_report():
    import pandas as pd

    from emotion_analyzer import evaluate

    df = pd.DataFrame({"file": [f"{l}_01.m4a" for l in config.LABELS], "label": config.LABELS,
                       "duration_s": 4.0, "speech_detected": True, "segments": 1, "transcript": "x",
                       "sound": config.LABELS, "sound_conf": 0.5, "text": ["joy"] * 7, "text_conf": 0.6,
                       "fused": config.LABELS[:6] + [""], "fused_conf": [0.5] * 6 + [0],
                       "disagreement": False, "total_ms": 900})
    md, sc = evaluate.own_markdown(df, {"asr": "a", "window_s": 30, "sound": "s", "text": "t", "fusion_w_sound": 0.6})
    assert sc["sound"]["accuracy"] == 100.0 and sc["fused"]["accuracy"] == pytest.approx(600 / 7, abs=0.1)
    assert "no speech" in md and "small sample" in md and "transcript" not in md.split("| File")[1]


def test_chatbot_answer_parsing_and_report():
    import pandas as pd

    from emotion_analyzer import chatbot_compare as cc

    assert cc.parse_label("Joy.") == "joy" and cc.parse_label("**Sadness**") == "sadness"
    assert cc.parse_label("The speaker sounds happy") == "" and cc.parse_label(None) == ""
    raw = pd.DataFrame({"file": ["anger_01.m4a", "joy_01.m4a"], "label": ["anger", "joy"],
                        "answer": ["Anger", "happy"], "parsed": ["anger", ""], "latency_s": [1.5, 2.5],
                        "model": "gemini-x"})
    ours = pd.DataFrame({"file": ["anger_01.m4a", "joy_01.m4a"], "fused": ["anger", "joy"],
                         "fused_conf": [0.6, 0.5], "total_ms": [800, 900]})
    md, s = cc.markdown(raw, ours, "2026-10-20")
    assert s["gemini"]["accuracy"] == 50.0 and s["ours"]["accuracy"] == 100.0 and s["invalid"] == 1
    assert "not private" in md and "`gemini-x`" in md and '("happy")' in md
