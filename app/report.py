"""The data behind the Results tab (spec §5.3, §5.4).

Assembled once at start-up from the aggregate JSON files in results/ (written by
`evaluate report`, `evaluate own`, `chatbot_compare` and `latency`) and from
models/fusion.json, so the page always shows the last evaluation. Every section is
copied field by field from a whitelist, so only aggregates reach the page: never MELD
audio, transcripts, clip ids or file names. A section whose file is missing or malformed
is marked unavailable instead of failing the server.
"""

import json
from pathlib import Path

from emotion_analyzer import config


def _pick(d, keys):
    return {k: d[k] for k in keys if k in d}


def _need(d, keys):
    """The fields a section can't be drawn without; a missing one makes it unavailable."""
    missing = [k for k in keys if k not in d]
    if missing:
        raise KeyError(", ".join(missing))
    return d


def _results_table(d):
    rows = [_pick(r, ("row", "condition", "n_seeds", "n", "weighted_f1_mean", "weighted_f1_sd", "macro_f1_mean",
                      "accuracy_mean", "ci_low", "ci_high", "dev_weighted_f1_mean")) for r in d["rows"]]
    return {"rows": rows, **_pick(d, ("gains", "w_sound", "weight_fit", "all_dev_weight_reference", "reference"))}


def _per_class(d):
    branches = {k: _pick(b, ("per_class", "weighted_f1", "macro_f1", "accuracy", "confusion"))
                for k, b in d["branches"].items() if k in ("sound", "text", "fused")}
    disagreement = _pick(d.get("disagreement") or {}, ("flagged", "flagged_pct", "n", "sound_right_pct",
                                                       "text_right_pct", "fused_right_pct", "fused_right_other_pct"))
    return {"labels": d["labels"], "n": d["n"], "branches": branches, "disagreement": disagreement or None}


def _wer(d):
    rows = [_pick(r, ("split", "window_s", "wer", "substitutions", "deletions", "insertions", "ref_words", "n"))
            for r in d["rows"]]
    return {"rows": rows, "decision": _pick(d["decision"], ("case", "rule", "window_s", "wer_gap_10s_minus_30s"))}


def _calibration(d):
    bins = {k: [_pick(b, ("confidence", "accuracy", "count")) for b in v] for k, v in d["reliability"].items()}
    return {"reliability": bins, **_pick(d, ("ece_before", "ece_after", "rows", "bins", "t_sound", "t_text", "w_sound"))}


def _latency(d):
    return _pick(_need(d, ("stages_ms", "peak_memory_gb")), ("clip_s", "date", "mains_power", "models", "load_s", "peak_memory_gb", "runs", "warmup",
                     "stages_ms"))


def _parity(d):
    return _pick(_need(d, ("rows", "pass")), ("n", "max_gap", "rows", "label_agreement", "identical_transcripts_pct", "wer", "pass"))


def _own(d):
    before = d.get("before")
    return {**_pick(_need(d, ("n", "scores")), ("n", "per_emotion", "scores", "w_sound", "median_ms", "mean_duration_s", "confusion_fused")),
            "before": _pick(before, ("label", "scores")) if before else None}


def _chatbot(d):
    return _pick(_need(d, ("gemini", "ours", "n_answered", "n_total")), ("gemini", "ours", "ours_before", "model", "served", "date", "invalid", "agree_pct",
                     "n_answered", "n_total", "partial", "median_latency_s"))


SECTIONS = {
    "results_table": ("results_table.json", _results_table),
    "per_class": ("per_class.json", _per_class),
    "wer": ("wer.json", _wer),
    "calibration": ("calibration.json", _calibration),
    "latency": ("latency.json", _latency),
    "parity": ("parity.json", _parity),
    "own_recordings": ("own_recordings.json", _own),
    "chatbot": ("chatbot.json", _chatbot),
}


def build_report(results_dir=None, fusion_path=None):
    results_dir = Path(results_dir or config.RESULTS_DIR)
    report = {"version": config.VERSION, "labels": config.LABELS,
              "targets": {"latency_s": config.LATENCY_TARGET_S, "latency_stretch_s": 1.2,
                          "memory_gb": config.MEMORY_TARGET_GB, "parity_max_gap": 1.5},
              "sections": {}}
    for name, (file, pick) in SECTIONS.items():
        try:
            report["sections"][name] = {"available": True, **pick(json.loads((results_dir / file).read_text(encoding="utf-8")))}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            report["sections"][name] = {"available": False, "reason": f"results/{file} is missing or unreadable"}
    try:
        fusion = json.loads(Path(fusion_path or config.FUSION_PATH).read_text(encoding="utf-8"))
        report["deployed"] = {"available": True, **_pick(fusion, (
            "t_sound", "t_text", "w_sound", "weight_fit", "n_weight", "n_dev", "dev_weighted_f1",
            "weight_clips_weighted_f1", "grid", "all_dev_weight_reference"))}
    except (OSError, ValueError):
        report["deployed"] = {"available": False, "reason": "models/fusion.json is missing or unreadable"}
    return report
