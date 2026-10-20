"""Datasets (spec §7): MELD manifests and the CSV join with defect handling, CREMA-D and
RAVDESS loaders with label maps, and the user's own recordings.

Every loader returns a pandas DataFrame manifest with at least the columns
`id`, `path`, `label`, `label_id`, `speaker` and `source`. MELD adds `text`, `split`,
`dialogue_id`, `utterance_id` and `duration_s`.

MELD layout, the same locally and on Kaggle: `{root}/{split}/{split}.csv` next to
`{root}/{split}/dia{Dialogue_ID}_utt{Utterance_ID}.flac`.
"""

import re
from pathlib import Path

import ftfy
import numpy as np
import pandas as pd
import soundfile as sf

from . import config

MELD_SPLITS = ("train", "dev", "test")
# Pairs left after the inner join (§7.1); the loader asserts them (AC-01).
MELD_EXPECTED_PAIRS = {"train": 9988, "dev": 1108, "test": 2610}
# CSV rows whose audio is absent in the release (§7.1).
MELD_KNOWN_MISSING = {"train": {(125, 3)}, "dev": {(110, 7)}, "test": set()}
MIN_CLIP_S = 0.1

MELD_FILE_RE = re.compile(r"^dia(\d+)_utt(\d+)\.flac$")
CREMA_FILE_RE = re.compile(r"^(\d{4})_([A-Z]{3})_([A-Z]{3})_([A-Z]{2})\.wav$")
RAVDESS_FILE_RE = re.compile(r"^(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})-(\d{2})\.wav$")
OWN_FILE_RE = re.compile(r"^([a-z]+)_(\d+)\.(wav|m4a|mp3|webm)$", re.IGNORECASE)

# Label maps onto the 7 classes (§7.2). CREMA-D has no surprise.
CREMA_MAP = {"ANG": "anger", "DIS": "disgust", "FEA": "fear", "HAP": "joy",
             "NEU": "neutral", "SAD": "sadness"}
RAVDESS_MAP = {"01": "neutral", "02": "neutral", "03": "joy", "04": "sadness",
               "05": "anger", "06": "fear", "07": "disgust", "08": "surprise"}


def clean_text(text):
    """Repair encoding artefacts such as 'â€™' with ftfy, then strip whitespace."""
    if not isinstance(text, str):
        return ""
    return ftfy.fix_text(text).strip()


def audio_duration(path):
    """Duration in seconds from the file header, or None if the file can't be read."""
    try:
        info = sf.info(str(path))
    except Exception:
        return None
    if info.samplerate <= 0:
        return None
    return info.frames / info.samplerate


def _with_label_ids(df):
    df["label_id"] = df["label"].map(config.LABEL_TO_ID).astype(int)
    return df


def _check_durations(df, dropped):
    """Drop unreadable clips and clips shorter than MIN_CLIP_S, recording why."""
    durations = [audio_duration(p) for p in df["path"]]
    df = df.assign(duration_s=durations)
    bad = df["duration_s"].isna() | (df["duration_s"] < MIN_CLIP_S)
    for row in df[bad].itertuples():
        reason = "unreadable" if pd.isna(row.duration_s) else f"shorter than {MIN_CLIP_S} s"
        dropped.append({"path": str(row.path), "reason": reason})
    return df[~bad].reset_index(drop=True)


def read_meld_csv(csv_path):
    df = pd.read_csv(csv_path, encoding="utf-8", keep_default_na=False)
    expected = ["Sr No.", "Utterance", "Speaker", "Emotion", "Sentiment", "Dialogue_ID",
                "Utterance_ID", "Season", "Episode", "StartTime", "EndTime"]
    missing = [c for c in expected if c not in df.columns]
    if missing:
        raise ValueError(f"{csv_path}: missing columns {missing}")
    unknown = set(df["Emotion"]) - set(config.LABELS)
    if unknown:
        raise ValueError(f"{csv_path}: unknown emotion labels {sorted(unknown)}")
    return df


def meld_manifest(split, root=None, check_counts=True, check_audio=True):
    """Join a MELD split's CSV to its audio files on (Dialogue_ID, Utterance_ID).

    Returns (manifest, dropped). The join count is asserted against §7.1 when
    check_counts is true. With check_audio, unreadable clips and clips under
    0.1 s are dropped after the assertion and listed in `dropped`, so the caller
    can log them in issues.md.
    """
    if split not in MELD_SPLITS:
        raise ValueError(f"unknown MELD split {split!r}")
    split_dir = Path(root or config.MELD_DIR) / split
    csv = read_meld_csv(split_dir / f"{split}.csv")

    files = {}
    for p in split_dir.glob("*.flac"):
        m = MELD_FILE_RE.match(p.name)
        if m:
            files[(int(m.group(1)), int(m.group(2)))] = p

    csv["key"] = list(zip(csv["Dialogue_ID"].astype(int), csv["Utterance_ID"].astype(int)))
    if csv["key"].duplicated().any():
        raise ValueError(f"{split}: duplicate (Dialogue_ID, Utterance_ID) rows in the CSV")
    joined = csv[csv["key"].isin(files.keys())].copy()

    dropped = []
    for key in sorted(set(csv["key"]) - files.keys()):
        known = key in MELD_KNOWN_MISSING[split]
        dropped.append({"path": f"{split}/dia{key[0]}_utt{key[1]}.flac",
                        "reason": "audio absent (known defect)" if known else "audio absent"})

    if check_counts and len(joined) != MELD_EXPECTED_PAIRS[split]:
        raise AssertionError(
            f"MELD {split}: {len(joined)} audio-label pairs, expected "
            f"{MELD_EXPECTED_PAIRS[split]} (§7.1). Check the download and extraction.")

    df = pd.DataFrame({
        "id": [f"{split}_dia{d}_utt{u}" for d, u in joined["key"]],
        "path": [files[k] for k in joined["key"]],
        "label": joined["Emotion"].to_numpy(),
        "text": [clean_text(t) for t in joined["Utterance"]],
        "speaker": joined["Speaker"].to_numpy(),
        "split": split,
        "dialogue_id": joined["Dialogue_ID"].astype(int).to_numpy(),
        "utterance_id": joined["Utterance_ID"].astype(int).to_numpy(),
        "source": "meld",
    })
    df = _with_label_ids(df)
    if check_audio:
        df = _check_durations(df, dropped)
    return df, dropped


