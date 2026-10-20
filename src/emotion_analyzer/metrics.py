"""Metrics (spec §6.2, §10.1): word error rate now; classification metrics follow in P4."""

import json
from functools import lru_cache

import jiwer


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
