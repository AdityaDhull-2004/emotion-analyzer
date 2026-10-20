"""Results tables from the saved probabilities (spec §10).

The first part summarises the Kaggle training runs (S8): per-run dev and test scores, the
seed means of the trained rows R1-R6 (§10.2), the WER table, and the compact final
results block that is saved as logs/final_results.txt. The Phase 6 part reads the
exported outputs on the laptop: the text-ensemble rule (§8.3) and the CPU parity check
(§10.5).

A run folder holds pred_{split}.npz (sound) or pred_{split}_{real,whisper}.npz (text),
each with ids, labels and probs; folders are named {run}_seed{k} under runs/sound/
and runs/text/.
"""

import json
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, fusion, metrics, speech

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


# --- Phase 6: the Kaggle outputs on the laptop -------------------------------------------

KAGGLE_DIR = config.KAGGLE_OUT_DIR / "emotion_outputs"
PARITY_DIR = config.KAGGLE_OUT_DIR / "parity"
PARITY_MAX_GAP = 1.5  # AC-07, weighted-F1 points on dev
PROB_COLS = [f"p_{label}" for label in config.LABELS]


def kaggle_pred(branch, run, seed, split, kind=None, pred_dir=None):
    """One exported prediction file (S8): {branch}_{run}_seed{k}_{split}[_{kind}].npz."""
    name = f"{branch}_{run}_seed{seed}_{split}" + (f"_{kind}" if kind else "") + ".npz"
    return Path(pred_dir or KAGGLE_DIR / "predictions") / name


def text_ensemble_rule(pred_dir=None, seeds=config.SEEDS, min_gain=config.ENSEMBLE_MIN_GAIN):
    """§8.3, the F1 test that comes first: text-only weighted-F1 on the dev Whisper
    transcripts, the ensemble (mean of the seeds' probabilities) against the best single
    seed. Latency and memory are measured only if `passes_f1`."""
    files = {s: kaggle_pred("text", "main", s, "dev", "whisper", pred_dir) for s in seeds}
    single = {}
    for s, f in files.items():
        _, y, p = fusion.load_predictions(f)
        single[s] = metrics.weighted_f1(y, p.argmax(1))
    _, y, p = fusion.load_predictions(*files.values())
    ens = metrics.weighted_f1(y, p.argmax(1))
    best = max(single, key=lambda s: (single[s], -s))
    return {"single": {s: round(v, 2) for s, v in single.items()}, "best_seed": best,
            "ensemble": round(ens, 2), "gain": round(ens - single[best], 2),
            "min_gain": min_gain, "passes_f1": bool(ens - single[best] >= min_gain)}


def deployed_dev_files(pred_dir=None, text_seeds=None):
    """The Kaggle dev predictions of the deployed models: the sound seed recorded in
    sound_head.json, and the deployed text seed(s) on the dev Whisper transcripts."""
    info = json.loads(config.SOUND_HEAD_PATH.with_suffix(".json").read_text())
    seeds = config.TEXT_SEEDS_DEPLOYED if text_seeds is None else text_seeds
    return ([kaggle_pred("sound", info.get("run", "main"), info["seed"], "dev", None, pred_dir)],
            [kaggle_pred("text", "main", s, "dev", "whisper", pred_dir) for s in seeds])


def cpu_dev_pass(manifest, pipe, sound, out_csv, log=print, save_every=50):
    """The laptop's CPU int8 path on every clip of `manifest`, resumable: frames and
    transcript from one shared encode (`SpeechPipeline.analyze_segment` on the whole clip,
    as the app does for a segment), then the deployed sound head on the frames. Rows
    (id, label, transcript, sound probabilities) are appended to out_csv, which stays in
    the git-ignored data/kaggle/ (F3)."""
    out_csv = Path(out_csv)
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    done = set(pd.read_csv(out_csv, keep_default_na=False)["id"]) if out_csv.exists() else set()
    todo = manifest[~manifest["id"].isin(done)]
    log(f"CPU pass: {len(done)} clips done, {len(todo)} to go")
    t0, rows = time.perf_counter(), []

    def flush():
        if rows:
            pd.DataFrame(rows).to_csv(out_csv, mode="a", header=not out_csv.exists(), index=False)
            rows.clear()

    for k, r in enumerate(todo.itertuples(), 1):
        frames, transcript, _ = pipe.analyze_segment(speech.decode(str(r.path)))
        p = sound.predict_proba([frames])[0]
        rows.append({"id": r.id, "label_id": r.label_id, "transcript": transcript,
                     **dict(zip(PROB_COLS, p.round(6)))})
        if k % save_every == 0 or k == len(todo):
            flush()
            el = time.perf_counter() - t0
            log(f"  {len(done) + k}/{len(manifest)} clips, {el / k:.2f} s/clip, "
                f"about {el / k * (len(todo) - k) / 60:.0f} min left")
    flush()
    return pd.read_csv(out_csv, keep_default_na=False)


def parity(cpu_rows, text, params, sound_files, text_files, kaggle_transcripts=None):
    """§10.5: weighted-F1 on dev of the Kaggle fp16 path (the deployed models' exported
    dev predictions) against the laptop's CPU path, for sound, text and fused, with the
    fusion.json temperatures and weight on both sides. `text` is the deployed
    TextClassifier. With Kaggle's transcripts, it is also scored on them, which separates
    the text model's precision from transcript changes."""
    ids, y, k_sound, k_text = fusion.align(fusion.load_predictions(*sound_files),
                                           fusion.load_predictions(*text_files))
    keep = np.isin(ids, cpu_rows["id"].to_numpy())  # all of dev, or the clips of a smoke run
    ids, y, k_sound, k_text = ids[keep], y[keep], k_sound[keep], k_text[keep]
    cpu = cpu_rows.set_index("id").loc[ids]
    if not np.array_equal(cpu["label_id"].to_numpy(), y):
        raise ValueError("CPU and Kaggle labels disagree for the same clip")
    c_sound = cpu[PROB_COLS].to_numpy(dtype=np.float64)
    c_text = text.predict_proba(cpu["transcript"].tolist())

    def fused(ps, pt):
        return fusion.fuse(ps, pt, params["w_sound"], params["t_sound"], params["t_text"])

    def f1(p):
        return metrics.weighted_f1(y, p.argmax(1))

    scores = {"sound": (f1(k_sound), f1(c_sound)), "text": (f1(k_text), f1(c_text)),
              "fused": (f1(fused(k_sound, k_text)), f1(fused(c_sound, c_text)))}
    out = {"n": int(len(ids)), "max_gap": PARITY_MAX_GAP,
           "text_precision": getattr(text, "precision", config.TEXT_PRECISION),
           "rows": {k: {"kaggle": round(a, 2), "cpu": round(b, 2), "gap": round(b - a, 2),
                        "pass": bool(abs(b - a) <= PARITY_MAX_GAP)} for k, (a, b) in scores.items()},
           "label_agreement": {
               "sound": round(100 * float((k_sound.argmax(1) == c_sound.argmax(1)).mean()), 1),
               "text": round(100 * float((k_text.argmax(1) == c_text.argmax(1)).mean()), 1)}}
    if kaggle_transcripts is not None:
        kt = kaggle_transcripts.set_index("id").loc[ids]
        out["text_cpu_on_kaggle_transcripts"] = round(f1(text.predict_proba(kt["hypothesis"].tolist())), 2)
        same = kt["hypothesis"].str.strip().to_numpy() == cpu["transcript"].str.strip().to_numpy()
        out["identical_transcripts_pct"] = round(100 * float(same.mean()), 1)
        refs = kt["reference"].tolist()
        out["wer"] = {"kaggle": round(metrics.wer(refs, kt["hypothesis"].tolist())["wer"], 2),
                      "cpu": round(metrics.wer(refs, cpu["transcript"].tolist())["wer"], 2)}
    out["pass"] = all(r["pass"] for r in out["rows"].values())
    return out


