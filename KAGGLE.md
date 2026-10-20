# Training on Kaggle

How the models are trained (spec §9). Everything runs in one private Kaggle notebook, `emotion-analyzer-train`, on two T4 GPUs. The notebook has **10 cells, numbered 1 to 10**. Each cell's heading also names its pipeline stage (S0–S8), the names used in the spec, the logs and the progress messages.

| Cell | Stage | What it does |
|---:|---|---|
| 1 | settings | Settings and helper functions |
| 2 | S0 | Environment check, installs, quick benchmark; writes `s0_check.txt` |
| 3 | S1 | Downloads MELD's audio from Hugging Face |
| 4 | S2 | Builds the data tables (manifests) for MELD, CREMA-D and RAVDESS |
| 5 | S3 | Transcribes every MELD clip in both Whisper windows |
| 6 | S4 | Chooses the window |
| 7 | S5 | Extracts the sound features |
| 8 | S6 | Trains the sound models |
| 9 | S7 | Trains the text models |
| 10 | S8 | Exports everything into `emotion_outputs.zip` |

The run has **two passes**:
- **Pass 1, interactive, about 10 minutes:** cells 1 and 2 only.
- **Pass 2, a background commit, about 2 hours:** all 10 cells, unattended.

**Budget:** about 3.2 GPU-hours and 2 h wall-clock (table below). The cap is 6 GPU-hours, well inside the 12-hour limit for a commit and the weekly quota. S0 re-measures these numbers on the real hardware.

| Stage | Arithmetic (§9.4) | GPU-hours | Wall-clock |
|---|---|---:|---:|
| S0 (pass 1 and again in pass 2) | installs and a 1-minute benchmark | 0.2 | 8 min |
| S1, S2 | download, manifests | 0.15 | 8 min |
| S3 | 13,706 clips × (≈0.15 s at 30 s + ≈0.08 s at 10 s) | 0.9 | 26 min on 2 GPUs |
| S4 | WER rule | 0 | seconds |
| S5 | (13,706 + 7,442 + 1,440) clips × ≈0.04 s, plus MELD in the other window | 0.4 | 12 min on 2 GPUs |
| S6 | 9 sound runs × ≈3 min | 0.45 | 14 min, 2 at a time |
| S7 | 6 text runs × ≈10 min | 1.0 | 30 min, 2 at a time |
| S8 | export and zip | 0.15 | 3 min |
| **Total** | | **≈3.2** | **≈2 h** |

## 1. Steps in order

**Getting ready, once:**

