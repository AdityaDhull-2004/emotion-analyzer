"""Build the Kaggle upload in kaggle/code/ (spec §9.1, §13).

    .venv\\Scripts\\python.exe scripts\\package_kaggle.py              build kaggle/code/
    .venv\\Scripts\\python.exe scripts\\package_kaggle.py --dry-run    rehearse the cells locally (P5)

Writes
  kaggle/code/emotion-analyzer-code/      the dataset tree: emotion_analyzer/, requirements-kaggle.txt,
                                          CODE_VERSION.json
  kaggle/code/emotion-analyzer-code.zip   the same tree zipped; upload it as the private dataset
                                          `emotion-analyzer-code` (Kaggle unpacks it)
  kaggle/code/emotion-analyzer-train.ipynb  the cells from KAGGLE.md as a notebook (File > Import)
  kaggle/code/cells/C.py, S0.py ... S8.py the same cells as plain files (used by the local dry-run)

The cells are taken from KAGGLE.md: each `### Cell <ID>` heading is followed by one
```python block, which is the cell.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "kaggle" / "code"
DATASET = "emotion-analyzer-code"
CELL_RE = re.compile(r"^### Cell (\w+)[^\n]*\n(?:(?!^### ).)*?^```python\n(.*?)^```", re.M | re.S)
CELL_ORDER = ["C", "S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"]


def read_cells(kaggle_md=ROOT / "KAGGLE.md"):
    cells = {m.group(1): m.group(2) for m in CELL_RE.finditer(kaggle_md.read_text(encoding="utf-8"))}
    missing = [c for c in CELL_ORDER if c not in cells]
    if missing:
        raise SystemExit(f"KAGGLE.md is missing cells {missing}")
    return [(c, cells[c]) for c in CELL_ORDER]


def notebook(cells):
    def code(src):
        return {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [],
                "source": src.splitlines(keepends=True)}

    head = {"cell_type": "markdown", "metadata": {},
            "source": ["# emotion-analyzer-train\n",
                       "Cells from KAGGLE.md. Pass 1: run only C and S0. Pass 2: Save Version > "
                       "Save & Run All (Commit).\n"]}
    return {"cells": [head] + [code(src) for _, src in cells],
            "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python",
                                        "name": "python3"},
                         "language_info": {"name": "python"}},
            "nbformat": 4, "nbformat_minor": 5}


def git_commit():
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain", "src", "requirements-kaggle.txt"],
                               cwd=ROOT, capture_output=True, text=True).stdout.strip()
        return out + ("+uncommitted" if dirty else "")
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def build(out=OUT):
    tree = out / DATASET
    if out.exists():
        shutil.rmtree(out)
    pkg = tree / "emotion_analyzer"
    pkg.mkdir(parents=True)
    files = {}
    for src in sorted((ROOT / "src" / "emotion_analyzer").glob("*.py")):
        shutil.copy2(src, pkg / src.name)
        files[f"emotion_analyzer/{src.name}"] = hashlib.sha256(src.read_bytes()).hexdigest()[:12]
    shutil.copy2(ROOT / "requirements-kaggle.txt", tree / "requirements-kaggle.txt")
    version = re.search(r'^VERSION = "([^"]+)"', (ROOT / "src" / "emotion_analyzer" / "config.py")
                        .read_text(encoding="utf-8"), re.M).group(1)
    (tree / "CODE_VERSION.json").write_text(json.dumps(
        {"version": version, "git": git_commit(), "files": files}, indent=2))

    zpath = out / f"{DATASET}.zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for f in sorted(tree.rglob("*")):
            if f.is_file():
                z.write(f, f.relative_to(tree).as_posix())

    cells = read_cells()
    (out / "cells").mkdir()
    for cid, src in cells:
        (out / "cells" / f"{cid}.py").write_text(src, encoding="utf-8")
    (out / "emotion-analyzer-train.ipynb").write_text(json.dumps(notebook(cells), indent=1),
                                                      encoding="utf-8")
    print(f"package: {len(files)} modules, {zpath.stat().st_size / 1e3:.0f} kB zip, "
          f"{len(cells)} cells -> {out}")
    return out


# Executes the cell files in order in one namespace, as a notebook kernel would.
RUNNER = """import sys, time
from pathlib import Path
ns = {"__name__": "__main__"}
for cid in sys.argv[2:]:
    t = time.time()
    print(f"===== cell {cid} =====", flush=True)
    exec(compile((Path(sys.argv[1]) / f"{cid}.py").read_text(encoding="utf-8"), f"cell {cid}", "exec"), ns)
    print(f"===== cell {cid} done in {time.time() - t:.0f} s =====", flush=True)
