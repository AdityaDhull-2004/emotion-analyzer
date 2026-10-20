"""Sound head (spec §8.2) and text model (§8.3). Text-model training needs the RoBERTa
weights and is marked slow."""

import numpy as np
import pytest
import torch

from emotion_analyzer import config, sound_model, text_model


def test_attnpool_head_size_and_shapes():
    m = sound_model.AttnPoolHead()
    n_params = sum(p.numel() for p in m.parameters())
    assert 0.2e6 < n_params < 0.3e6
    x, mask = sound_model.pad_batch([np.random.randn(50, 768), np.random.randn(80, 768)])
    assert m(x, mask).shape == (2, 7)


def test_padding_does_not_change_output():
    m = sound_model.AttnPoolHead().eval()
    a = np.random.default_rng(0).normal(size=(40, 768)).astype(np.float32)
    b = np.random.default_rng(1).normal(size=(120, 768)).astype(np.float32)
    alone = sound_model.predict_proba(m, [a])
    padded = sound_model.predict_proba(m, [a, b], batch_size=2)
    assert np.allclose(alone[0], padded[0], atol=1e-5)


def test_augment():
    rng = np.random.default_rng(0)
    frames = np.arange(300)[:, None].repeat(4, 1)
    lengths = [len(sound_model.augment(frames, rng, crop_prob=1.0, frame_drop=0.0)) for _ in range(50)]
    assert min(lengths) >= 50 and max(lengths) <= 300
    kept = len(sound_model.augment(frames, rng, crop_prob=0.0, frame_drop=0.1))
    assert 240 <= kept <= 300
    assert len(sound_model.augment(frames[:3], rng, frame_drop=0.99)) >= 1


def test_schedules():
    assert sound_model.cosine_with_warmup(0, 10, 100) == pytest.approx(0.1)
    assert sound_model.cosine_with_warmup(10, 10, 100) == pytest.approx(1.0)
    assert sound_model.cosine_with_warmup(100, 10, 100) == pytest.approx(0.0)
    assert text_model._linear_with_warmup(99, 10, 100) == pytest.approx(1 / 90)


def _toy_frames(n, rng):
    """Clips whose label is encoded in the mean of a few dimensions."""
    labels = rng.integers(0, 7, n)
    frames = []
    for y in labels:
        f = rng.normal(0, 1, (int(rng.integers(20, 60)), 768)).astype(np.float32)
        f[:, y * 10:(y + 1) * 10] += 2.0
        frames.append(f)
    return frames, labels


def test_sound_head_trains_and_round_trips(tmp_path):
    rng = np.random.default_rng(0)
    tr_f, tr_y = _toy_frames(160, rng)
    dv_f, dv_y = _toy_frames(60, rng)
    model, history, best = sound_model.train(tr_f, tr_y, dv_f, dv_y, seed=0, max_epochs=5,
                                             patience=3, log=lambda *_: None)
    assert best > 80 and len(history) >= 3
    path = tmp_path / "sound_head.pt"
    sound_model.save(model, path, {"seed": 0, "dev_wf1": best, "window_s": 10})
    loaded, info = sound_model.load(path)
    assert info["name"] == "attnpool-v1" and info["labels"] == config.LABELS
    assert np.allclose(sound_model.predict_proba(model, dv_f[:5]),
                       sound_model.predict_proba(loaded, dv_f[:5]), atol=1e-6)


def test_text_training_set_rules():
    df = text_model.build_training_set(
        ["Okay.", "I hate this!", "  ", "Okay."], [4, 0, 1, 3],
        ["okay", "I hate this!", "", "Okay."], [4, 0, 1, 3])
    assert "" not in set(df["text"])
    assert len(df[(df["text"] == "I hate this!") & (df["label_id"] == 0)]) == 1
    assert set(df[df["text"] == "Okay."]["label_id"]) == {3, 4}     # same text, two labels kept
    assert len(df[(df["text"] == "Okay.") & (df["label_id"] == 3)]) == 1


@pytest.mark.slow
def test_text_model_tiny_training_and_int8(tmp_path):
    texts = ["I am so happy!", "This is terrible.", "What?!", "Fine.", "I'm scared."] * 8
    labels = np.array([3, 5, 6, 4, 2] * 8)
    df = text_model.build_training_set(texts, labels)
    model, tok, history, best = text_model.train(df, texts[:5], labels[:5], seed=0, epochs=1,
                                                 batch_size=8, log=lambda *_: None)
    assert len(history) == 1
    text_model.save(model, tok, tmp_path / "text_model_seed0", {"seed": 0, "dev_wf1": best})
    clf = text_model.TextClassifier([tmp_path / "text_model_seed0"], precision="int8")
    probs = clf.predict_proba(["I am so happy!", ""])
    assert probs.shape == (2, 7) and np.allclose(probs.sum(1), 1.0, atol=1e-4)
    assert isinstance(clf.models[0][0].roberta.encoder.layer[0].attention.self.query,
                      torch.ao.nn.quantized.dynamic.Linear)
    fp32 = text_model.TextClassifier([tmp_path / "text_model_seed0"], precision="fp32")
    assert type(fp32.models[0][0].roberta.encoder.layer[0].attention.self.query) is torch.nn.Linear
    assert np.allclose(fp32.predict_proba(["I am so happy!"]).sum(), 1.0, atol=1e-4)
    with pytest.raises(ValueError):
        text_model.TextClassifier([tmp_path / "text_model_seed0"], precision="fp16")