1. **Phone-verify your Kaggle account.** On kaggle.com, go to **Settings → Phone verification**. GPUs and Internet access need it.
2. **Build the upload on the laptop.** This is already done after the last code change; run it again only if the code changes:

   ```
   E:\AIDS\Project\emotion-analyzer
   .venv\Scripts\python.exe scripts\package_kaggle.py
   ```

   It writes `kaggle\code\` (git-ignored):
   - `emotion-analyzer-code.zip`, the code dataset;
   - `emotion-analyzer-train.ipynb`, the 10 cells as a notebook;
   - `cells\1.py` … `cells\10.py`, the same cells as plain files.

**Setting up the notebook:**

3. **Upload the code as a dataset.** kaggle.com → **Create** → **New Dataset**. Drop in `E:\AIDS\Project\emotion-analyzer\kaggle\code\emotion-analyzer-code.zip` (Kaggle unpacks it). Title it **emotion-analyzer-code**, leave it **Private**, and choose **Create**. After a code change, upload a **New Version** of this dataset instead.
4. **Create the notebook.** **Create** → **New Notebook**. Rename it **emotion-analyzer-train**, and keep it **Private**.
5. **Import the cells.** **File** → **Import Notebook** → choose `E:\AIDS\Project\emotion-analyzer\kaggle\code\emotion-analyzer-train.ipynb`. You get cells 1–10, each under its heading. Alternatively, paste cells 1–10 from section 4 below, one Kaggle cell each, in order.
6. **Add the three inputs.** In the right-hand panel, choose **Add Input** and add:
   - `emotion-analyzer-code` (under **Your Datasets**);
   - `ejlok1/cremad`;
   - `uwrfkaggler/ravdess-emotional-speech-audio`.
7. **Settings.** In the right-hand panel, set **Accelerator → GPU T4 ×2** and **Internet → On**. Persistence isn't needed.

**Pass 1, the interactive check (about 10 minutes):**

8. **Run cell 1.** It takes seconds. Expected output: one line, `[C  0.0 min] code /kaggle/input/…/emotion-analyzer-code; 2 GPU(s), device cuda; work /kaggle/working; dry_run=False`.
9. **Run cell 2** (stage S0). It takes about 6–8 minutes: it installs the packages, downloads 32 MELD dev clips, transcribes them on the GPU in a subprocess, extracts features and benchmarks training. It prints a report ending with `verdict: GO`, and saves it as `s0_check.txt`.

   What `s0_check.txt` looks like (your numbers will differ):
   
   ```
   S0 check 2026-10-21 09:12 | code 1.0.0 (abc1234) | Python 3.11.11 | dry_run=False
   GPUs: 0, Tesla T4, 15360 MiB, 550.90.07 | 1, Tesla T4, 15360 MiB, 550.90.07
   RAM 32 GB | free disk: /kaggle/working 19 GB, /tmp 60 GB
   preinstalled: torch 2.x, transformers 4.x, scikit-learn 1.x, pandas 2.x, numpy 1.x
   installed: faster-whisper 1.2.1, ctranslate2 4.8.3, transformers 5.20.2, ...
   LD_LIBRARY_PATH for the GPU subprocesses: 2+ nvidia lib folders (cublas, cudnn, ...)
   MELD sample: 32 dev clips downloaded and extracted in 9 s
   CUDA subprocess test: OK, backend ct2 on GPU
   measured: transcribe 0.080 / 0.150 s per clip (10 s / 30 s window); features 0.030 / 0.040 s per clip; sound step 0.015 s; text step 0.120 s
   re-estimate (GPU-hours / wall-clock hours on 2 GPUs):
     S3         0.88 /  0.44
     ...
     total      3.1  /  1.9   (budget 6 GPU-hours, commit limit 12 h, guard 11 h)
   verdict: GO
   ```

   **If the CUDA test fails:** S0 tries the transformers fallback by itself (same weights, §9.2) and reports `backend hf`. The run then continues with the fallback, and the Phase 6 parity check covers the change of implementation. If both backends fail, S0 stops with an error naming the log file under `/kaggle/working/logs/`.
10. **Download the report.** In the right-hand panel, open **Output** (`/kaggle/working`) and download **`s0_check.txt`** into `C:\Users\adity\Downloads`. Then say so in the session. Claude checks that the CUDA subprocess test passed, that there's enough free disk, and that the re-estimated total fits the budget. **Wait for the go-ahead.**
11. **Don't run cells 3–10 in the editor.** An interactive session stops after about 60 minutes idle, and the full run takes about 2 hours.

**Pass 2, the background commit (about 2 hours):**

12. **Commit.** Top right → **Save Version** → **Save & Run All (Commit)** → **Save**. Kaggle starts a clean session and runs cells 1–10 from top to bottom. You can close the browser; a commit has no idle timeout.
13. **Watch progress (optional).** Use **View Active Events**, or open the running version's log. Every stage prints one-line status messages such as `[S3  41.2 min] dev: WER ...`; long subprocess logs go to `/kaggle/working/logs/`. Cell 10 ends with the **final results block**, which is also saved as `logs/final_results.txt` inside the zip.
14. **Download the results.** When the version has finished, open it (**View Versions** → the commit) → **Output**, and download **`emotion_outputs.zip`** (about 0.8 GB) into `C:\Users\adity\Downloads`. Then say so in the session. Phase 6 moves it into the git-ignored `data/kaggle/`. If the browser download fails, use the Kaggle CLI, with your API token in `%USERPROFILE%\.kaggle\kaggle.json`:

    ```
    C:\Users\adity\Downloads
    kaggle kernels output <your-username>/emotion-analyzer-train -p C:\Users\adity\Downloads
    ```

**Safety:** no new training run starts after 11 hours (`GUARD_HOURS` in cell 1), so the commit ends before Kaggle's 12-hour limit. Runs that were skipped or failed are listed in the final results block, under `skipped`.

## 2. If something goes wrong

**The commit fails part-way: resume.**

Every stage writes a marker into `/kaggle/working/state/`:
- `S3_{split}.done` and `S4.done`;
- `S6_{run}_seed{k}.done` and `S7_{run}_seed{k}.done`, one per training run.

At start-up, a stage looks for its marker both in `/kaggle/working/state/` and in the `state/` folder of **any** attached input (§9.3, F8). It copies the finished results from there and skips the work.

To resume:
1. Fix the cause if it's in the code: rebuild the package (step 2) and upload a **New Version** of the dataset (step 3).
2. In the notebook editor: **Add Input** → **Notebooks** → `emotion-analyzer-train`, and pick the failed version. Its output mounts under `/kaggle/input/<name>/`, and the code searches every input, whatever the folder is called.
3. **Save & Run All (Commit)** again. Finished transcripts and training runs are reused.
   - Features (S5) are recomputed, because they live in `/tmp` and are cheap.
   - S5 is skipped entirely if every sound run is already finished.

**Alternative:** download the failed version's output, upload it as a new private dataset, and attach that instead. The search finds its `state/` folder the same way.

**MELD fallback:** if S1 can't download from Hugging Face, it stops with a message. Then attach the Kaggle dataset `ngocson2002/meld-datasetv2` with Add Input and commit again; S1 links the audio from there.

**A cell's log is empty, or a subprocess dies silently:** that usually means it ran out of memory. Lower `BATCH` in cell 1's settings, then commit again; the finished stages are reused.

## 3. What the zip holds

From §9.5:
- `models/`: `sound_head.pt` and `sound_head.json` (the main seed with the best dev weighted-F1), `text_model_seed{0,1,2}/` (fp16 safetensors plus the tokenizer), and `decision.json`.
- `predictions/`: dev and test probabilities for every run, named `{sound|text}_{run}_seed{k}_{split}[_{real|whisper}].npz`.
- `transcripts/`: per-utterance transcripts, WER and `decision.json`. These stay out of git (F3).
- `metrics.json`.
- `logs/`: `final_results.txt`, `s0_check.txt`, `class_tables.csv`, the training histories and every subprocess log.

## 4. The cells

Each cell is complete. They are numbered in the order they run. Only the settings block at the top of cell 1 is meant to be edited.

### Cell 1 — settings and helpers

Runs in seconds. **Expected output:** one line, `[C  0.0 min] code /kaggle/input/emotion-analyzer-code; 2 GPU(s), device cuda; work /kaggle/working; dry_run=False`.

```python
# Cell 1 - settings and helpers (spec §9). Edit only the settings block.
import glob, json, os, re, shutil, subprocess, sys, time
from pathlib import Path

# ---- settings ------------------------------------------------------------------
WINDOW_CASE = "a"        # Phase 3 result (§8.1): "a" = S4 picks the window by WER; "b" = 10 s fixed
SEEDS = [0, 1, 2]
RUN_ABLATIONS = True     # sound A (+ acted corpora) and W (other window), text T (real transcripts only)
GUARD_HOURS = 11.0       # no new training run starts after this many hours (§9.3)
SOUND_MAX_EPOCHS = 40
TEXT_EPOCHS = 6
LIMIT = None             # clips per MELD split; None = all (the local dry-run uses a few)
# ---------------------------------------------------------------------------------