def parity_markdown(p, window_s):
    prec = p.get("text_precision", config.TEXT_PRECISION)
    lines = ["# CPU parity on MELD dev (§10.5, AC-07)", "",
             "Kaggle: faster-whisper small.en float16 on a T4 and the text model in fp16 on the "
             "GPU. Laptop: small.en int8 on the CPU, the same sound head, and the text model "
             f"in {prec} on the CPU. {p['n']} dev clips, {window_s} s window, the same fusion.json "
             "temperatures and weight on both sides.", "",
             "| Branch | Kaggle fp16 | Laptop CPU | Difference | Within 1.5 |",
             "|---|---:|---:|---:|---|"]
    for k, r in p["rows"].items():
        lines.append(f"| {k} | {r['kaggle']:.2f} | {r['cpu']:.2f} | {r['gap']:+.2f} | "
                     f"{'yes' if r['pass'] else 'NO'} |")
    lines += ["", "Weighted-F1 in points; difference = laptop minus Kaggle.", ""]
    la = p["label_agreement"]
    lines.append(f"- Same predicted label on both paths: sound {la['sound']}% of clips, "
                 f"text {la['text']}%.")
    if "wer" in p:
        q = p["text_cpu_on_kaggle_transcripts"]
        lines += [f"- Transcripts: {p['identical_transcripts_pct']}% identical; WER "
                  f"{p['wer']['kaggle']:.2f}% on Kaggle and {p['wer']['cpu']:.2f}% on the laptop.",
                  f"- The {prec} text model on Kaggle's own transcripts scores {q:.2f}, so the "
                  f"text model on the CPU alone moves text by {q - p['rows']['text']['kaggle']:+.2f}; "
                  "the rest of the text difference comes from the transcripts."]
    verdict = "pass" if p["pass"] else "FAIL"
    lines += ["", f"**AC-07: {verdict}** (every difference must be within {p['max_gap']} points)."]
    return "\n".join(lines) + "\n"


# --- Phase 7: the evaluation report (§10) -------------------------------------------------

def write_json(path, obj):
    """An aggregate file for the web page's Results tab (§5.4), with numpy values made plain."""
    def plain(x):
        if isinstance(x, np.ndarray):
            return x.tolist()
        if isinstance(x, np.generic):
            return x.item()
        raise TypeError(f"not JSON-serialisable: {type(x).__name__}")

    Path(path).write_text(json.dumps(obj, indent=1, default=plain) + "\n", encoding="utf-8")


ROW_NAMES = {
    "R0": "Majority baseline (always neutral)",
    "R1": "Sound only (main)",
    "R2": "Sound only, ablation A (plus acted corpora)",
    "R3": "Sound only, ablation W (other window)",
    "R4": "Text on real transcripts",
    "R5": "Text on Whisper transcripts",
    "R6": "Text, ablation T (trained on real only), Whisper transcripts",
    "R7": "Fused, Whisper transcripts (sound seed i with text seed i)",
    "R8": "Fused, real transcripts (same pairing)",
    "R9": "Deployed system, Whisper transcripts",
}
SINGLE_ROWS = {"R1": ("sound", "main", None), "R2": ("sound", "A", None), "R3": ("sound", "W", None),
               "R4": ("text", "main", "real"), "R5": ("text", "main", "whisper"),
               "R6": ("text", "T", "whisper")}
OWN_EVAL_CSV = config.DATA_DIR / "own_eval.csv"  # per clip, with transcripts; git-ignored


def deployed_sound_seed():
    return int(json.loads(config.SOUND_HEAD_PATH.with_suffix(".json").read_text())["seed"])


def text_cpu(text, split, seeds=None, kaggle_dir=None):
    """The deployed text model (`text`, a TextClassifier) on Kaggle's MELD Whisper
    transcripts of one split in the decided window, cached per precision as per-utterance
    predictions in the git-ignored data/kaggle/."""
    from .sound_model import save_predictions

    seeds = config.TEXT_SEEDS_DEPLOYED if seeds is None else seeds
    cache = PARITY_DIR / f"text_{text.precision}_{split}_seed{'-'.join(map(str, seeds))}.npz"
    if not cache.exists():
        df = pd.read_csv(Path(kaggle_dir or KAGGLE_DIR) / "transcripts" / f"{split}_{config.WINDOW_S}s.csv",
                         keep_default_na=False)
        cache.parent.mkdir(parents=True, exist_ok=True)
        save_predictions(cache, df["id"], df["label"].map(config.LABEL_TO_ID),
                         text.predict_proba(df["hypothesis"].tolist()))
    return fusion.load_predictions(cache)


def _fused(sound, text, params):
    ids, y, ps, pt = fusion.align(sound, text)
    return ids, y, fusion.fuse(ps, pt, params["w_sound"], params["t_sound"], params["t_text"])


WEIGHT_FIT = "the dev clips from speakers outside the six main characters"


def weight_mask(ids, speakers=None):
    """True for the dev clips whose speaker isn't in the main cast (§8.4, v1.4)."""
    from . import data

    spk = (data.meld_speakers("dev") if speakers is None else speakers).reindex(ids)
    if spk.isna().any():
        raise ValueError(f"no speaker for {int(spk.isna().sum())} dev clips; run data.download_meld_meta()")
    return ~spk.isin(config.MAIN_CAST).to_numpy()


