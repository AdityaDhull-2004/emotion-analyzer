"""Batch transcription of MELD and WER in both windows (spec §8.1, §9.3 S3).

Writes one CSV per split and window, `{out}/{split}_{W}s.csv`, with the reference,
the Whisper hypothesis and the label, plus `{out}/wer_{split}_{W}s.json`. With
--parts N --part k it processes every N-th clip starting at k (one GPU each) and
writes `.part{k}` files; `merge_parts` joins them.

Example (local CPU, 300 dev clips):
    python -m emotion_analyzer.transcribe --split dev --windows 10 30 --limit 300 --out data/kaggle/p3

S4 (`--decide`) reads the WER files and writes `decision.json` by the §8.1 rule.
"""

import argparse
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, data, metrics, speech

COLUMNS = ["id", "dialogue_id", "utterance_id", "label", "duration_s", "reference", "hypothesis"]


def select(manifest, limit=None, seed=0, part=0, parts=1):
    df = manifest
    if limit:
        df = df.sample(n=min(limit, len(df)), random_state=seed).sort_index()
    return df.iloc[part::parts]


def transcribe_manifest(pipe, df, window_s, batch_size=16, log_every=200):
    """Transcribe every clip in df; returns a DataFrame with COLUMNS."""
    hyps = []
    t0 = time.perf_counter()
    for b in range(0, len(df), batch_size):
        audios = [speech.decode(str(p)) for p in df["path"].iloc[b:b + batch_size]]
        hyps += pipe.transcribe_clips(audios, window_s)
        if log_every and (b // batch_size) % max(1, log_every // batch_size) == 0:
            print(f"  {window_s}s window: {len(hyps)}/{len(df)} clips, "
                  f"{time.perf_counter() - t0:.0f} s", flush=True)
    return pd.DataFrame({
        "id": df["id"].to_numpy(),
        "dialogue_id": df["dialogue_id"].to_numpy(),
        "utterance_id": df["utterance_id"].to_numpy(),
        "label": df["label"].to_numpy(),
        "duration_s": df["duration_s"].to_numpy(),
        "reference": df["text"].to_numpy(),
        "hypothesis": hyps,
    }, columns=COLUMNS)


def wer_summary(df, seconds=None):
    out = metrics.wer(df["reference"].tolist(), df["hypothesis"].fillna("").tolist())
    out["empty_hypotheses"] = int((df["hypothesis"].fillna("").str.strip() == "").sum())
    if seconds is not None:
        out["seconds"] = round(seconds, 1)
        out["seconds_per_clip"] = round(seconds / max(len(df), 1), 3)
    return out


def merge_parts(out_dir, split, window_s, parts):
    """Join the .part{k} CSVs of one split and window into the final CSV and WER."""
    out_dir = Path(out_dir)
    frames = [pd.read_csv(out_dir / f"{split}_{window_s}s.part{k}.csv", keep_default_na=False)
              for k in range(parts)]
    df = pd.concat(frames).sort_values(["dialogue_id", "utterance_id"]).reset_index(drop=True)
    df.to_csv(out_dir / f"{split}_{window_s}s.csv", index=False)
    summary = wer_summary(df)
    (out_dir / f"wer_{split}_{window_s}s.json").write_text(json.dumps(summary, indent=2))
    return df, summary


def decide_window(transcripts_dir, case=config.WINDOW_CASE, max_gap=config.WER_RULE_MAX_GAP):
    """S4 (§8.1). Case "a": 10 s if WER(10 s) - WER(30 s) <= max_gap on dev, else 30 s.
    Case "b": the window stays 10 s and the WER cost is recorded for dev and test."""
    tdir = Path(transcripts_dir)
    wer = {}
    for split in ("dev", "test"):
        for w in config.WINDOWS_S:
            f = tdir / f"wer_{split}_{w}s.json"
            if f.exists():
                wer[f"{split}_{w}s"] = round(json.loads(f.read_text())["wer"], 2)
    gaps = {split: round(wer[f"{split}_10s"] - wer[f"{split}_30s"], 2) for split in ("dev", "test")
            if f"{split}_10s" in wer and f"{split}_30s" in wer}
    if "dev" not in gaps:
        raise FileNotFoundError(f"S4 needs wer_dev_10s.json and wer_dev_30s.json in {tdir}; run S3 first")
    if case == "a":
        window = 10 if gaps["dev"] <= max_gap else 30
        rule = f"case a: dev WER gap <= {max_gap} -> 10 s, else 30 s"
    elif case == "b":
        window, rule = 10, "case b: 10 s fixed by latency; WER cost recorded"
    else:
        raise ValueError(f"window case must be 'a' or 'b' at S4, not {case!r}")
    decision = {"case": case, "window_s": window, "rule": rule, "asr_model": config.ASR_MODEL,
                "wer": wer, "wer_gap_10s_minus_30s": gaps}
    (tdir / "decision.json").write_text(json.dumps(decision, indent=2))
    return decision


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--split", choices=data.MELD_SPLITS)
    ap.add_argument("--manifest", default=None, help="S2 manifest CSV instead of reading MELD")
    ap.add_argument("--meld-root", default=str(config.MELD_DIR))
    ap.add_argument("--windows", type=int, nargs="+", default=list(config.WINDOWS_S))
    ap.add_argument("--out", default=str(config.KAGGLE_OUT_DIR / "transcripts"))
    ap.add_argument("--model", default=config.ASR_MODEL)
    ap.add_argument("--device", default=config.ASR_DEVICE)
    ap.add_argument("--compute-type", default=config.ASR_COMPUTE_TYPE)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--limit", type=int, default=None, help="random sample of this many clips")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--parts", type=int, default=1)
    ap.add_argument("--no-count-check", action="store_true")
    ap.add_argument("--backend", default="ct2", choices=["ct2", "hf"],
                    help="hf = the transformers fallback (§9.2)")
    ap.add_argument("--merge", action="store_true",
                    help="join the --parts outputs of an earlier run instead of transcribing")
    ap.add_argument("--decide", action="store_true", help="S4: write decision.json from the WER files")
    ap.add_argument("--case", default=config.WINDOW_CASE, help="the Phase 3 window case")
    args = ap.parse_args(argv)

    if args.decide:
        d = decide_window(args.out, args.case)
        print(f"S4: window {d['window_s']} s ({d['rule']}); WER gap {d['wer_gap_10s_minus_30s']}")
        return
    if not args.split:
        ap.error("--split is required")

    if args.merge:
        for w in args.windows:
            _, summary = merge_parts(args.out, args.split, w, args.parts)
            print(f"{args.split} {w}s: WER {summary['wer']:.2f}% on {summary['n']} clips (merged)")
        return

    if args.manifest:
        manifest = pd.read_csv(args.manifest, keep_default_na=False)
    else:
        manifest, _ = data.meld_manifest(args.split, root=args.meld_root,
                                         check_counts=not args.no_count_check)
    df = select(manifest, args.limit, args.seed, args.part, args.parts)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    suffix = f".part{args.part}" if args.parts > 1 else ""

    pipe = speech.make_pipeline(args.backend, model_size=args.model, device=args.device,
                                compute_type=args.compute_type, window_s=args.windows[0],
                                batch_size=args.batch_size)
    for w in args.windows:
        csv_path = out / f"{args.split}_{w}s{suffix}.csv"
        if csv_path.exists() and len(pd.read_csv(csv_path)) == len(df):
            print(f"{csv_path.name}: already done, skipped")
            continue
        t0 = time.perf_counter()
        res = transcribe_manifest(pipe, df, w, args.batch_size)
        seconds = time.perf_counter() - t0
        res.to_csv(csv_path, index=False)
        summary = wer_summary(res, seconds)
        if not suffix:
            (out / f"wer_{args.split}_{w}s.json").write_text(json.dumps(summary, indent=2))
        print(f"{args.split} {w}s: WER {summary['wer']:.2f}% on {len(res)} clips, "
              f"{summary['seconds_per_clip']} s/clip")


if __name__ == "__main__":
    main()