T0 = time.time()
DRY_RUN = os.environ.get("EA_DRY_RUN") == "1"     # local CPU rehearsal (Phase 5), never on Kaggle
if DRY_RUN:
    SEEDS, SOUND_MAX_EPOCHS, TEXT_EPOCHS = [0, 1], 3, 1
    LIMIT = int(os.environ.get("EA_LIMIT", "12"))
INPUT = Path(os.environ.get("EA_INPUT", "/kaggle/input"))
WORK = Path(os.environ.get("EA_WORK", "/kaggle/working"))
TMP = Path(os.environ.get("EA_TMP", "/tmp"))
MELD_DIR, FEAT_DIR = TMP / "meld", TMP / "features"
HF_CACHE = None if DRY_RUN else str(TMP / "hf")   # MELD archives go to /tmp, not to the output
SPLITS = ["train", "dev", "test"]
TMP.mkdir(parents=True, exist_ok=True)
for _d in ("state", "logs", "manifests", "transcripts", "runs", "models", "predictions"):
    (WORK / _d).mkdir(parents=True, exist_ok=True)


def find(pattern, root=INPUT, depth=4):
    """First path matching `pattern` under root, up to `depth` folders down."""
    for k in range(depth + 1):
        hits = sorted(root.glob("/".join(["*"] * k + [pattern])))
        if hits:
            return hits[0]
    return None


_req = find("requirements-kaggle.txt")
if _req is None:
    raise SystemExit("The code is missing: add the dataset emotion-analyzer-code as an input (KAGGLE.md, step 6).")
CODE = _req.parent
sys.path.insert(0, str(CODE))
os.environ["EA_ROOT"] = str(WORK)      # config.py's writable paths point at /kaggle/working
try:
    _smi = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True).stdout
except FileNotFoundError:
    _smi = ""
GPUS = 0 if DRY_RUN else _smi.count("GPU ")
DEVICE, COMPUTE = ("cuda", "float16") if GPUS else ("cpu", "int8")
PARTS = 2 if DRY_RUN else max(1, min(2, GPUS))   # S3 and S5: one subprocess per GPU (§9.2)
BATCH = 4 if DRY_RUN else 16   # Whisper clips per batch; 16 full 30 s windows fit a T4 in fp16
BACKEND = "ct2"          # S0 switches to "hf" (transformers) if CTranslate2 cannot use the GPU
SKIP_W = False           # S0 sets this if /tmp has less than 15 GB free (§9.5)
SKIP_A = not RUN_ABLATIONS
ENV = dict(os.environ, PYTHONPATH=os.pathsep.join([str(CODE), os.environ.get("PYTHONPATH", "")]),
           PYTHONUNBUFFERED="1", PYTHONWARNINGS="ignore")
FAILED = []              # training runs that failed or were not started; S8 reports them


def status(stage, msg):
    print(f"[{stage} {(time.time() - T0) / 60:5.1f} min] {msg}", flush=True)


def done(name):
    return (WORK / "state" / f"{name}.done").exists()


def mark(name, **info):
    (WORK / "state" / f"{name}.done").write_text(json.dumps(info, default=str))


def restore(name, *paths):
    """Resume (§9.3): True if `name` finished here or in the state/ folder of any attached
    input (a previous version's output), whose results are then copied into WORK."""
    if done(name):
        return True
    for k in range(4):
        for marker in sorted(INPUT.glob("/".join(["*"] * k + ["state", f"{name}.done"]))):
            prev = marker.parent.parent
            for p in paths:
                src, dst = prev / p, WORK / p
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                elif src.exists():
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            shutil.copy2(marker, WORK / "state" / marker.name)
            status("resume", f"{name}: reused from {prev}")
            return True
    return False


def tail(path, n=15):
    try:
        return "\n".join(Path(path).read_text(errors="replace").splitlines()[-n:])
    except OSError:
        return "(no log)"


def start(args, gpu=None, log="run.log"):
    """Start `python -m emotion_analyzer.<module> ...` with the GPU library path (§9.2)."""
    env = dict(ENV)
    if gpu is not None:
        env["CUDA_VISIBLE_DEVICES"] = str(gpu)
    with open(WORK / "logs" / log, "a") as f:
        return subprocess.Popen([sys.executable, "-m", *map(str, args)], env=env, stdout=f,
                                stderr=subprocess.STDOUT, cwd=str(WORK))


def run_module(args, log):
    """A short subprocess (merge, decision); raises with the log tail on failure."""
    if start(args, None, log).wait():
        raise RuntimeError(f"{args[0]} failed:\n" + tail(WORK / "logs" / log))
    return tail(WORK / "logs" / log, 3)


def run_parts(make_args, what, log):
    """S3 and S5: PARTS subprocesses, one per GPU, each taking every PARTS-th clip."""
    procs = [start(make_args(k, PARTS), k if GPUS else None, f"{log}.part{k}.log") for k in range(PARTS)]
    codes = [p.wait() for p in procs]
    if any(codes):
        for k in range(PARTS):
            print(f"--- logs/{log}.part{k}.log ---\n" + tail(WORK / "logs" / f"{log}.part{k}.log"))
        raise RuntimeError(f"{what} failed (exit codes {codes}); the log tails are above. An empty log "
                           "usually means out of memory: add a cell with BATCH = 8 and run this cell again. "
                           "If CTranslate2 is the cause, add a cell with BACKEND = 'hf' instead.")