"""


def fake_acted_inputs(inp, n=7):
    """Stand-ins for ejlok1/cremad and the RAVDESS input (with its duplicated tree), made from
    local MELD dev clips under the scratch folder only (never committed, never shipped)."""
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    sys.path.insert(0, str(ROOT / "src"))
    from emotion_analyzer import data

    dev, _ = data.meld_manifest("dev")
    paths = dev[(dev.duration_s > 1) & (dev.duration_s < 6)]["path"].tolist()[:2 * n]
    crema = inp / "cremad" / "AudioWAV"
    crema.mkdir(parents=True)
    emos = ["ANG", "DIS", "FEA", "HAP", "NEU", "SAD"]
    for i, path in enumerate(paths[:n]):
        audio, sr = sf.read(path, dtype="float32")
        sf.write(crema / f"10{i:02d}_DFA_{emos[i % 6]}_XX.wav", audio, sr)
    rav = inp / "ravdess-emotional-speech-audio"
    for tree in (rav, rav / "audio_speech_actors_01-24"):
        (tree / "Actor_01").mkdir(parents=True, exist_ok=True)
        for i, path in enumerate(paths[n:]):
            audio, sr = sf.read(path, dtype="float32")
            sf.write(tree / "Actor_01" / f"03-01-0{i % 8 + 1}-01-01-01-01.wav",
                     resample_poly(audio, 3, 1).astype(np.float32), 48000)


def run_cells(cells_dir, env, log):
    with open(log, "w", encoding="utf-8") as f:
        p = subprocess.run([sys.executable, "-c", RUNNER, str(cells_dir), *CELL_ORDER], env=env,
                           stdout=f, stderr=subprocess.STDOUT)
    text = Path(log).read_text(encoding="utf-8", errors="replace")
    if p.returncode:
        print(text[-6000:])
        raise SystemExit(f"dry-run failed (exit {p.returncode}); full log: {log}")
    return text


def dry_run(scratch=None, limit=12):
    """Phase 5 rehearsal: every cell on CPU on a tiny subset, then a resumed session."""
    scratch = Path(scratch or tempfile.mkdtemp(prefix="ea_dryrun_"))
    if scratch.exists():
        shutil.rmtree(scratch)
    t0 = time.time()
    pkg = build(scratch / "package")
    inp = scratch / "input"
    shutil.copytree(pkg / DATASET, inp / DATASET)
    fake_acted_inputs(inp)
    env = dict(os.environ, EA_DRY_RUN="1", EA_LIMIT=str(limit), EA_INPUT=str(inp),
               EA_WORK=str(scratch / "working"), EA_TMP=str(scratch / "tmp"), PYTHONWARNINGS="ignore")
    first = run_cells(pkg / "cells", env, scratch / "run1.log")
    zpath = scratch / "working" / "emotion_outputs.zip"
    with zipfile.ZipFile(zpath) as z:
        names = z.namelist()
    need = ["metrics.json", "logs/final_results.txt", "models/sound_head.pt", "models/decision.json",
            "models/text_model_seed0/model.safetensors", "transcripts/wer_dev_10s.json"]
    missing = [n for n in need if n not in names]
    if missing:
        raise SystemExit(f"dry-run: the zip lacks {missing}")
    print(f"run 1: {len(names)} files in the zip, {zpath.stat().st_size / 1e6:.0f} MB, "
          f"{time.time() - t0:.0f} s")

    # A fresh session with the first run's output attached as an input: finished stages are reused.
    shutil.copytree(scratch / "working", inp / "emotion-analyzer-train",
                    ignore=shutil.ignore_patterns("emotion_outputs.zip"))
    env2 = dict(env, EA_WORK=str(scratch / "working2"), EA_TMP=str(scratch / "tmp2"))
    t1 = time.time()
    second = run_cells(pkg / "cells", env2, scratch / "run2.log")
    reused = re.findall(r"\] (S\d\w*): reused from", second)
    expected = len(re.findall(r"^\[S[367] .*(?:finished in|WER)", first, re.M)) + 1   # + S4
    s5_reran = list((scratch / "working2" / "logs").glob("S5_*"))
    print(f"run 2 (resumed): {len(reused)} stages reused ({', '.join(reused)}), expected {expected}; "
          f"{time.time() - t1:.0f} s")
    if len(reused) != expected or s5_reran:
        raise SystemExit("dry-run: the resumed session did not reuse every finished stage "
                         f"(S5 reran: {bool(s5_reran)})")
    block = (scratch / "working2" / "logs" / "final_results.txt").read_text()
    print(block)
    print(f"dry-run passed in {time.time() - t0:.0f} s; logs in {scratch}")
    return scratch


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Build kaggle/code/, or rehearse the cells locally")
    ap.add_argument("out", nargs="?", default=str(OUT))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--scratch", default=None, help="dry-run folder (default: a new temp folder)")
    ap.add_argument("--limit", type=int, default=12, help="dry-run clips per split")
    args = ap.parse_args()
    if args.dry_run:
        dry_run(args.scratch, args.limit)
    else:
        build(Path(args.out))
