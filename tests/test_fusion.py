"""Fusion (spec §8.4, §5.3) and the per-recording answer."""

import numpy as np
import pytest

from emotion_analyzer import config, fusion, speech


def _probs(i, conf):
    p = np.full(7, (1 - conf) / 6)
    p[i] = conf
    return p


def test_calibrate_and_fit_temperature():
    p = np.array([0.7, 0.1, 0.05, 0.05, 0.04, 0.03, 0.03])
    assert np.allclose(fusion.calibrate(p, 1.0), p, atol=1e-9)
    assert fusion.calibrate(p, 2.0).max() < p.max()

    rng = np.random.default_rng(0)
    logits = rng.normal(0, 3, (5000, 7))
    labels = (logits / 2.5 + rng.gumbel(size=logits.shape)).argmax(1)  # samples at T = 2.5
    t = fusion.fit_temperature(fusion._softmax(logits), labels)
    assert t == pytest.approx(2.5, rel=0.1)


def test_fuse_extremes_and_normalisation():
    ps, pt = _probs(0, 0.6), _probs(3, 0.8)
    assert np.allclose(fusion.fuse(ps, pt, 1.0), ps, atol=1e-6)
    assert np.allclose(fusion.fuse(ps, pt, 0.0), pt, atol=1e-6)
    f = fusion.fuse(np.stack([ps, pt]), np.stack([pt, ps]), 0.35)
    assert f.shape == (2, 7) and np.allclose(f.sum(1), 1.0)


def test_search_weight_prefers_better_branch_and_smallest_tie():
    labels = np.array([0, 1, 2, 3] * 10)
    good = np.stack([_probs(l, 0.6) for l in labels])
    bad = np.stack([_probs((l + 1) % 7, 0.9) for l in labels])
    w, table = fusion.search_weight(good, bad, labels)
    assert len(table) == 21 and w > 0.5
    w2, _ = fusion.search_weight(good, good, labels)
    assert w2 == 0.0


def test_disagreement_rule():
    a = fusion.answer(_probs(0, 0.61))
    b = fusion.answer(_probs(6, 0.55))
    assert fusion.disagreement(a, b)
    assert not fusion.disagreement(a, fusion.answer(_probs(6, 0.35)))
    assert not fusion.disagreement(a, fusion.answer(_probs(0, 0.9)))
    assert fusion.disagreement(a, fusion.answer(_probs(6, 0.35)), min_conf=0.30)


def test_answer_and_overall():
    ans = fusion.answer(_probs(4, 0.5))
    assert ans["label"] == "neutral" and list(ans["probs"]) == config.LABELS
    o = fusion.overall([_probs(0, 1.0), _probs(1, 1.0)], [3.0, 1.0])
    assert o[0] == pytest.approx(0.75) and o[1] == pytest.approx(0.25)


class _FakeSpeech:
    name, window_s = "fake-asr", 10

    def analyze_segment(self, audio, timer, window_s=None):
        with timer.stage("encode"):
            frames = np.zeros((max(1, len(audio) // 320), 768), dtype=np.float32)
        with timer.stage("transcribe"):
            text = "I can't believe you did that!"
        return frames, text, timer


class _Fixed:
    def __init__(self, p, name="fake"):
        self.p, self.name = p, name

    def predict_proba(self, items):
        return np.stack([self.p] * len(items))


def test_analyzer_response_shape():
    an = fusion.Analyzer(_FakeSpeech(), _Fixed(_probs(0, 0.61)), _Fixed(_probs(6, 0.55)),
                         {"t_sound": 1.0, "t_text": 1.0, "w_sound": 0.35})
    r = an.analyze(str(config.FIXTURES_DIR / "speech_short.wav"))
    assert r["speech_detected"] is True and len(r["segments"]) == 1
    seg = r["segments"][0]
    assert seg["sound"]["label"] == "anger" and seg["text"]["label"] == "surprise"
    assert seg["disagreement"] is True
    assert set(r["timing_ms"]) == {"decode", "encode", "transcribe", "sound", "text", "fusion", "total"}
    assert r["models"]["fusion_w_sound"] == 0.35
    assert r["overall"]["label"] == seg["fused"]["label"]


def test_analyzer_silence_and_errors(tmp_path):
    import soundfile as sf

    an = fusion.Analyzer(_FakeSpeech(), _Fixed(_probs(0, 0.6)), _Fixed(_probs(0, 0.6)),
                         {"t_sound": 1.0, "t_text": 1.0, "w_sound": 0.5})
    silent = tmp_path / "silence.wav"
    sf.write(str(silent), np.zeros(3 * 16000, dtype=np.float32), 16000)
    r = an.analyze(str(silent))
    assert r["speech_detected"] is False and r["segments"] == [] and r["overall"] is None
    short = tmp_path / "short.wav"
    sf.write(str(short), np.zeros(4000, dtype=np.float32), 16000)
    with pytest.raises(speech.AudioError) as e:
        an.analyze(str(short))
    assert e.value.status == 422


def test_prediction_files_align_and_fit(tmp_path):
    from emotion_analyzer.sound_model import save_predictions

    rng = np.random.default_rng(0)
    ids = np.array([f"dev_dia{i}_utt0" for i in range(60)])
    labels = rng.integers(0, 7, 60)
    sound = np.stack([_probs(l if rng.random() < 0.5 else (l + 1) % 7, 0.5) for l in labels])
    text = np.stack([_probs(l if rng.random() < 0.7 else (l + 2) % 7, 0.6) for l in labels])
    save_predictions(tmp_path / "s.npz", ids, labels, sound)
    save_predictions(tmp_path / "t0.npz", ids[::-1], labels[::-1], text[::-1])
    save_predictions(tmp_path / "t1.npz", ids[::-1], labels[::-1], text[::-1])
    ens = fusion.load_predictions(tmp_path / "t0.npz", tmp_path / "t1.npz")
    assert np.allclose(ens[2], text[::-1])
    a_ids, a_lab, ps, pt = fusion.align(fusion.load_predictions(tmp_path / "s.npz"), ens)
    assert np.array_equal(a_ids, ids) and np.allclose(pt, text)
    params = fusion.fit(ps, pt, a_lab)
    assert params["w_sound"] in config.FUSION_WEIGHT_GRID and params["t_text"] > 0
    with pytest.raises(ValueError):
        fusion.align((ids, labels, sound), (ids, (labels + 1) % 7, text))


def test_fit_chooses_the_weight_on_the_masked_clips_only():
    """§8.4 v1.4: temperatures on all of dev, the weight on a subset of its clips."""
    labels = np.array([0, 1, 2, 3] * 20)
    right = np.stack([_probs(l, 0.6) for l in labels])
    wrong = np.stack([_probs((l + 1) % 7, 0.6) for l in labels])
    subset = np.arange(len(labels)) >= 60          # here sound is wrong and text right
    p_sound = np.where(subset[:, None], wrong, right)
    p_text = np.where(subset[:, None], right, wrong)
    full = fusion.fit(p_sound, p_text, labels)
    masked = fusion.fit(p_sound, p_text, labels, weight_mask=subset)
    assert masked["w_sound"] < full["w_sound"] and masked["w_sound"] == 0.0
    assert masked["t_sound"] == full["t_sound"] and masked["t_text"] == full["t_text"]