def run_queue(jobs, stage):
    """Training runs (name, output folder, args), one per GPU at a time. Finished runs, here
    or in an attached input, are skipped; none starts after GUARD_HOURS."""
    slots = max(1, GPUS)
    pending, running = list(jobs), {}
    while pending or running:
        while pending and len(running) < slots:
            name, rel, args = pending.pop(0)
            if restore(name, rel):
                continue
            if (time.time() - T0) / 3600 > GUARD_HOURS:
                status(stage, f"{name} not started: over {GUARD_HOURS} h elapsed (session guard)")
                FAILED.append(name)
                continue
            gpu = min(set(range(slots)) - {g for _, g, _ in running.values()})
            proc = start(list(args) + ["--out", WORK / rel], gpu if GPUS else None, f"{name}.log")
            running[name] = (proc, gpu, time.time())
            status(stage, f"{name} started on {'GPU ' + str(gpu) if GPUS else 'CPU'}")
        time.sleep(1 if DRY_RUN else 10)
        for name, (proc, gpu, t) in list(running.items()):
            if proc.poll() is None:
                continue
            del running[name]
            minutes = (time.time() - t) / 60
            if proc.returncode == 0:
                mark(name, minutes=round(minutes, 1))
                status(stage, f"{name} finished in {minutes:.1f} min: {tail(WORK / 'logs' / f'{name}.log', 1)}")
            else:
                FAILED.append(name)
                status(stage, f"{name} FAILED (exit {proc.returncode}); last lines of logs/{name}.log:\n"
                       + tail(WORK / "logs" / f"{name}.log"))


status("C", f"code {CODE}; {GPUS} GPU(s), device {DEVICE}; work {WORK}; dry_run={DRY_RUN}")
```

### Cell 2 — stage S0: environment check, installs and quick benchmark

About 6–8 minutes, 0.2 GPU-hours. **Expected output:** the report shown in step 9, ending with `verdict: GO` and `[S0 ...] report saved to /kaggle/working/s0_check.txt`.

```python
# Cell 2 (stage S0) - environment check, installs and quick benchmark (spec §9.1, §9.2).
import importlib.metadata as md
import platform
import site
import tarfile

REPORT = []


def say(*parts):
    line = " ".join(str(p) for p in parts)
    print(line, flush=True)
    REPORT.append(line)


def ver(pkg):
    try:
        return md.version(pkg)
    except md.PackageNotFoundError:
        return "-"


def timed(args, log):
    t = time.time()
    return start(args, 0 if GPUS else None, log).wait(), time.time() - t


info = json.loads((CODE / "CODE_VERSION.json").read_text())
say(f"S0 check {time.strftime('%Y-%m-%d %H:%M')} | code {info['version']} ({info['git']}) | "
    f"Python {platform.python_version()} | dry_run={DRY_RUN}")
try:
    smi = subprocess.run(["nvidia-smi", "--query-gpu=index,name,memory.total,driver_version",
                          "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
except FileNotFoundError:
    smi = ""
say("GPUs:", " | ".join(smi.splitlines()) if smi and not DRY_RUN else "none")
try:
    import psutil
    ram = f"{psutil.virtual_memory().total / 1e9:.0f} GB"
except ImportError:
    ram = "?"
free = {str(p): shutil.disk_usage(p).free / 1e9 for p in (WORK, TMP)}
say(f"RAM {ram} | free disk: " + ", ".join(f"{p} {g:.0f} GB" for p, g in free.items()))
say("preinstalled:", ", ".join(f"{p} {ver(p)}" for p in ("torch", "transformers", "scikit-learn", "pandas", "numpy")))

if not DRY_RUN:
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(CODE / "requirements-kaggle.txt")],
                       capture_output=True, text=True)
    if r.returncode:
        print(r.stdout[-3000:], r.stderr[-3000:])
        raise RuntimeError("S0: pip install failed (output above). Check that Internet is On in the notebook settings.")
say("installed:", ", ".join(f"{p} {ver(p)}" for p in ("faster-whisper", "ctranslate2", "transformers", "huggingface_hub",
                                                      "jiwer", "ftfy", "soundfile", "nvidia-cublas-cu12",
                                                      "nvidia-cudnn-cu12")))

# cuBLAS and cuDNN for CTranslate2 (§9.2): only read when a process starts, so the GPU
# stages run as subprocesses with this environment.
libdirs = sorted({d for sp in site.getsitepackages() for d in glob.glob(f"{sp}/nvidia/*/lib")})
ENV["LD_LIBRARY_PATH"] = os.pathsep.join(libdirs + [os.environ.get("LD_LIBRARY_PATH", "")])
say(f"LD_LIBRARY_PATH for the GPU subprocesses: {len(libdirs)} nvidia lib folders "
    f"({', '.join(Path(d).parent.name for d in libdirs) or 'none'})")

# A handful of MELD dev clips (§7.1)
from huggingface_hub import hf_hub_download

s0 = TMP / "s0"
(s0 / "dev").mkdir(parents=True, exist_ok=True)
t = time.time()
csv = hf_hub_download("ajyy/MELD_audio", "dev.csv", repo_type="dataset", cache_dir=HF_CACHE)
tgz = hf_hub_download("ajyy/MELD_audio", "archive/dev.tar.gz", repo_type="dataset", cache_dir=HF_CACHE)
shutil.copy(csv, s0 / "dev" / "dev.csv")
n = 0
with tarfile.open(tgz, "r:gz") as tar:
    for m in tar:
        if m.isfile() and m.name.endswith(".flac"):
            with tar.extractfile(m) as src, open(s0 / "dev" / Path(m.name).name, "wb") as dst:
                shutil.copyfileobj(src, dst)
            n += 1
            if n == 32:
                break
say(f"MELD sample: {n} dev clips downloaded and extracted in {time.time() - t:.0f} s")
from emotion_analyzer import data

sample, _ = data.meld_manifest("dev", root=s0, check_counts=False)
sample.to_csv(s0 / "manifest.csv", index=False)


# The CUDA subprocess test: transcribe the sample in both windows on GPU 0 (§9.2)
def tr_args(backend):
    return ["emotion_analyzer.transcribe", "--split", "dev", "--manifest", s0 / "manifest.csv", "--windows", 10, 30,
            "--device", DEVICE, "--compute-type", COMPUTE, "--backend", backend, "--batch-size", BATCH,
            "--out", s0 / f"tr_{backend}"]


