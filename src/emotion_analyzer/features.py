"""Batch encoder-frame extraction and fp16 sharded caching (spec §6.2, §9.3 S5).

A feature set is a folder of shards `shard_000.npy` (all frames of a group of clips,
concatenated, fp16) and `index.csv` with one row per clip: `id`, `label_id`, `shard`,
`offset`, `length`. With --parts N --part k a process handles every N-th clip and
writes into `part{k}/`; `load` reads all parts.

    python -m emotion_analyzer.features --manifest state/manifests/meld_train.csv \
        --window 10 --out /tmp/features/meld_10s/train --device cuda --compute-type float16
"""

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, speech


def manifest_ids(manifest):
    if "id" in manifest.columns:
        return manifest["id"].astype(str).tolist()
    return [Path(p).stem for p in manifest["path"]]


def extract(manifest, pipe, window_s, out_dir, shard_size=1000, log=print):
    """Write the valid frames of every clip in `manifest` as fp16 shards. Shards that
    already exist are skipped, so an interrupted run resumes."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ids = manifest_ids(manifest)
    rows = []
    t0 = time.perf_counter()
    for s, b in enumerate(range(0, len(manifest), shard_size)):
        part = manifest.iloc[b:b + shard_size]
        shard_path = out_dir / f"shard_{s:03d}.npy"
        shard_index = out_dir / f"shard_{s:03d}.csv"
        if shard_path.exists() and shard_index.exists():
            rows.append(pd.read_csv(shard_index))
            continue
        frames = []
        for c in range(0, len(part), pipe.batch_size):
            audios = [speech.decode(str(p)) for p in part["path"].iloc[c:c + pipe.batch_size]]
            frames += pipe.frames_clips(audios, window_s)
        lengths = np.array([len(f) for f in frames])
        offsets = np.concatenate([[0], np.cumsum(lengths)[:-1]])
        np.save(shard_path, np.concatenate(frames).astype(np.float16))
        idx = pd.DataFrame({"id": ids[b:b + shard_size], "label_id": part["label_id"].to_numpy(),
                            "shard": s, "offset": offsets, "length": lengths})
        idx.to_csv(shard_index, index=False)
        rows.append(idx)
        log(f"  shard {s}: {b + len(part)}/{len(manifest)} clips, {time.perf_counter() - t0:.0f} s")
    index = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    index.to_csv(out_dir / "index.csv", index=False)
    return index


def load(feature_dir, dtype=np.float16):
    """Read a feature set (all parts). Returns (index DataFrame, list of (T, d) arrays)."""
    feature_dir = Path(feature_dir)
    dirs = sorted(feature_dir.glob("part*")) or [feature_dir]
    indexes, frames = [], []
    for d in dirs:
        index = pd.read_csv(d / "index.csv")
        shards = {s: np.load(d / f"shard_{s:03d}.npy", mmap_mode="r") for s in index["shard"].unique()}
        for row in index.itertuples():
            frames.append(np.asarray(shards[row.shard][row.offset:row.offset + row.length], dtype=dtype))
        indexes.append(index)
    return pd.concat(indexes, ignore_index=True), frames


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--manifest", required=True, help="CSV with path, label_id and id")
    ap.add_argument("--window", type=int, required=True, choices=config.WINDOWS_S)
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=config.ASR_MODEL)
    ap.add_argument("--device", default=config.ASR_DEVICE)
    ap.add_argument("--compute-type", default=config.ASR_COMPUTE_TYPE)
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--shard-size", type=int, default=1000)
    ap.add_argument("--part", type=int, default=0)
    ap.add_argument("--parts", type=int, default=1)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--backend", default="ct2", choices=["ct2", "hf"],
                    help="hf = the transformers fallback (§9.2)")
    args = ap.parse_args(argv)

    manifest = pd.read_csv(args.manifest, keep_default_na=False)
    if args.limit:
        manifest = manifest.head(args.limit)
    manifest = manifest.iloc[args.part::args.parts]
    out = Path(args.out) / f"part{args.part}" if args.parts > 1 else Path(args.out)
    pipe = speech.make_pipeline(args.backend, model_size=args.model, device=args.device,
                                compute_type=args.compute_type, window_s=args.window,
                                batch_size=args.batch_size)
    t0 = time.perf_counter()
    index = extract(manifest, pipe, args.window, out, args.shard_size)
    print(f"features: {len(index)} clips, {int(index['length'].sum()) if len(index) else 0} frames, "
          f"{time.perf_counter() - t0:.0f} s -> {out}")


if __name__ == "__main__":
    main()
