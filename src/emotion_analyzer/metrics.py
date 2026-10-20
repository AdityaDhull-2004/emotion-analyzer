"""Metrics (spec §6.2, §10.1): weighted-F1, macro-F1, accuracy, per-class report,
confusion matrix, bootstrap confidence intervals, seed mean ± sd, calibration error and
word error rate. F1 and accuracy are reported in points (0–100)."""

import json
from functools import lru_cache

import jiwer
import numpy as np
from sklearn.metrics import (accuracy_score, confusion_matrix as _confusion_matrix, f1_score,
                             precision_recall_fscore_support)

from . import config

_ALL = list(range(config.NUM_LABELS))


def weighted_f1(y_true, y_pred):
    return 100.0 * f1_score(y_true, y_pred, labels=_ALL, average="weighted", zero_division=0)


def macro_f1(y_true, y_pred):
    return 100.0 * f1_score(y_true, y_pred, labels=_ALL, average="macro", zero_division=0)


def accuracy(y_true, y_pred):
    return 100.0 * accuracy_score(y_true, y_pred)


def summary(y_true, y_pred):
    return {"weighted_f1": weighted_f1(y_true, y_pred), "macro_f1": macro_f1(y_true, y_pred),
            "accuracy": accuracy(y_true, y_pred), "n": int(len(y_true))}


def per_class(y_true, y_pred):
    """Precision, recall, F1 (points) and support per label, in the fixed order."""
    p, r, f, s = precision_recall_fscore_support(y_true, y_pred, labels=_ALL, zero_division=0)
    return {label: {"precision": 100 * p[i], "recall": 100 * r[i], "f1": 100 * f[i],
                    "support": int(s[i])} for i, label in enumerate(config.LABELS)}


def confusion(y_true, y_pred):
    """Rows are true labels, columns predictions, in the fixed label order."""
    return _confusion_matrix(y_true, y_pred, labels=_ALL)


def bootstrap_ci(y_true, y_pred, metric=weighted_f1, n=config.BOOTSTRAP_RESAMPLES,
                 seed=config.BOOTSTRAP_SEED, alpha=0.05):
    """95% percentile bootstrap interval over utterances (§10.1)."""
    y_true, y_pred = np.asarray(y_true), np.asarray(y_pred)
    rng = np.random.default_rng(seed)
    stats = np.empty(n)
    for i in range(n):
        idx = rng.integers(0, len(y_true), len(y_true))
        stats[i] = metric(y_true[idx], y_pred[idx])
    return float(np.percentile(stats, 100 * alpha / 2)), float(np.percentile(stats, 100 * (1 - alpha / 2)))


def weighted_f1_counts(y_true, y_pred):
    """weighted_f1 from a bincount confusion matrix: the same value, about 50 times faster,
    for the bootstrap's thousands of resamples."""
    k = config.NUM_LABELS
    cm = np.bincount(np.asarray(y_true) * k + np.asarray(y_pred), minlength=k * k).reshape(k, k)
    tp, support, predicted = np.diag(cm), cm.sum(1), cm.sum(0)
    denom = support + predicted
    f1 = np.divide(2 * tp, denom, out=np.zeros(k), where=denom > 0)
    return 100.0 * float((f1 * support).sum() / max(support.sum(), 1))


def bootstrap_ci_seeds(y_true, preds, metric=weighted_f1_counts, n=config.BOOTSTRAP_RESAMPLES,
                       seed=config.BOOTSTRAP_SEED, alpha=0.05):
    """95% interval of the seed mean: each resample of the utterances scores every seed's
    predictions and averages them (§10.1, F5). With one seed it equals bootstrap_ci."""
    y_true, preds = np.asarray(y_true), [np.asarray(p) for p in preds]
    rng = np.random.default_rng(seed)
    stats = np.empty(n)
    for i in range(n):
        idx = rng.integers(0, len(y_true), len(y_true))
        stats[i] = np.mean([metric(y_true[idx], p[idx]) for p in preds])
    return float(np.percentile(stats, 100 * alpha / 2)), float(np.percentile(stats, 100 * (1 - alpha / 2)))


def mean_sd(values):
    v = np.asarray(values, dtype=float)
    return float(v.mean()), float(v.std(ddof=1)) if len(v) > 1 else 0.0


def reliability(probs, y_true, bins=config.ECE_BINS):
    """Per-bin confidence, accuracy and count for equal-width confidence bins."""
    probs, y_true = np.asarray(probs), np.asarray(y_true)
    conf = probs.max(1)
    correct = (probs.argmax(1) == y_true).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(conf, edges[1:-1], right=True), 0, bins - 1)
    out = []
    for b in range(bins):
        m = idx == b
        out.append({"lo": float(edges[b]), "hi": float(edges[b + 1]), "count": int(m.sum()),
                    "confidence": float(conf[m].mean()) if m.any() else None,
                    "accuracy": float(correct[m].mean()) if m.any() else None})
    return out


def ece(probs, y_true, bins=config.ECE_BINS):
    """Expected calibration error in points, 15 equal-width bins (§10.4b)."""
    n = len(y_true)
    return 100.0 * sum(b["count"] / n * abs(b["accuracy"] - b["confidence"])
                       for b in reliability(probs, y_true, bins) if b["count"])


@lru_cache(maxsize=1)
def _english_normalizer():
    """Whisper's English text normaliser, with its spelling map (normalizer.json from
    the openai/whisper-small.en repository; cached by huggingface_hub)."""
    from huggingface_hub import hf_hub_download
    from transformers.models.whisper.english_normalizer import EnglishTextNormalizer

    path = hf_hub_download("openai/whisper-small.en", "normalizer.json")
    with open(path, encoding="utf-8") as f:
        return EnglishTextNormalizer(json.load(f))


def normalize_text(text):
    return _english_normalizer()(text or "")


def wer(references, hypotheses):
    """Corpus word error rate in percent, after Whisper's English normaliser (§8.1).

    Returns a dict with the WER, its edit counts and the number of reference words.
    References that normalise to nothing still count their inserted words.
    """
    refs = [normalize_text(r) for r in references]
    hyps = [normalize_text(h) for h in hypotheses]
    out = jiwer.process_words(refs, hyps)
    ref_words = out.hits + out.substitutions + out.deletions
    errors = out.substitutions + out.deletions + out.insertions
    return {
        "wer": 100.0 * errors / max(ref_words, 1),
        "substitutions": out.substitutions,
        "deletions": out.deletions,
        "insertions": out.insertions,
        "ref_words": ref_words,
        "n": len(refs),
    }