rc, _ = timed(tr_args("ct2"), "S0_transcribe_ct2.log")
if rc and GPUS:
    say("CTranslate2 failed on the GPU; last log lines:\n" + tail(WORK / "logs" / "S0_transcribe_ct2.log", 8))
    BACKEND = "hf"
    rc, _ = timed(tr_args("hf"), "S0_transcribe_hf.log")
if rc:
    raise RuntimeError(f"S0: transcription failed; see /kaggle/working/logs/S0_transcribe_{BACKEND}.log")
say(f"CUDA subprocess test: OK, backend {BACKEND} on {'GPU' if GPUS else 'CPU (dry run)'}")
sec = {w: json.loads((s0 / f"tr_{BACKEND}" / f"wer_dev_{w}s.json").read_text())["seconds_per_clip"] for w in (10, 30)}
feat = {}
for w in (10, 30):
    rc, _ = timed(["emotion_analyzer.features", "--manifest", s0 / "manifest.csv", "--window", w,
                   "--out", s0 / f"feat{w}", "--device", DEVICE, "--compute-type", COMPUTE,
                   "--backend", BACKEND, "--batch-size", BATCH], f"S0_features_{w}.log")
    if rc:
        raise RuntimeError(f"S0: feature extraction failed; see /kaggle/working/logs/S0_features_{w}.log "
                           "(an empty log usually means out of memory: lower BATCH in cell 1)")
    m = re.search(r"features: (\d+) clips, \d+ frames, ([\d.]+) s", (WORK / "logs" / f"S0_features_{w}.log").read_text())
    feat[w] = float(m.group(2)) / int(m.group(1))

# Training-step benchmarks (warms the RoBERTa download for S7 too)
steps = 3 if DRY_RUN else 20
code = ("import json; from emotion_analyzer import sound_model as s, text_model as t; "
        f"print(json.dumps({{'sound': s.benchmark({steps}, {DEVICE!r}), 'text': t.benchmark({steps}, {DEVICE!r})}}))")
r = subprocess.run([sys.executable, "-c", code], env=dict(ENV, CUDA_VISIBLE_DEVICES="0") if GPUS else ENV,
                   capture_output=True, text=True)
if r.returncode:
    raise RuntimeError("S0: training benchmark failed:\n" + r.stderr[-2000:])
bench = json.loads(r.stdout.strip().splitlines()[-1])

