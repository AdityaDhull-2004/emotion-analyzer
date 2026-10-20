"""Results tables from the saved probabilities (spec §10).

This part summarises the Kaggle training runs (S8): per-run dev and test scores, the
seed means of the trained rows R1-R6 (§10.2), the WER table, and the compact final
results block that is saved as logs/final_results.txt.

A run folder holds pred_{split}.npz (sound) or pred_{split}_{real,whisper}.npz (text),
each with ids, labels and probs; folders are named {run}_seed{k} under runs/sound/
and runs/text/.
"""

import json
import re
from pathlib import Path

import numpy as np

from . import config, fusion, metrics

# Trained rows of §10.2: (row, branch, run, prediction file stem without the split)
ROWS = [
    ("R1", "sound", "main", "pred_{split}"),
    ("R2", "sound", "A", "pred_{split}"),
    ("R3", "sound", "W", "pred_{split}"),
    ("R4", "text", "main", "pred_{split}_real"),
    ("R5", "text", "main", "pred_{split}_whisper"),
    ("R6", "text", "T", "pred_{split}_whisper"),
]
RUN_DIR_RE = re.compile(r"^(?P<run>\w+?)_seed(?P<seed>\d+)$")


def majority_baseline(labels):
    y = np.asarray(labels)
    return metrics.summary(y, np.full_like(y, config.LABEL_TO_ID["neutral"]))


def run_dirs(runs_root, branch):
    """{(run, seed): folder} for every finished run of one branch."""
    out = {}
    for d in sorted((Path(runs_root) / branch).glob("*_seed*")):
        m = RUN_DIR_RE.match(d.name)
        if m and any(d.glob("pred_*.npz")):
            out[(m["run"], int(m["seed"]))] = d
    return out


def summarize_runs(runs_root):
    """Per-run scores and the seed mean +- sd of each trained row, on dev and test."""
    runs_root = Path(runs_root)
    per_run, rows = {}, {}
    test_labels = None
    for row, branch, run, stem in ROWS:
        dirs = {s: d for (r, s), d in run_dirs(runs_root, branch).items() if r == run}
        for split in ("dev", "test"):
            scores = []
            for seed, d in sorted(dirs.items()):
                f = d / (stem.format(split=split) + ".npz")
                if not f.exists():
                    continue
                ids, y, p = fusion.load_predictions(f)
                s = metrics.summary(y, p.argmax(1))
                per_run[f"{row}/{run}_seed{seed}/{split}"] = s
                scores.append(s["weighted_f1"])
                if split == "test" and test_labels is None:
                    test_labels = y
            if scores:
                mean, sd = metrics.mean_sd(scores)
                rows[f"{row}/{split}"] = {"branch": branch, "run": run, "n_seeds": len(scores),
                                          "weighted_f1_mean": round(mean, 2),
                                          "weighted_f1_sd": round(sd, 2),
                                          "seeds": [round(v, 2) for v in scores]}
    if test_labels is not None:
        rows["R0/test"] = {"branch": "baseline", "run": "majority", "n_seeds": 0,
                           **{k: round(v, 2) for k, v in majority_baseline(test_labels).items()
                              if k != "n"}}
    return {"rows": rows, "per_run": per_run}


def provisional_fusion(runs_root):
    """A first look at R7 on test: each seed's sound head fused with the same seed's text
    model, temperatures and weight fitted on that seed's dev predictions. Phase 6 refits on
    the deployed models; these numbers are only for the Kaggle results block."""
    runs_root = Path(runs_root)
    sound = {s: d for (r, s), d in run_dirs(runs_root, "sound").items() if r == "main"}
    text = {s: d for (r, s), d in run_dirs(runs_root, "text").items() if r == "main"}
    out = []
    for seed in sorted(set(sound) & set(text)):
        dev = fusion.align(fusion.load_predictions(sound[seed] / "pred_dev.npz"),
                           fusion.load_predictions(text[seed] / "pred_dev_whisper.npz"))
        test = fusion.align(fusion.load_predictions(sound[seed] / "pred_test.npz"),
                            fusion.load_predictions(text[seed] / "pred_test_whisper.npz"))
        p = fusion.fit(dev[2], dev[3], dev[1])
        fused = fusion.fuse(test[2], test[3], p["w_sound"], p["t_sound"], p["t_text"])
        out.append({"seed": seed, "w_sound": p["w_sound"], "t_sound": round(p["t_sound"], 3),
                    "t_text": round(p["t_text"], 3),
                    "test_weighted_f1": round(metrics.weighted_f1(test[1], fused.argmax(1)), 2)})
    if not out:
        return None
    mean, sd = metrics.mean_sd([r["test_weighted_f1"] for r in out])
    return {"per_seed": out, "weighted_f1_mean": round(mean, 2), "weighted_f1_sd": round(sd, 2)}


def wer_table(transcripts_dir):
    out = {}
    for f in sorted(Path(transcripts_dir).glob("wer_*_*s.json")):
        w = json.loads(f.read_text())
        out[f.stem[4:]] = {"wer": round(w["wer"], 2), "n": w["n"]}
    return out


def final_block(summary):
    """The compact text block printed at the end of S8 (and saved as final_results.txt)."""
    lines = ["EMOTION ANALYZER - FINAL RESULTS (weighted-F1, mean +- sd over seeds)"]
    d = summary.get("decision") or {}
    if d:
        lines.append(f"window {d.get('window_s')} s (case {d.get('case')}); "
                     f"WER gap 10s-30s {d.get('wer_gap_10s_minus_30s')}")
    wer = summary.get("wer") or {}
    if wer:
        lines.append("WER  " + "  ".join(f"{k} {v['wer']:.1f}" for k, v in wer.items()))
    rows = summary["runs"]["rows"]
    names = {"R0": "majority", "R1": "sound main", "R2": "sound +acted (A)",
             "R3": "sound other window (W)", "R4": "text real", "R5": "text Whisper",
             "R6": "text real-only (T)"}
    lines.append(f"{'row':<26}{'dev':>15}{'test':>15}")
    for r, name in names.items():
        cells = []
        for split in ("dev", "test"):
            x = rows.get(f"{r}/{split}")
            if x is None:
                cells.append("-")
            elif r == "R0":
                cells.append(f"{x['weighted_f1']:.1f}")
            else:
                cells.append(f"{x['weighted_f1_mean']:.1f}+-{x['weighted_f1_sd']:.1f} ({x['n_seeds']})")
        lines.append(f"{r + ' ' + name:<26}{cells[0]:>15}{cells[1]:>15}")
    pf = summary.get("provisional_fusion")
    if pf:
        ws = ", ".join(str(r["w_sound"]) for r in pf["per_seed"])
        lines.append(f"R7 fused Whisper (provisional, per-seed w {ws}): test "
                     f"{pf['weighted_f1_mean']:.1f}+-{pf['weighted_f1_sd']:.1f}")
    for k in ("deployed_sound", "text_seeds", "elapsed_h", "skipped"):
        if summary.get(k) not in (None, [], {}):
            lines.append(f"{k}: {summary[k]}")
    return "\n".join(lines)