def cremad_manifest(root, check_audio=True):
    """CREMA-D clips from `{root}/**/ActorID_Sentence_EMO_Level.wav` (§7.2)."""
    rows, dropped = [], []
    for p in sorted(Path(root).rglob("*.wav")):
        m = CREMA_FILE_RE.match(p.name)
        if not m:
            continue
        actor, _sentence, emo, _level = m.groups()
        if emo not in CREMA_MAP:
            dropped.append({"path": str(p), "reason": f"unmapped emotion {emo}"})
            continue
        rows.append({"id": p.stem, "path": p, "label": CREMA_MAP[emo], "speaker": f"cremad_{actor}",
                     "source": "cremad"})
    df = _with_label_ids(pd.DataFrame(rows, columns=["id", "path", "label", "speaker", "source"]))
    if check_audio:
        df = _check_durations(df, dropped)
    return df, dropped


def ravdess_manifest(root, check_audio=True):
    """RAVDESS speech clips (§7.2). The Kaggle copy holds the folder tree twice, so
    files are de-duplicated by name and only the first copy (sorted path) is kept."""
    rows, dropped, seen = [], [], set()
    for p in sorted(Path(root).rglob("*.wav")):
        m = RAVDESS_FILE_RE.match(p.name)
        if not m or p.name in seen:
            continue
        modality, channel, emotion, _intensity, _statement, _rep, actor = m.groups()
        if modality != "03" or channel != "01":  # audio-only speech
            continue
        seen.add(p.name)
        rows.append({"id": p.stem, "path": p, "label": RAVDESS_MAP[emotion], "speaker": f"ravdess_{actor}",
                     "source": "ravdess"})
    df = _with_label_ids(pd.DataFrame(rows, columns=["id", "path", "label", "speaker", "source"]))
    if check_audio:
        df = _check_durations(df, dropped)
    return df, dropped


def resample_corpus(manifest, out_dir):
    """Decode every clip to 16 kHz mono float32 and write it as 16-bit WAV under
    out_dir, keeping file names. Returns a copy of the manifest pointing at the copies."""
    from faster_whisper import decode_audio

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    new_paths = []
    for p in manifest["path"]:
        target = out_dir / Path(p).name
        if not target.exists():
            audio = decode_audio(str(p), sampling_rate=config.SAMPLE_RATE)
            sf.write(str(target), audio, config.SAMPLE_RATE, subtype="PCM_16")
        new_paths.append(target)
    return manifest.assign(path=new_paths)


def own_manifest(root=None):
    """The user's recordings in `data/own/{emotion}_{nn}.{wav|m4a|mp3|webm}` (§7.3).
    Returns (manifest, skipped) where skipped lists files that don't fit the pattern."""
    root = Path(root or config.OWN_DIR)
    rows, skipped = [], []
    if root.exists():
        for p in sorted(root.iterdir()):
            if not p.is_file():
                continue
            m = OWN_FILE_RE.match(p.name)
            if not m or m.group(1).lower() not in config.LABEL_TO_ID:
                skipped.append(p.name)
                continue
            rows.append({"id": p.stem, "path": p, "label": m.group(1).lower(), "speaker": "own",
                         "source": "own"})
    df = _with_label_ids(pd.DataFrame(rows, columns=["id", "path", "label", "speaker", "source"]))
    return df, skipped


def download_meld_meta(dest=None):
    """MELD's train, dev and test CSVs (utterance text, speakers, labels; no audio) from the
    mirror into data/meld/meta/ (§7.4)."""
    from huggingface_hub import hf_hub_download

    dest = Path(dest or config.MELD_META_DIR)
    return [Path(hf_hub_download(config.MELD_MIRROR, f"{split}.csv", repo_type="dataset", local_dir=dest))
            for split in MELD_SPLITS]


def meld_speakers(split, meta_dir=None):
    """Speaker name per clip id for one MELD split (§8.4). The names are characters, so a
    generic one such as "Woman" pools several actors."""
    df = read_meld_csv(Path(meta_dir or config.MELD_META_DIR) / f"{split}.csv")
    ids = [f"{split}_dia{d}_utt{u}" for d, u in zip(df["Dialogue_ID"], df["Utterance_ID"])]
    return pd.Series(df["Speaker"].astype(str).str.strip().to_numpy(), index=ids, name="speaker")


def class_table(df):
    """Counts per label in the fixed label order."""
    counts = df["label"].value_counts()
    return pd.Series([int(counts.get(l, 0)) for l in config.LABELS], index=config.LABELS)


def class_weights(labels, num_labels=config.NUM_LABELS):
    """w_c = sqrt(N / (K * n_c)), normalised to a mean of 1 (§8.2)."""
    labels = np.asarray(labels)
    counts = np.bincount(labels, minlength=num_labels).astype(float)
    w = np.sqrt(len(labels) / (num_labels * np.maximum(counts, 1.0)))
    return w / w.mean()