# Re-estimate every stage (§9.4): GPU-hours and wall-clock hours
N_MELD, N_ACTED, N_SOUND, N_TEXT = 13706, 7442 + 1440, 9988, 19000
par = max(1, GPUS)
est = {}
g = N_MELD * (sec[10] + sec[30]) / 3600
est["S3"] = (g, g / PARTS)
g = ((N_MELD + N_ACTED) * max(feat.values()) + N_MELD * min(feat.values())) / 3600
est["S5"] = (g, g / PARTS)
g = len(SEEDS) * SOUND_MAX_EPOCHS * (2 * -(-N_SOUND // 64) + -(-(N_SOUND + N_ACTED) // 64)) * bench["sound"] / 3600
est["S6 (max)"] = (g, g / par)             # upper bound: every run trains all epochs
g = 2 * len(SEEDS) * TEXT_EPOCHS * -(-N_TEXT // 32) * bench["text"] / 3600
est["S7"] = (g, g / par)
est["S1 S2 S8"] = (0.3, 0.3)
say(f"measured: transcribe {sec[10]:.3f} / {sec[30]:.3f} s per clip (10 s / 30 s window); features "
    f"{feat[10]:.3f} / {feat[30]:.3f} s per clip; sound step {bench['sound']:.3f} s; text step {bench['text']:.3f} s")
say(f"re-estimate (GPU-hours / wall-clock hours on {par} GPU(s)):")
for k, (g, w) in est.items():
    say(f"  {k:<9} {g:5.2f} / {w:5.2f}")
total_g, total_w = sum(g for g, _ in est.values()), sum(w for _, w in est.values())
say(f"  total     {total_g:5.2f} / {total_w:5.2f}   (budget 6 GPU-hours, commit limit 12 h, guard {GUARD_HOURS:.0f} h)")
if free[str(TMP)] < 15:
    SKIP_W = True
    say(f"only {free[str(TMP)]:.0f} GB free in /tmp: features in the chosen window only, ablation W skipped (§9.5)")
say(f"verdict: {'GO' if total_g <= 6 and total_w < GUARD_HOURS else 'CHECK - over budget, see the table'}")
(WORK / "s0_check.txt").write_text("\n".join(REPORT) + "\n")
status("S0", "report saved to /kaggle/working/s0_check.txt (download it from the Output panel)")
```

### Cell 3 — stage S1: download MELD

About 3–5 minutes. **Expected output:** `[S1 ...] train: 9989 clips in 150 s`, then the same for dev and test, then `MELD ready from huggingface ajyy/MELD_audio`. The counts are archive files; the CSV join in S2 gives 9,988 / 1,108 / 2,610.

```python
# Cell 3 (stage S1) - MELD audio and CSVs into /tmp/meld (spec §7.1).
import tarfile


def extract_flacs(tgz, dest, limit=None):
    dest.mkdir(parents=True, exist_ok=True)
    n = 0
    with tarfile.open(tgz, "r:gz") as tar:
        for m in tar:
            if m.isfile() and m.name.endswith(".flac"):
                with tar.extractfile(m) as src, open(dest / Path(m.name).name, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                n += 1
                if limit and n >= limit:
                    break
    return n


def link_fallback():
    """The Kaggle input ngocson2002/meld-datasetv2, attached by hand if Hugging Face fails."""
    names = {"train": ("train",), "dev": ("dev", "val"), "test": ("test",)}
    dirs = [p for k in range(1, 6) for p in INPUT.glob("/".join(["*"] * k)) if p.is_dir()]
    for split in SPLITS:
        csv = next((c for c in (find(f"{split}.csv", depth=5), find(f"{split}_sent_emo.csv", depth=5)) if c), None)
        audio = [d for d in dirs if any(t in d.name.lower() for t in names[split]) and any(d.glob("dia*_utt*.flac"))]
        if csv is None or not audio:
            raise RuntimeError(f"S1: MELD {split} not found. Hugging Face failed and the fallback input is missing: "
                               "add ngocson2002/meld-datasetv2 with Add Input, then commit again.")
        best = max(audio, key=lambda d: sum(1 for _ in d.glob("dia*_utt*.flac")))
        dest = MELD_DIR / split
        dest.mkdir(parents=True, exist_ok=True)
        for f in best.glob("dia*_utt*.flac"):
            if not (dest / f.name).exists():
                (dest / f.name).symlink_to(f)
        shutil.copy(csv, dest / f"{split}.csv")
    return "kaggle ngocson2002/meld-datasetv2"


if (MELD_DIR / "READY").exists():
    status("S1", f"MELD already in {MELD_DIR}")
else:
    try:
        from huggingface_hub import hf_hub_download

        for split in (["dev"] if DRY_RUN else SPLITS):
            t = time.time()
            csv = hf_hub_download("ajyy/MELD_audio", f"{split}.csv", repo_type="dataset", cache_dir=HF_CACHE)
            tgz = hf_hub_download("ajyy/MELD_audio", f"archive/{split}.tar.gz", repo_type="dataset", cache_dir=HF_CACHE)
            n = extract_flacs(Path(tgz), MELD_DIR / split, limit=5 * LIMIT if DRY_RUN else None)
            shutil.copy(csv, MELD_DIR / split / f"{split}.csv")
            if not DRY_RUN:
                os.remove(os.path.realpath(tgz))        # extracted; free the space in /tmp
            status("S1", f"{split}: {n} clips in {time.time() - t:.0f} s")
        source = "huggingface ajyy/MELD_audio"
    except Exception as e:
        status("S1", f"Hugging Face download failed ({e!r}); trying the fallback input")
        source = link_fallback()
    if DRY_RUN:     # the rehearsal downloads dev only and reuses it as train and test
        for split in ("train", "test"):
            shutil.copytree(MELD_DIR / "dev", MELD_DIR / split, dirs_exist_ok=True)
            (MELD_DIR / split / "dev.csv").replace(MELD_DIR / split / f"{split}.csv")
    (MELD_DIR / "READY").write_text(source)
    status("S1", f"MELD ready from {source}")
```

### Cell 4 — stage S2: manifests and class tables

About 3–5 minutes, most of it resampling RAVDESS. **Expected output:** a class table with columns `meld_train`, `meld_dev`, `meld_test`, `cremad` and `ravdess`. The totals are 9,988 / 1,106 / 2,610 / 7,442 / 1,440, minus any clip that is too short or unreadable. Then `[S2 ...] manifests written; N clips dropped`. The count assertion (AC-01) raises an error if a MELD join count is wrong.

```python
# Cell 4 (stage S2) - manifests and class tables (spec §7).
import pandas as pd
from emotion_analyzer import data

tables, notes = {}, []
for split in SPLITS:
    df, dropped = data.meld_manifest(split, root=MELD_DIR, check_counts=not DRY_RUN)
    if LIMIT:
        df = df.sample(n=min(LIMIT, len(df)), random_state=0).sort_index()
    df.to_csv(WORK / "manifests" / f"meld_{split}.csv", index=False)
    tables[f"meld_{split}"] = data.class_table(df)
    notes += [f"meld {split}: {d}" for d in dropped]
if not SKIP_A:
    crema, rav = find("AudioWAV"), find("Actor_01")
    if crema is None or rav is None:
        SKIP_A = True
        status("S2", "CREMA-D or RAVDESS input missing: ablation A skipped "
               "(add ejlok1/cremad and uwrfkaggler/ravdess-emotional-speech-audio to run it)")
    else:
        cdf, cdrop = data.cremad_manifest(crema)
        rdf, rdrop = data.ravdess_manifest(INPUT / rav.relative_to(INPUT).parts[0])  # both copies, de-duplicated
        rdf = data.resample_corpus(rdf, TMP / "ravdess16k")
        acted = pd.concat([cdf, rdf], ignore_index=True)
        if LIMIT:
            acted = acted.sample(n=min(LIMIT, len(acted)), random_state=0)
        acted.to_csv(WORK / "manifests" / "acted.csv", index=False)
        tables["cremad"], tables["ravdess"] = data.class_table(cdf), data.class_table(rdf)
        notes += [f"acted: {d}" for d in cdrop + rdrop]
table = pd.DataFrame(tables)
table.loc["total"] = table.sum()
table.to_csv(WORK / "logs" / "class_tables.csv")
print(table.to_string())
(WORK / "logs" / "S2_dropped.txt").write_text("\n".join(map(str, notes)) + "\n")
status("S2", f"manifests written; {len(notes)} clips dropped or absent (logs/S2_dropped.txt)")
```

### Cell 5 — stage S3: transcripts in both windows

About 26 minutes on two GPUs, 0.9 GPU-hours. **Expected output:** one line per split, for example `[S3 ...] train: WER 27.1% (10 s window), 24.3% (30 s) in 18 min`. Expect roughly 20–35% (§8.1). Detailed logs: `logs/S3_{split}.part{0,1}.log`.

```python
# Cell 5 (stage S3) - transcripts of every MELD split in both windows, on both GPUs (spec §8.1).
for split in SPLITS:
    name = f"S3_{split}"
    if restore(name, "transcripts"):
        continue
    t = time.time()
    run_parts(lambda k, n: ["emotion_analyzer.transcribe", "--split", split,
                            "--manifest", WORK / "manifests" / f"meld_{split}.csv", "--windows", 10, 30,
                            "--parts", n, "--part", k, "--device", DEVICE, "--compute-type", COMPUTE,
                            "--backend", BACKEND, "--batch-size", BATCH, "--out", WORK / "transcripts"],
              f"S3 {split}", name)
    if PARTS > 1:
        run_module(["emotion_analyzer.transcribe", "--split", split, "--windows", 10, 30, "--parts", PARTS,
                    "--merge", "--out", WORK / "transcripts"], f"{name}.merge.log")
        for f in (WORK / "transcripts").glob(f"{split}_*s.part*.csv"):
            f.unlink()
    wer = {w: round(json.loads((WORK / "transcripts" / f"wer_{split}_{w}s.json").read_text())["wer"], 2)
           for w in (10, 30)}
    mark(name, wer=wer, minutes=round((time.time() - t) / 60, 1))
    status("S3", f"{split}: WER {wer[10]:.1f}% (10 s window), {wer[30]:.1f}% (30 s) in {(time.time() - t) / 60:.0f} min")
```

### Cell 6 — stage S4: window decision

Seconds. **Expected output:** `[S4 ...] window 10 s (case a: dev WER gap <= 2.0 -> 10 s, else 30 s); WER gap 10 s - 30 s: {'dev': ..., 'test': ...}`.

In case (b), the window stays at 10 s and the gaps are recorded as the WER cost (§8.1).

```python
# Cell 6 (stage S4) - window decision by the rule in spec §8.1; writes decision.json.
if not restore("S4", "transcripts/decision.json"):
    run_module(["emotion_analyzer.transcribe", "--decide", "--case", WINDOW_CASE, "--out", WORK / "transcripts"],
               "S4.log")
    mark("S4")
DECISION = json.loads((WORK / "transcripts" / "decision.json").read_text())
W = DECISION["window_s"]
W_OTHER = 30 if W == 10 else 10
shutil.copy2(WORK / "transcripts" / "decision.json", WORK / "models" / "decision.json")
status("S4", f"window {W} s ({DECISION['rule']}); WER gap 10 s - 30 s: {DECISION['wer_gap_10s_minus_30s']}")
```

### Cell 7 — stage S5: encoder frames

About 12 minutes on two GPUs, 0.4 GPU-hours. **Expected output:** one line per feature set, for example `[S5 ...] meld_10s/train: done in 4.1 min`. It ends with `N feature sets ready for M sound runs; X GB free in /tmp`. Features stay in `/tmp/features` and are not saved.

```python
# Cell 7 (stage S5) - encoder frames, trimmed, fp16 shards in /tmp/features (spec §8.2), on both GPUs.
SOUND_RUNS = [("main", s) for s in SEEDS]
if RUN_ABLATIONS:
    SOUND_RUNS += [("A", s) for s in SEEDS if not SKIP_A] + [("W", s) for s in SEEDS if not SKIP_W]


def sound_sets(run):
    w = W_OTHER if run == "W" else W
    sets = {f"meld_{w}s/{sp}": (f"meld_{sp}.csv", w) for sp in SPLITS}
    if run == "A":
        sets[f"acted_{W}s"] = ("acted.csv", W)
    return sets


pending = [(r, s) for r, s in SOUND_RUNS if not restore(f"S6_{r}_seed{s}", f"runs/sound/{r}_seed{s}")]
needed = {}
for r, _ in pending:
    needed.update(sound_sets(r))
for key, (manifest, w) in sorted(needed.items(), key=lambda kv: (kv[1][1] != W, kv[0])):
    out = FEAT_DIR / key
    if (out / "DONE").exists():
        continue
    t = time.time()
    run_parts(lambda k, n: ["emotion_analyzer.features", "--manifest", WORK / "manifests" / manifest,
                            "--window", w, "--out", out, "--parts", n, "--part", k, "--device", DEVICE,
                            "--compute-type", COMPUTE, "--backend", BACKEND, "--batch-size", BATCH],
              f"S5 {key}", "S5_" + key.replace("/", "_"))
    (out / "DONE").write_text(f"{time.time() - t:.0f} s")
    status("S5", f"{key}: done in {(time.time() - t) / 60:.1f} min")
status("S5", f"{len(needed)} feature sets ready for {len(pending)} sound runs; "
       f"{shutil.disk_usage(TMP).free / 1e9:.0f} GB free in /tmp")
```

### Cell 8 — stage S6: sound heads

About 14 minutes, 0.45 GPU-hours. There are 9 runs (main, A and W, × 3 seeds), two at a time. **Expected output:** per run, `S6_main_seed0 started on GPU 0`, then `S6_main_seed0 finished in 2.8 min: [main seed 0] best dev wF1 43.10`. Expect roughly 40–46 for main (§10.9). Logs: `logs/S6_*.log`.

```python
# Cell 8 (stage S6) - sound heads: main, A and W x seeds, one per GPU at a time (spec §8.2).
jobs = []
for r, s in SOUND_RUNS:
    w = W_OTHER if r == "W" else W
    train = [FEAT_DIR / f"meld_{w}s/train"] + ([FEAT_DIR / f"acted_{W}s"] if r == "A" else [])
    jobs.append((f"S6_{r}_seed{s}", f"runs/sound/{r}_seed{s}",
                 ["emotion_analyzer.sound_model", "--train", *train, "--dev", FEAT_DIR / f"meld_{w}s/dev",
                  "--test", FEAT_DIR / f"meld_{w}s/test", "--seed", s, "--run-name", r, "--window", w,
                  "--max-epochs", SOUND_MAX_EPOCHS, "--device", DEVICE]))
run_queue(jobs, "S6")
status("S6", f"sound runs finished; failed or skipped so far: {FAILED or 'none'}")
```

### Cell 9 — stage S7: text models

About 30 minutes, 1.0 GPU-hours. There are 6 runs (main and T, × 3 seeds), two at a time, one per GPU. **Expected output:** per run, `S7_main_seed0 finished in 10.2 min: [text main seed 0] best dev wF1 (Whisper) 54.3`. All three main seeds are saved as fp16 safetensors (F2).

```python
# Cell 9 (stage S7) - text models: main and T x seeds, two at a time, one per GPU (spec §8.3).
TEXT_RUNS = [("main", s) for s in SEEDS] + ([("T", s) for s in SEEDS] if RUN_ABLATIONS else [])
jobs = []
for r, s in TEXT_RUNS:
    jobs.append((f"S7_{r}_seed{s}", f"runs/text/{r}_seed{s}",
                 ["emotion_analyzer.text_model", "--transcripts", WORK / "transcripts", "--window", W,
                  "--seed", s, "--epochs", TEXT_EPOCHS, "--device", DEVICE]
                 + (["--real-only", "--no-save-model"] if r == "T" else [])))
run_queue(jobs, "S7")
status("S7", f"text runs finished; failed or skipped so far: {FAILED or 'none'}")
```

### Cell 10 — stage S8: export

About 3 minutes. **Expected output:** the final results block, then `[S8 ...] emotion_outputs.zip 0.8 GB`.

```
EMOTION ANALYZER - FINAL RESULTS (weighted-F1, mean +- sd over seeds)
window 10 s (case a); WER gap 10s-30s {'dev': 1.4, 'test': 1.6}
WER  dev_10s 25.9  dev_30s 24.5  test_10s 27.0  test_30s 25.4  train_10s ...
row                                   dev           test
R0 majority                             -           31.3
R1 sound main                43.5+-0.6 (3)  42.8+-0.5 (3)
...
R7 fused Whisper (provisional, per-seed w 0.35, 0.3, 0.35): test 56.1+-0.4
deployed_sound: main_seed1
text_seeds: [0, 1, 2]
elapsed_h: 1.9
```

```python
# Cell 10 (stage S8) - export: models, predictions, metrics.json, final results block, zip (spec §9.3, §9.5).
import zipfile
from emotion_analyzer import evaluate

models = WORK / "models"
heads = sorted(WORK.glob("runs/sound/main_seed*/sound_head.json"))
deployed = None
if heads:
    best = max(heads, key=lambda f: json.loads(f.read_text())["dev_wf1"])   # best dev weighted-F1 (§8.2)
    shutil.copy2(best.with_suffix(".pt"), models / "sound_head.pt")
    shutil.copy2(best, models / "sound_head.json")
    deployed = best.parent.name
text_dirs = {int(d.parent.name.split("seed")[-1]): d for d in sorted(WORK.glob("runs/text/main_seed*/model"))}
for f in sorted(WORK.glob("runs/*/*/pred_*.npz")):
    shutil.copy2(f, WORK / "predictions" / f"{f.parts[-3]}_{f.parts[-2]}_{f.stem[5:]}.npz")
(WORK / "logs" / "histories").mkdir(exist_ok=True)
for f in sorted(WORK.glob("runs/*/*/history.json")):
    shutil.copy2(f, WORK / "logs" / "histories" / f"{f.parts[-3]}_{f.parts[-2]}.json")
if (WORK / "s0_check.txt").exists():
    shutil.copy2(WORK / "s0_check.txt", WORK / "logs" / "s0_check.txt")

skipped = list(FAILED) + (["ablation W (disk)"] if SKIP_W else []) + (["ablation A (inputs)"] if SKIP_A and RUN_ABLATIONS else [])
summary = {"decision": DECISION, "wer": evaluate.wer_table(WORK / "transcripts"),
           "runs": evaluate.summarize_runs(WORK / "runs"),
           "provisional_fusion": evaluate.provisional_fusion(WORK / "runs"),
           "deployed_sound": deployed, "text_seeds": sorted(text_dirs), "backend": BACKEND, "gpus": GPUS,
           "elapsed_h": round((time.time() - T0) / 3600, 2), "skipped": skipped}
(WORK / "metrics.json").write_text(json.dumps(summary, indent=2))
block = evaluate.final_block(summary)
(WORK / "logs" / "final_results.txt").write_text(block + "\n")

entries = [(WORK / "metrics.json", "metrics.json")]
for src, arc in [(models, "models"), (WORK / "predictions", "predictions"),
                 (WORK / "transcripts", "transcripts"), (WORK / "logs", "logs")] + \
                [(d, f"models/text_model_seed{k}") for k, d in text_dirs.items()]:   # zipped from runs/, not copied
    entries += [(f, f"{arc}/{f.relative_to(src).as_posix()}") for f in sorted(src.rglob("*")) if f.is_file()]
zpath = WORK / "emotion_outputs.zip"
with zipfile.ZipFile(zpath, "w") as z:
    for f, arc in entries:
        stored = f.suffix in (".safetensors", ".pt", ".npz")             # already compact
        z.write(f, arc, compress_type=zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED)
mark("S8", zip_gb=round(zpath.stat().st_size / 1e9, 2), files=len(entries))
print(block)
status("S8", f"emotion_outputs.zip {zpath.stat().st_size / 1e9:.2f} GB - download it from the version's Output tab")
```

## 5. Local rehearsal (Phase 5)

Before any Kaggle run, the same cells run on the laptop CPU, on a tiny subset:

```
E:\AIDS\Project\emotion-analyzer
.venv\Scripts\python.exe scripts\package_kaggle.py --dry-run
```

- It builds the package in a scratch folder, along with stand-ins for the acted corpora made from local MELD dev clips (they stay in the scratch folder).
- It runs cells 1–10 in one Python process, as a notebook kernel would, with `EA_DRY_RUN=1`. That means 12 clips per split, 2 seeds, 3 sound epochs and 1 text epoch.
- It then runs them again as a fresh session with the first run's output attached as an input. This checks that every finished stage is reused.