def fit_deployed(text_dev, pred_dir=None, precision=None, speakers=None):
    """§8.4: T_sound and T_text on the deployed models' dev probabilities, and the weight on
    the dev clips of speakers outside the main cast (v1.4). The sound head's probabilities
    are its Kaggle dev ones (CPU parity checks the features); the text model's are its CPU
    outputs in the deployed precision on Kaggle's dev Whisper transcripts, since int8
    changes the outputs. For reference it also records the weight that all of dev would
    give (the v1.3 rule) and the same fit on the fp16 text probabilities."""
    sound_f = kaggle_pred("sound", "main", deployed_sound_seed(), "dev", None, pred_dir)
    ids, y, ps, pt = fusion.align(fusion.load_predictions(sound_f), text_dev)
    m = weight_mask(ids, speakers)
    p = fusion.fit(ps, pt, y, weight_mask=m)
    fused = fusion.fuse(ps, pt, p["w_sound"], p["t_sound"], p["t_text"])

    def scores(mask):
        return {name: round(metrics.weighted_f1(y[mask], q[mask].argmax(1)), 2)
                for name, q in (("sound", ps), ("text", pt), ("fused", fused))}

    fp16 = [kaggle_pred("text", "main", s, "dev", "whisper", pred_dir) for s in config.TEXT_SEEDS_DEPLOYED]
    ids16, y16, ps16, pt16 = fusion.align(fusion.load_predictions(sound_f), fusion.load_predictions(*fp16))
    ref = fusion.fit(ps16, pt16, y16, weight_mask=weight_mask(ids16, speakers))
    return {"t_sound": p["t_sound"], "t_text": p["t_text"], "w_sound": p["w_sound"],
            "weight_fit": WEIGHT_FIT, "n_weight": int(m.sum()),
            "sound_dev": sound_f.name, "text_dev": f"{precision or config.TEXT_PRECISION} text seed(s) {list(config.TEXT_SEEDS_DEPLOYED)} "
            "on Kaggle's dev Whisper transcripts", "n_dev": int(len(ids)),
            "dev_weighted_f1": scores(np.ones(len(y), dtype=bool)), "weight_clips_weighted_f1": scores(m),
            "grid": p["grid"], "all_dev_weight_reference": fusion.fit(ps, pt, y)["w_sound"],
            "fp16_text_reference": {k: ref[k] for k in ("t_sound", "t_text", "w_sound")}}


def row_probs(row, split, params, text_cpu=None, pred_dir=None, seeds=config.SEEDS):
    """(labels, [probabilities per seed]) for one trained row of §10.2 on one split.
    R7 and R8 fuse sound seed i with text seed i (Kaggle fp16) at the deployed weight, each
    model temperature-scaled with its own T fitted on dev (§8.4). R9 is the deployed sound
    head with the deployed text model on the CPU and fusion.json (test only)."""
    def load(branch, run, seed, kind=None, sp=split):
        f = kaggle_pred(branch, run, seed, sp, kind, pred_dir)
        return fusion.load_predictions(f) if f.exists() else None

    def pair(seed, kind):
        s_dev, t_dev = load("sound", "main", seed, sp="dev"), load("text", "main", seed, kind, sp="dev")
        a, b = load("sound", "main", seed), load("text", "main", seed, kind)
        if not (a and b and s_dev and t_dev):
            return None
        _, y_dev, ps, pt = fusion.align(s_dev, t_dev)
        temps = {"t_sound": fusion.fit_temperature(ps, y_dev), "t_text": fusion.fit_temperature(pt, y_dev)}
        return _fused(a, b, {**temps, "w_sound": params["w_sound"]})

    if row in SINGLE_ROWS:
        got = [g for g in (load(*SINGLE_ROWS[row][:2], s, SINGLE_ROWS[row][2]) for s in seeds) if g]
    elif row in ("R7", "R8"):
        got = [g for g in (pair(s, "whisper" if row == "R7" else "real") for s in seeds) if g]
    elif row == "R9" and split == "test" and text_cpu is not None:
        got = [_fused(load("sound", "main", deployed_sound_seed()), text_cpu, params)]
    else:
        return None
    if not got:
        return None
    if any(not np.array_equal(g[0], got[0][0]) for g in got):
        raise ValueError(f"{row} {split}: the seeds' prediction files cover different clips")
    return got[0][1], [g[2] for g in got]


def results_rows(params, text_cpu, pred_dir=None, parity_json=None):
    """Rows R0-R9 on MELD test (§10.2): weighted-F1, macro-F1 and accuracy as seed mean ±
    sd, the 95% bootstrap interval of the seed mean, and the dev weighted-F1 for context."""
    out = []
    for row in ROW_NAMES:
        if row == "R0":
            y = row_probs("R1", "test", params, pred_dir=pred_dir)[0]
            preds = [np.full_like(y, config.LABEL_TO_ID["neutral"])]
        else:
            got = row_probs(row, "test", params, text_cpu, pred_dir)
            if got is None:
                continue
            y, probs = got
            preds = [p.argmax(1) for p in probs]
        per = [metrics.summary(y, p) for p in preds]
        r = {"row": row, "condition": ROW_NAMES[row], "n_seeds": len(preds), "n": int(len(y))}
        for m in ("weighted_f1", "macro_f1", "accuracy"):
            r[f"{m}_mean"], r[f"{m}_sd"] = (round(v, 2) for v in metrics.mean_sd([s[m] for s in per]))
        r["ci_low"], r["ci_high"] = (round(v, 2) for v in metrics.bootstrap_ci_seeds(y, preds))
        r["seeds_weighted_f1"] = " ".join(f"{s['weighted_f1']:.2f}" for s in per)
        dev = row_probs(row, "dev", params, pred_dir=pred_dir) if row != "R0" else None
        if dev is not None:
            r["dev_weighted_f1_mean"], r["dev_weighted_f1_sd"] = (round(v, 2) for v in metrics.mean_sd(
                [metrics.weighted_f1(dev[0], p.argmax(1)) for p in dev[1]]))
        elif row == "R9" and parity_json and Path(parity_json).exists():
            r["dev_weighted_f1_mean"] = json.loads(Path(parity_json).read_text())["rows"]["fused"]["cpu"]
            r["dev_weighted_f1_sd"] = 0.0
        out.append(r)
    return out


def fusion_gains(params, pred_dir=None, seeds=config.SEEDS):
    """The fusion gain on test (§10.9, AC-05): R7 minus R5 and R7 minus R1 as differences
    of seed means, each with a paired bootstrap 95% interval. The text files list the
    clips in another order, so every row is put in the sound files' order first."""
    ids = fusion.load_predictions(kaggle_pred("sound", "main", seeds[0], "test", None, pred_dir))[0]

    def labels(branch, run, kind):
        out = []
        for s in seeds:
            f_ids, _, p = fusion.load_predictions(kaggle_pred(branch, run, s, "test", kind, pred_dir))
            pos = {i: k for k, i in enumerate(f_ids)}
            out.append(p[[pos[i] for i in ids]].argmax(1))
        return out

    y, fused = row_probs("R7", "test", params, pred_dir=pred_dir, seeds=seeds)
    if len(y) != len(ids):
        raise ValueError("R7 doesn't cover every test clip")
    r7 = [p.argmax(1) for p in fused]
    out = {}
    for name, other in (("R7-R5", labels("text", "main", "whisper")), ("R7-R1", labels("sound", "main", None))):
        g, lo, hi = metrics.paired_bootstrap_gain(y, r7, other)
        out[name] = {"gain": round(g, 2), "ci_low": round(lo, 2), "ci_high": round(hi, 2)}
    return out


def results_table_markdown(rows, params, gains=None, reference=None):
    lines = ["# MELD test results (§10.2)", "",
             f"MELD test, {rows[0]['n']} utterances. Weighted-F1 is the headline (points). Trained rows "
             "show the mean ± sd over seeds 0, 1 and 2; the 95% interval is a bootstrap of the seed "
             f"mean over test utterances ({config.BOOTSTRAP_RESAMPLES} resamples, seed "
             f"{config.BOOTSTRAP_SEED}). Fused rows use the deployed weight (w_sound "
             f"{params['w_sound']}, chosen on {params.get('weight_fit', 'dev')}, §8.4).", "",
             "| Row | Condition | Seeds | Weighted-F1 | 95% CI | Macro-F1 | Accuracy | Dev weighted-F1 |",
             "|---|---|---:|---:|---|---:|---:|---:|"]

    def ms(r, m):
        return f"{r[m + '_mean']:.1f}" + (f" ± {r[m + '_sd']:.1f}" if r["n_seeds"] > 1 else "")

    for r in rows:
        dev = f"{r['dev_weighted_f1_mean']:.1f}" if "dev_weighted_f1_mean" in r else "–"
        if r["n_seeds"] > 1 and "dev_weighted_f1_mean" in r:
            dev += f" ± {r['dev_weighted_f1_sd']:.1f}"
        lines.append(f"| {r['row']} | {r['condition']} | {r['n_seeds'] if r['row'] != 'R0' else '–'} | "
                     f"**{ms(r, 'weighted_f1')}** | {r['ci_low']:.1f}–{r['ci_high']:.1f} | "
                     f"{ms(r, 'macro_f1')} | {ms(r, 'accuracy')} | {dev} |")
    lines += ["", "- R1–R8 are the Kaggle models' own probabilities (fp16 on the GPU). In R7 and R8 each "
              "model is temperature-scaled with its own T, fitted on dev (§8.4), before fusing at the "
              "deployed weight.",
              f"- R9 is a single run: the deployed sound head (main, seed {deployed_sound_seed()}) with its "
              f"Kaggle test probabilities, and the deployed text model ({config.TEXT_PRECISION}) on the "
              "laptop CPU, run on Kaggle's test Whisper transcripts, fused with `models/fusion.json` (T_sound "
              f"{params['t_sound']:.3f}, T_text {params['t_text']:.3f}). MELD test audio isn't kept on "
              "the laptop (§7.4), so the remaining CPU difference (int8 Whisper features and transcripts) "
              "is measured on dev by the parity check (`parity.md`); R9's dev value is that check's "
              "end-to-end CPU result."]
    if reference:
        lines.append(f"- For reference, at the weight that all of dev gives (w_sound "
                     f"{params['all_dev_weight_reference']}, the v1.3 rule): "
                     + ", ".join(f"{k} {r['weighted_f1_mean']:.1f}" for k, r in reference.items())
                     + ". The v1.4 rule was adopted after the own-recordings result (§20); MELD test wasn't "
                     "used to choose the weight.")
    if gains:
        lines.append("- Fusion gain on test, as a difference of seed means with a paired bootstrap 95% "
                     "interval (both rows scored on the same resampled utterances): "
                     + "; ".join(f"{k.replace('-', ' − ')} {g['gain']:+.1f} [{g['ci_low']:+.1f}, {g['ci_high']:+.1f}]"
                                 for k, g in gains.items()) + ".")
    return "\n".join(lines) + "\n"


def deployed_test_parts(params, text_cpu, pred_dir=None):
    """Calibrated branch probabilities and the fused output of the deployed system on test."""
    sound = fusion.load_predictions(kaggle_pred("sound", "main", deployed_sound_seed(), "test", None, pred_dir))
    ids, y, ps, pt = fusion.align(sound, text_cpu)
    return {"ids": ids, "y": y, "sound_raw": ps, "text_raw": pt,
            "sound": fusion.calibrate(ps, params["t_sound"]), "text": fusion.calibrate(pt, params["t_text"]),
            "fused": fusion.fuse(ps, pt, params["w_sound"], params["t_sound"], params["t_text"]),
            "fused_uncal": fusion.fuse(ps, pt, params["w_sound"])}


def confusion_png(cm, title, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    norm = cm / np.maximum(cm.sum(1, keepdims=True), 1)
    fig, ax = plt.subplots(figsize=(6.4, 5.6))
    im = ax.imshow(norm, cmap="Blues", vmin=0, vmax=1)
    ax.set_xticks(range(len(config.LABELS)), config.LABELS, rotation=45, ha="right")
    ax.set_yticks(range(len(config.LABELS)), config.LABELS)
    ax.set_xlabel("predicted")
    ax.set_ylabel("true")
    ax.set_title(title, fontsize=10)
    for i in range(cm.shape[0]):
        for j in range(cm.shape[1]):
            ax.text(j, i, f"{cm[i, j]}\n{100 * norm[i, j]:.0f}%", ha="center", va="center", fontsize=7,
                    color="white" if norm[i, j] > 0.5 else "black")
    fig.colorbar(im, ax=ax, fraction=0.046, label="share of the true class")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def per_class_report(parts, out_dir):
    """results/per_class.md and confusion_{sound,text,fused}.png for the deployed system."""
    y = parts["y"]
    lines = ["# Per-class results on MELD test (§10.1)", "",
             "The deployed system's branches and its fused output (R9). Precision, recall and F1 in "
             "points; support is the number of test utterances.", ""]
    names = {"sound": "Sound (how it sounds)",
             "text": f"Text (what was said, {config.TEXT_PRECISION}, Whisper transcripts)",
             "fused": "Fused (deployed)"}
    for key, name in names.items():
        pred = parts[key].argmax(1)
        rep = metrics.per_class(y, pred)
        lines += [f"## {name}", "", "| Class | Precision | Recall | F1 | Support |", "|---|---:|---:|---:|---:|"]
        lines += [f"| {c} | {v['precision']:.1f} | {v['recall']:.1f} | {v['f1']:.1f} | {v['support']} |"
                  for c, v in rep.items()]
        s = metrics.summary(y, pred)
        lines += ["", f"Weighted-F1 {s['weighted_f1']:.1f}, macro-F1 {s['macro_f1']:.1f}, accuracy "
                  f"{s['accuracy']:.1f}. Confusion matrix: `confusion_{key}.png`.", ""]
        confusion_png(metrics.confusion(y, pred), f"MELD test, {name.lower()}: rows true, columns predicted",
                      Path(out_dir) / f"confusion_{key}.png")
    return "\n".join(lines)


def per_class_json(parts):
    """results/per_class.json: per-class scores and confusion counts for each branch."""
    y = parts["y"]
    branches = {}
    for key in ("sound", "text", "fused"):
        pred = parts[key].argmax(1)
        branches[key] = {"per_class": metrics.per_class(y, pred), **metrics.summary(y, pred),
                         "confusion": metrics.confusion(y, pred)}
    return {"labels": config.LABELS, "n": int(len(y)), "branches": branches}


def wer_rows(transcripts_dir):
    rows = []
    for split in ("train", "dev", "test"):
        for w in config.WINDOWS_S:
            f = Path(transcripts_dir) / f"wer_{split}_{w}s.json"
            if f.exists():
                rows.append({"split": split, "window_s": w, **json.loads(f.read_text())})
    return rows


def wer_json(transcripts_dir, decision):
    """results/wer.json: corpus WER per split and window, and the window decision."""
    return {"rows": wer_rows(transcripts_dir),
            "decision": {k: decision[k] for k in ("case", "rule", "window_s", "wer_gap_10s_minus_30s")}}


def wer_markdown(transcripts_dir, decision):
    lines = ["# Word error rate (§10.3, AC-02)", "",
             "faster-whisper small.en, greedy, no timestamps, float16 on Kaggle's T4s. Whisper's English "
             "normaliser on reference and hypothesis, then corpus WER with `jiwer`. MELD's references "
             "are subtitles, which inflates the figures.", "",
             "| Split | Window | Clips | Ref. words | Subst. | Del. | Ins. | WER |",
             "|---|---|---:|---:|---:|---:|---:|---:|"]
    for x in wer_rows(transcripts_dir):
        lines.append(f"| {x['split']} | {x['window_s']} s | {x['n']} | {x['ref_words']} | {x['substitutions']} | "
                     f"{x['deletions']} | {x['insertions']} | **{x['wer']:.2f}%** |")
    g = decision["wer_gap_10s_minus_30s"]
    lines += ["", "## Window decision (§8.1)", "",
              f"- Phase 3 timing put the build in **case {decision['case']}**: small.en met AC-08 in both "
              "windows on the laptop, so S4 chose the window by WER on dev.",
              f"- Rule: {decision['rule']}.",
              f"- WER(10 s) − WER(30 s): **{g['dev']:+.2f}** points on dev and {g['test']:+.2f} on test.",
              f"- Chosen window: **{decision['window_s']} s**, recorded in `models/decision.json`."]
    return "\n".join(lines) + "\n"


def calibration_report(parts, params, out_dir):
    """results/calibration.md and reliability.png (§10.4b, AC-16): fused test ECE before and
    after temperature scaling, at the deployed weight."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    y = parts["y"]
    nll = lambda p: float(-np.mean(np.log(p[np.arange(len(y)), y] + 1e-12)))
    rows = [("Fused (deployed weight)", parts["fused_uncal"], parts["fused"]),
            ("Sound branch", parts["sound_raw"], parts["sound"]),
            ("Text branch", parts["text_raw"], parts["text"])]
    lines = ["# Calibration on MELD test (§10.4b, AC-16)", "",
             f"Expected calibration error (ECE, {config.ECE_BINS} equal-width confidence bins, in points) "
             "and negative log-likelihood, before and after temperature scaling. The temperatures were "
             f"fitted on dev by NLL: T_sound {params['t_sound']:.3f}, T_text {params['t_text']:.3f}. "
             f"Both fused rows use the deployed weight w_sound {params['w_sound']}.", "",
             "| Output | ECE before | ECE after | NLL before | NLL after | Accuracy |",
             "|---|---:|---:|---:|---:|---:|"]
    table = []
    for name, before, after in rows:
        table.append({"output": name, "ece_before": metrics.ece(before, y), "ece_after": metrics.ece(after, y),
                      "nll_before": nll(before), "nll_after": nll(after),
                      "accuracy": metrics.accuracy(y, after.argmax(1))})
        r = table[-1]
        lines.append(f"| {name} | {r['ece_before']:.2f} | {r['ece_after']:.2f} | "
                     f"{r['nll_before']:.3f} | {r['nll_after']:.3f} | {r['accuracy']:.1f} |")
    reliability = {k: [b for b in metrics.reliability(p, y) if b["count"] >= 10]
                   for k, p in (("before", parts["fused_uncal"]), ("after", parts["fused"]))}
    fig, ax = plt.subplots(figsize=(5.2, 5.0))
    ax.plot([0, 1], [0, 1], ls="--", color="grey", lw=1, label="perfect calibration")
    for label, p, style in (("before scaling", parts["fused_uncal"], "o-"), ("after scaling", parts["fused"], "s-")):
        bins = reliability[label.split()[0]]
        ax.plot([b["confidence"] for b in bins], [b["accuracy"] for b in bins], style, ms=4,
                label=f"{label} (ECE {metrics.ece(p, y):.1f})")
    ax.set_xlabel("confidence (top fused probability)")
    ax.set_ylabel("accuracy")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_title("Fused output on MELD test: reliability", fontsize=10)
    ax.legend(loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(Path(out_dir) / "reliability.png", dpi=150)
    plt.close(fig)
    before, after = metrics.ece(parts["fused_uncal"], y), metrics.ece(parts["fused"], y)
    lines += ["", "Reliability diagram: `reliability.png` (bins with at least 10 utterances).", "",
              f"**AC-16:** fused test ECE {before:.2f} before and {after:.2f} after temperature scaling, "
              "with the reliability diagram: **reported**."]
    return "\n".join(lines) + "\n", {"ece_before": round(before, 2), "ece_after": round(after, 2),
                                     "rows": table, "reliability": reliability, "bins": config.ECE_BINS,
                                     **{k: params[k] for k in ("t_sound", "t_text", "w_sound")}}


def error_analysis(parts, transcripts_csv, n=10, seed=0):
    """results/error_analysis.md (§10.8): 10 MELD test clips where the branches disagree
    (the app's rule: different labels, both confidences ≥ 0.40), quoted as text, and the
    confusions per class of the fused output."""
    y, lab = parts["y"], config.LABELS
    s_lab, t_lab, f_lab = (parts[k].argmax(1) for k in ("sound", "text", "fused"))
    s_conf, t_conf = parts["sound"].max(1), parts["text"].max(1)
    flag = (s_lab != t_lab) & (s_conf >= config.DISAGREEMENT_MIN_CONF) & (t_conf >= config.DISAGREEMENT_MIN_CONF)
    tr = pd.read_csv(transcripts_csv, keep_default_na=False).set_index("id").loc[parts["ids"]]
    rng = np.random.default_rng(seed)
    right, wrong = np.flatnonzero(flag & (f_lab == y)), np.flatnonzero(flag & (f_lab != y))
    pick = list(rng.choice(right, min(n // 2, len(right)), replace=False))
    n_right = len(pick)
    pick += list(rng.choice(wrong, min(n - len(pick), len(wrong)), replace=False))
    pct = lambda m: 100 * float(np.mean(m)) if np.size(m) else 0.0
    lines = ["# Error analysis on MELD test (§10.8)", "",
             f"The deployed system on {len(y)} test utterances. The branches disagree (different labels, "
             f"both calibrated confidences ≥ {config.DISAGREEMENT_MIN_CONF}) on **{int(flag.sum())}** "
             f"clips ({pct(flag):.1f}%). On those clips the sound branch is right {pct(s_lab[flag] == y[flag]):.1f}% "
             f"of the time, the text branch {pct(t_lab[flag] == y[flag]):.1f}%, and the fused answer "
             f"{pct(f_lab[flag] == y[flag]):.1f}%. On the other clips the fused answer is right "
             f"{pct(f_lab[~flag] == y[~flag]):.1f}% of the time.", "",
             f"## {len(pick)} disagreements ({n_right} where the fused answer is right, then "
             f"{len(pick) - n_right} where it is wrong; drawn with a fixed seed)", "",
             "| Clip | True | Sound | Text | Fused | Whisper transcript | Subtitle |", "|---|---|---|---|---|---|---|"]
    q = lambda s: str(s).replace("|", "/")
    for i in pick:
        r = tr.iloc[i]
        lines.append(f"| {parts['ids'][i].replace('test_', '')} | {lab[y[i]]} | {lab[s_lab[i]]} {s_conf[i]:.2f} | "
                     f"{lab[t_lab[i]]} {t_conf[i]:.2f} | {lab[f_lab[i]]} {parts['fused'][i].max():.2f} | "
                     f"“{q(r['hypothesis'])}” | “{q(r['reference'])}” |")
    cm = metrics.confusion(y, f_lab)
    lines += ["", "## Confusions per class (fused output)", "",
              "| True class | Support | Recall | Most often mistaken for |", "|---|---:|---:|---|"]
    for c in range(len(lab)):
        row = cm[c].astype(float)
        others = sorted(((row[j], j) for j in range(len(lab)) if j != c), reverse=True)[:2]
        tops = ", ".join(f"{lab[j]} {100 * v / max(row.sum(), 1):.0f}%" for v, j in others if v)
        lines.append(f"| {lab[c]} | {int(row.sum())} | {100 * row[c] / max(row.sum(), 1):.1f}% | {tops} |")
    return "\n".join(lines) + "\n", {"flagged": int(flag.sum()), "flagged_pct": round(pct(flag), 1),
                                   "n": int(len(y)), "sound_right_pct": round(pct(s_lab[flag] == y[flag]), 1),
                                   "text_right_pct": round(pct(t_lab[flag] == y[flag]), 1),
                                   "fused_right_pct": round(pct(f_lab[flag] == y[flag]), 1),
                                   "fused_right_other_pct": round(pct(f_lab[~flag] == y[~flag]), 1)}


DISCUSSION_HEADING = "## Discussion"


def keep_discussion(path, new_md):
    """`new_md` plus the hand-written "## Discussion" section of the report already at
    `path`, so regenerating the tables doesn't erase the written analysis."""
    old = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
    i = old.find(DISCUSSION_HEADING)
    return new_md if i < 0 else new_md.rstrip("\n") + "\n\n" + old[i:]


def own_recordings_eval(analyzer, manifest, out_csv=OWN_EVAL_CSV, log=print):
    """Run the deployed system on every own recording (§10.6). Per-clip rows, transcripts
    included, go to the git-ignored data/own_eval.csv."""
    rows = []
    for r in manifest.itertuples():
        res = analyzer.analyze(str(r.path))
        segs = res["segments"]
        if segs:
            d = np.array([s["end_s"] - s["start_s"] for s in segs])
            branch = {k: fusion.answer(fusion.overall([[s[k]["probs"][l] for l in config.LABELS] for s in segs], d))
                      for k in ("sound", "text")}
        row = {"file": Path(r.path).name, "label": r.label, "duration_s": res["duration_s"],
               "speech_detected": res["speech_detected"], "segments": len(segs),
               "transcript": " ".join(s["transcript"] for s in segs),
               "sound": branch["sound"]["label"] if segs else "", "sound_conf": branch["sound"]["confidence"] if segs else 0,
               "text": branch["text"]["label"] if segs else "", "text_conf": branch["text"]["confidence"] if segs else 0,
               "fused": res["overall"]["label"] if segs else "", "fused_conf": res["overall"]["confidence"] if segs else 0,
               "disagreement": any(s["disagreement"] for s in segs), "total_ms": res["timing_ms"]["total"]}
        rows.append(row)
        log(f"  {row['file']}: true {row['label']}, fused {row['fused']} ({row['fused_conf']:.2f}), "
            f"{row['total_ms']} ms")
    df = pd.DataFrame(rows)
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_csv, index=False)
    return df


def own_scores(df, col):
    y = df["label"].map(config.LABEL_TO_ID).to_numpy()
    pred = df[col].map(config.LABEL_TO_ID).fillna(-1).astype(int).to_numpy()
    ok = pred >= 0
    pred = np.where(ok, pred, (y + 1) % config.NUM_LABELS)  # no answer counts as wrong
    s = metrics.summary(y, pred)
    lo, hi = metrics.bootstrap_ci(y, pred, metric=metrics.accuracy)
    return {**{k: round(v, 1) for k, v in s.items() if k != "n"}, "acc_ci": (round(lo, 1), round(hi, 1)),
            "n": int(len(y))}


def own_markdown(df, models, before=None, before_label=None):
    """results/own_recordings.md. `before` is an earlier own_eval table of the same clips
    from a system that was changed after it was seen; both results are then shown, and
    the report says so (§10.6)."""
    sc = {k: own_scores(df, k) for k in ("sound", "text", "fused")}
    lines = ["# Own recordings: new voices (§10.6, AC-10)", "",
             f"The deployed system ({models['asr']}, {models['window_s']} s window; {models['sound']}; "
             f"{models['text']} {config.TEXT_PRECISION}; w_sound {models['fusion_w_sound']}) on the user's {len(df)} recordings in "
             "`data/own/`, labelled by file name. Transcripts stay out of this file (the recordings are "
             "private); they are in the git-ignored `data/own_eval.csv`.", "",
             "| Output | Accuracy | 95% CI (accuracy) | Weighted-F1 | Macro-F1 |", "|---|---:|---|---:|---:|"]
    for k, name in (("sound", "Sound"), ("text", "Text"), ("fused", "Fused (the app's answer)")):
        s = sc[k]
        lines.append(f"| {name} | {s['accuracy']:.1f} | {s['acc_ci'][0]:.1f}–{s['acc_ci'][1]:.1f} | "
                     f"{s['weighted_f1']:.1f} | {s['macro_f1']:.1f} |")
    lines += ["", f"Chance is {100 / config.NUM_LABELS:.1f}% accuracy with 7 balanced classes. Median processing "
              f"time {df['total_ms'].median():.0f} ms per clip (mean duration {df['duration_s'].mean():.1f} s)."]
    if before is not None:
        before = before.set_index("file").loc[df["file"]].reset_index()
        bs = {k: own_scores(before, k) for k in ("sound", "text", "fused")}
        lines += ["", "## Before and after the fusion refit", "",
                  "**The fusion weight was changed after these recordings were first scored, and because of that "
                  f"result.** The first run ({before_label}) had the app right on {bs['fused']['accuracy']:.1f}% of "
                  f"the clips while the text branch alone got {bs['text']['accuracy']:.1f}%. The weight was then "
                  "chosen again (spec v1.4, §8.4) on MELD dev, using only the clips from speakers outside the six "
                  "main characters. These recordings weren't used to choose it, but the change came after seeing "
                  "them, so they are no longer a blind test.", "",
                  "| Output | Accuracy before | Accuracy after | Weighted-F1 before | Weighted-F1 after |",
                  "|---|---:|---:|---:|---:|"]
        for k, name in (("sound", "Sound"), ("text", "Text"), ("fused", "Fused (the app's answer)")):
            lines.append(f"| {name} | {bs[k]['accuracy']:.1f} | {sc[k]['accuracy']:.1f} | "
                         f"{bs[k]['weighted_f1']:.1f} | {sc[k]['weighted_f1']:.1f} |")
        lines += ["", "The sound and text branches don't change; only the weight that combines them does."]
    lines += ["", "| File | True | Sound | Text | Fused |" + (" Fused before |" if before is not None else "")
              + " Disagreement |", "|---|---|---|---|---|" + ("---|" if before is not None else "") + "---|"]
    for i, r in enumerate(df.itertuples()):
        mark = lambda lab, conf: (f"**{lab}**" if lab == r.label else lab) + f" {conf:.2f}" if lab else "no speech"
        was = "" if before is None else f" {mark(before['fused'].iloc[i], before['fused_conf'].iloc[i])} |"
        lines.append(f"| {r.file} | {r.label} | {mark(r.sound, r.sound_conf)} | {mark(r.text, r.text_conf)} | "
                     f"{mark(r.fused, r.fused_conf)} |{was} {'yes' if r.disagreement else ''} |")
    heard = df[df["fused"].isin(config.LABELS)]
    cm = metrics.confusion(heard["label"].map(config.LABEL_TO_ID), heard["fused"].map(config.LABEL_TO_ID))
    counts = df["label"].value_counts()
    per_emotion = str(counts.min()) if counts.min() == counts.max() else f"{counts.min()}–{counts.max()}"
    lines += ["", "Bold = correct. Fused confusion (rows true, columns predicted, order "
              f"{', '.join(config.LABELS)}):", "", "```"] + [" ".join(f"{v:2d}" for v in row) for row in cm] + ["```", "",
              "**Caveat: a small sample.** "
              f"{len(df)} clips ({per_emotion} per emotion), acted on purpose rather than spontaneous "
              "speech like MELD's. One clip moves accuracy by "
              f"{100 / len(df):.1f} points, and the bootstrap interval above is wide. These numbers show whether the "
              "system transfers to new voices at all; they don't estimate its accuracy precisely."]
    return "\n".join(lines) + "\n", sc


def own_json(df, sc, models, before=None, before_label=None):
    """results/own_recordings.json: aggregates only (no file names or transcripts)."""
    heard = df[df["fused"].isin(config.LABELS)]
    out = {"n": int(len(df)), "per_emotion": {l: int((df["label"] == l).sum()) for l in config.LABELS},
           "scores": sc, "w_sound": models["fusion_w_sound"], "median_ms": float(df["total_ms"].median()),
           "mean_duration_s": float(df["duration_s"].mean()),
           "confusion_fused": metrics.confusion(heard["label"].map(config.LABEL_TO_ID),
                                                heard["fused"].map(config.LABEL_TO_ID)),
           "before": None}
    if before is not None:
        b = before.set_index("file").loc[df["file"]].reset_index()
        out["before"] = {"label": before_label, "scores": {k: own_scores(b, k) for k in ("sound", "text", "fused")}}
    return out


def deployed_models_info():
    """The deployed system's description without loading any weights (for re-rendering)."""
    from . import sound_model, text_model

    params = json.loads(config.FUSION_PATH.read_text())
    return {"asr": f"faster-whisper {config.ASR_MODEL} {config.ASR_COMPUTE_TYPE}", "window_s": config.WINDOW_S,
            "sound": sound_model.MODEL_NAME, "text": text_model.MODEL_NAME, "fusion_w_sound": params["w_sound"]}


def main(argv=None):
    """python -m emotion_analyzer.evaluate {ensemble,parity,report,own} ..."""
    import argparse

    ap = argparse.ArgumentParser(description="Results from the saved probabilities (§10)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ensemble", help="§8.3 text-ensemble F1 test on the Kaggle dev predictions")
    pp = sub.add_parser("parity", help="§10.5 CPU int8 pass on MELD dev and the comparison")
    pp.add_argument("--limit", type=int, default=None, help="first N clips (smoke runs)")
    pp.add_argument("--out", default=str(PARITY_DIR / "cpu_dev.csv"))
    sub.add_parser("fit", help="§8.4 temperatures and weight on the deployed models' dev outputs")
    sub.add_parser("report", help="§10.2-§10.8 tables and figures from the saved predictions")
    po = sub.add_parser("own", help="§10.6 the deployed system on the own recordings")
    po.add_argument("--before", default=None,
                    help="an earlier own_eval CSV of the same clips, shown next to the new result (§10.6)")
    po.add_argument("--before-label", default="the earlier system", help="what the earlier run was")
    po.add_argument("--reuse", action="store_true",
                    help="re-render from data/own_eval.csv without running the models (and without new timings)")
    args = ap.parse_args(argv)

    if args.cmd == "ensemble":
        print(json.dumps(text_ensemble_rule(), indent=2))
        return
    from . import data, sound_model, text_model

    out = config.RESULTS_DIR
    out.mkdir(exist_ok=True)
    if args.cmd == "fit":
        p = fit_deployed(text_cpu(text_model.TextClassifier(config.text_model_dirs()), "dev"))
        fusion.save_params(config.FUSION_PATH, p.pop("t_sound"), p.pop("t_text"), p.pop("w_sound"), p)
        q = fusion.load_params(config.FUSION_PATH)
        print(f"fusion: T_sound {q['t_sound']:.3f}, T_text {q['t_text']:.3f}, w_sound {q['w_sound']}, "
              f"dev wF1 {q['dev_weighted_f1']}; fp16-text reference {q['fp16_text_reference']}")
        return
    if args.cmd == "report":
        params = fusion.load_params(config.FUSION_PATH)
        t_cpu = text_cpu(text_model.TextClassifier(config.text_model_dirs()), "test")
        rows = results_rows(params, t_cpu, parity_json=out / "parity.json")
        pd.DataFrame(rows).to_csv(out / "results_table.csv", index=False)
        gains = fusion_gains(params)
        reference = None
        if params.get("all_dev_weight_reference", params["w_sound"]) != params["w_sound"]:
            old = {**params, "w_sound": params["all_dev_weight_reference"]}
            reference = {r["row"]: r for r in results_rows(old, t_cpu) if r["row"] in ("R7", "R8", "R9")}
        (out / "results_table.md").write_text(results_table_markdown(rows, params, gains, reference),
                                              encoding="utf-8")
        write_json(out / "results_table.json", {
            "rows": rows, "gains": gains, "w_sound": params["w_sound"], "weight_fit": params.get("weight_fit"),
            "all_dev_weight_reference": params.get("all_dev_weight_reference"),
            "reference": {k: r["weighted_f1_mean"] for k, r in reference.items()} if reference else None})
        parts = deployed_test_parts(params, t_cpu)
        (out / "per_class.md").write_text(per_class_report(parts, out), encoding="utf-8")
        decision = json.loads((config.MODELS_DIR / "decision.json").read_text())
        (out / "wer.md").write_text(wer_markdown(KAGGLE_DIR / "transcripts", decision), encoding="utf-8")
        write_json(out / "wer.json", wer_json(KAGGLE_DIR / "transcripts", decision))
        cal_md, cal = calibration_report(parts, params, out)
        (out / "calibration.md").write_text(cal_md, encoding="utf-8")
        write_json(out / "calibration.json", cal)
        err_md, err = error_analysis(parts, KAGGLE_DIR / "transcripts" / f"test_{config.WINDOW_S}s.csv")
        (out / "error_analysis.md").write_text(keep_discussion(out / "error_analysis.md", err_md),
                                               encoding="utf-8")
        write_json(out / "per_class.json", {**per_class_json(parts), "disagreement": err})
        for r in rows:
            print(f"{r['row']:<3} {r['weighted_f1_mean']:6.2f} ± {r['weighted_f1_sd']:.2f}  "
                  f"[{r['ci_low']:.1f}, {r['ci_high']:.1f}]  {r['condition']}")
        print(f"fusion gains {gains}; calibration ECE {cal['ece_before']} -> {cal['ece_after']}; "
              f"disagreements {err}")
        return
    if args.cmd == "own":
        manifest, skipped = data.own_manifest()
        if skipped:
            print(f"skipped (name doesn't match emotion_nn.ext): {skipped}")
        if args.reuse:
            df, models = pd.read_csv(OWN_EVAL_CSV, keep_default_na=False), deployed_models_info()
        else:
            analyzer = fusion.load_analyzer()
            df = own_recordings_eval(analyzer, manifest, log=lambda m: print(m, flush=True))
            models = analyzer.models_info()
        before = pd.read_csv(args.before, keep_default_na=False) if args.before else None
        md, sc = own_markdown(df, models, before, args.before_label)
        (out / "own_recordings.md").write_text(md, encoding="utf-8")
        write_json(out / "own_recordings.json", own_json(df, sc, models, before, args.before_label))
        print(json.dumps(sc, indent=2))
        return

    manifest, _ = data.meld_manifest("dev")
    if args.limit:
        manifest = manifest.head(args.limit)
    pipe = speech.SpeechPipeline(window_s=config.WINDOW_S)
    sound = sound_model.SoundClassifier(config.SOUND_HEAD_PATH)
    rows = cpu_dev_pass(manifest, pipe, sound, args.out, log=lambda m: print(m, flush=True))
    del pipe
    text = text_model.TextClassifier(config.text_model_dirs())
    kt = pd.read_csv(KAGGLE_DIR / "transcripts" / f"dev_{config.WINDOW_S}s.csv", keep_default_na=False)
    p = parity(rows[rows["id"].isin(manifest["id"])], text, fusion.load_params(config.FUSION_PATH),
               *deployed_dev_files(), kaggle_transcripts=kt)
    if not args.limit:
        config.RESULTS_DIR.mkdir(exist_ok=True)
        (config.RESULTS_DIR / "parity.md").write_text(parity_markdown(p, config.WINDOW_S),
                                                      encoding="utf-8")
        (config.RESULTS_DIR / "parity.json").write_text(json.dumps(p, indent=2))
    print(json.dumps(p, indent=2))


if __name__ == "__main__":
    main()
