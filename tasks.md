# Emotion Analyzer: build tasks

Derived from `specs.md` v1.0, §14. The spec is the source of truth: if a task here and the spec disagree, the spec wins and this file is corrected.

- `[ ]` to do, `[x]` done. **[USER]** marks a task that needs you. I stop and ask instead of doing it.
- Every phase ends the same way (§14): its tests pass, its tasks are ticked here, problems go in `issues.md`, results in `insights.md`, then a commit.
- Each phase's **Done when** line is §14's check, with the matching acceptance criteria from §11 written out.

## Before P1: spec review decisions

Found while reading the spec in full. Accepted changes go into `specs.md` first (v1.1, reasons in §20), then into the phases below. Phase tasks tagged (F*n*) depend on the decision.

- [ ] [USER] **F1** §1 says "calibrated probabilities" and "runs fully offline" are measured in §10, but §10 and §11 measure neither. Proposal: add ECE and a reliability diagram, with one temperature fitted on dev (computed from the saved probabilities, so no Kaggle re-run), plus an offline check (server started with the network off and `HF_HUB_OFFLINE=1`). Alternative: drop "calibrated".
- [ ] [USER] **F2** §17 allows a 3-seed text ensemble, but S7 (§9.3) exports only the best seed's checkpoint, so choosing the ensemble later means a second Kaggle run. Proposal: S7 exports all 3 main-seed checkpoints (about +500 MB; the zip stays under 1 GB), so the choice can wait until P8.
- [ ] [USER] **F3** §4.3 keeps MELD-derived data private, but P6 unpacks transcripts and per-utterance predictions into `results/`, which §13 commits. Proposal: those go to `data/kaggle/` (git-ignored); `results/` holds only aggregate tables, figures and `metrics.json`.
- [ ] [USER] **F4** §5.2 runs VAD only on audio over 10 s, so silence in a short clip is never detected, yet AC-11 tests silence. Proposal: run VAD on every clip; a clip of 10 s or less that contains speech stays one segment.
- [ ] [USER] **F5** AC-03 is judged on the 3-seed mean, AC-04 and AC-05 don't say, and R7 is a single deployed pair, so AC-05 may compare one model against a seed mean. Proposal: every trained row is mean ± sd over seeds (R7 and R8 fuse sound seed *i* with text seed *i* at the deployed weight), plus a "deployed system" row; the ACs use the means.
- [ ] [USER] **F6** The `base.en` fallback (§8.1) is not drop-in: its encoder output is 512-d where the sound head expects small.en's 768-d frames, and the text model is trained on small.en transcripts. Switching after training means a second Kaggle run. Proposal: P3 measures end-to-end CPU latency in both windows and settles small.en versus base.en before P5.
- [ ] [USER] **F7** `pad_or_trim` cuts clips longer than the window. In the 10 s window that drops words from the 2.1 % of MELD clips over 10 s (3 clips also exceed 30 s), which biases the WER rule against the 10 s window. Proposal: transcribe in chunks of up to 10 s and join the text, as §8.2 already does for frames and as the app does through segmentation.
- [ ] [USER] **F8** Resuming (§9.3): an attached notebook output mounts under that notebook's own slug, not at `/kaggle/input/emotion-analyzer-prev/`. Proposal: look for `state/` markers in every `/kaggle/input/*/`; `KAGGLE.md` also describes the "New Dataset from output" route.
- [ ] [USER] **F9** P6 checks parity for the fused output, which needs the fusion weight that §14 schedules in P7. Proposal: run the weight search at the start of P6.
- [ ] [USER] **F10** §8.1 says small.en gets "about 14 % on clean speech". On LibriSpeech test-clean it gets about 3 % (Whisper paper); 14 % matches acted IEMOCAP speech. Proposal: reword.
- [ ] [USER] **F11** §13 has no `pyproject.toml` (needed to make `src/` importable locally and for `python -m` on Kaggle, and to register the pytest `slow` marker) and no versioned pre-commit hook. Proposal: add `pyproject.toml` and `.githooks/pre-commit` (enabled with `git config core.hooksPath .githooks`) in P1.
- [ ] [USER] **F12** The UI serves demo samples, but `data/own/` is git-ignored and the spec doesn't say where demo files live. Proposal: a git-ignored `app/static/samples/`, filled from the clips whose speakers agreed.
- [ ] [USER] **F13** A risk missing from §16: campus Wi-Fi often blocks device-to-device traffic, and the firewall rule only applies on a network set to Private. Proposal: add it to §16, with a phone hotspot or the tunnel as the fallback for AC-12.
- [ ] [USER] **F14** A risk to AC-15: I can't run `/export` myself, and its output format (and its behaviour after context compaction) is unknown until tried. Proposal: you run one trial `/export` after P1 so the converter is built against the real format; the session's `.jsonl` log is the fallback source.
- [ ] [USER] **F15** With Gemini, your friends' clips are sent to Google. Proposal: the consent covers that, and the README says so.

## P1 Scaffold

- [x] `.gitignore`: the §13 entries (created with the plan commit)
- [ ] Folder tree from §13: `src/emotion_analyzer/`, `app/static/`, `scripts/`, `tests/`, `tools/`, `results/`, `data/meld/dev/`, `data/own/`, `models/`, `kaggle/code/`
- [ ] `.venv/` built with `py -3.12` (installed; never the 3.14 `python` on PATH)
- [ ] `requirements.txt`: the local CPU environment, pinned (CPU-only torch, faster-whisper, transformers, FastAPI, uvicorn and the rest)
- [ ] `.env.example` containing an empty `GEMINI_API_KEY=`
- [ ] `src/emotion_analyzer/__init__.py` and `src/emotion_analyzer/config.py`: labels in the fixed order, paths, window, thresholds, seeds
- [ ] `README.md` stub, plus empty `issues.md` and `insights.md`
- [ ] `tests/test_repo_rules.py`: first trivial checks (label order, `.gitignore` entries); the full AC-13 scan comes in P10
- [ ] `pyproject.toml` and `.githooks/pre-commit` running the fast tests (F11)
- **Done when:** `pytest` runs and the trivial tests pass; commit "P1: scaffold".

## P2 Data

- [ ] `data/meld/dev/`: `archive/dev.tar.gz` and `dev.csv` from `ajyy/MELD_audio` via `hf_hub_download` (git-ignored)
- [ ] `src/emotion_analyzer/data.py`: MELD manifests, inner join on (`Dialogue_ID`, `Utterance_ID`), `ftfy` text repair, count assertions, unreadable or under-0.1 s clips dropped and logged in `issues.md`
- [ ] `data.py`: CREMA-D and RAVDESS loaders with the §7.2 label maps (RAVDESS from one folder tree, de-duplicated by file name, resampled to 16 kHz)
- [ ] `data.py`: own-recordings loader, label read from `{emotion}_{nn}.{ext}`
- [ ] `tests/test_data.py`: the dev join gives 1,108 pairs with `dia110_utt7` missing; label maps; file-name parsing; text repair never touches labels
- [ ] `insights.md`: short data report (class counts, durations, defects found)
- [ ] [USER] Record 30–50 clips of 3–8 s (at least 4 per emotion, with the speakers' consent; see F15) into `data/own/`. This doesn't block P2; P7 needs it, and so do the P8 demo samples
- **Done when:** the AC-01 logic is tested on dev (1,108 pairs) and the label-map tests pass. AC-01 (§11): MELD joins to 9,988 / 1,108 / 2,610 audio–label pairs, checked by a loader assertion and a test (train and test are asserted on Kaggle in S2).

## P3 Speech pipeline

- [ ] `src/emotion_analyzer/speech.py`: `SpeechPipeline` with decoding (16 kHz mono, 0.5–120 s), VAD segmentation into 1–10 s pieces (F4), the shared encode in both windows, the transcript from the encoder output, valid frames and per-stage timing
- [ ] `src/emotion_analyzer/metrics.py`: WER with Whisper's English normaliser and `jiwer` (the rest of the module comes in P4)
- [ ] `tests/test_speech.py`: decoding and limits, segmentation rules, frame counts (500 for the 10 s window), the no-speech case; tests that need weights are marked `slow`
- [ ] WER on 300 local dev clips in both windows (F7) → `insights.md`
- [ ] Per-stage CPU times in both windows, and the end-to-end time on a 5 s clip against AC-08's 2.0 s (F6: settles small.en versus base.en before P5) → `insights.md`
- [ ] Preliminary window rule evaluated (§8.1: WER(10 s) − WER(30 s) ≤ 2.0 points) → `insights.md`
- **Done when:** the numbers are in `insights.md`, the preliminary window rule is evaluated, and the tests pass.

## P4 Training code

- [ ] `src/emotion_analyzer/features.py`: batched encoder frames, long clips in chunks of up to 10 s, fp16 shards with an index, on CPU or CUDA
- [ ] `src/emotion_analyzer/transcribe.py`: batch transcription in both windows and WER per split, runnable as `python -m` with an option to process one half of the clip list (one GPU each)
- [ ] `src/emotion_analyzer/sound_model.py`: the attention-pooling head (§8.2), its training loop (AdamW, cosine schedule with warm-up, early stopping on dev weighted-F1, frame drop and crop, class weights) and inference
- [ ] `src/emotion_analyzer/text_model.py`: the RoBERTa classifier (§8.3), its training set (real plus Whisper transcripts, de-duplicated), training loop, int8 dynamic quantisation and inference
- [ ] `src/emotion_analyzer/fusion.py`: weighted log-probability fusion, the weight grid search, the disagreement rule
- [ ] `src/emotion_analyzer/metrics.py`: weighted-F1, macro-F1, accuracy, per-class report, confusion matrix, bootstrap CIs
- [ ] `tests/test_models.py`, `tests/test_fusion.py`, `tests/test_metrics.py`
- [ ] Local smoke run of every stage on a few dev clips with tiny settings → `insights.md`
- **Done when:** every stage's code runs end to end locally on tiny settings.

## P5 Kaggle package

- [ ] [USER] §17 decision: text model at inference, best single seed (default) or the 3-seed ensemble. Needed before packaging because it decides what S7 exports, unless F2 is accepted
- [ ] `requirements-kaggle.txt`: pinned `faster-whisper` and `ctranslate2`, `jiwer`, `ftfy`, `huggingface_hub`, `soundfile`, plus the cuBLAS/cuDNN fix from §9.2
- [ ] `scripts/package_kaggle.py` → `kaggle/code/`
- [ ] `KAGGLE.md`: inputs and settings; the two passes (S0 interactive, then Save & Run All); cells S0–S8, each complete, with expected output and run time; one config cell at the top; resume markers in `/kaggle/working/state/` (F8); the 11 h guard; both T4s; the final results block; how to resume from a previous version and how to download the results
- [ ] Local dry-run of the S0–S8 sequence on a tiny subset, on CPU → `insights.md`
- [ ] GPU-hours estimate stated in `KAGGLE.md` (§9.4: about 3.2 GPU-hours, about 2 h wall-clock)
- **Done when:** the dry-run passes and the GPU-hours estimate is stated.

## Kaggle run (between P5 and P6)

- [ ] [USER] Kaggle account phone-verified (needed for Internet On)
- [ ] [USER] Upload `kaggle/code/` as the private dataset `emotion-analyzer-code`
- [ ] [USER] Create the private notebook `emotion-analyzer-train`: add `emotion-analyzer-code`, `ejlok1/cremad` and `uwrfkaggler/ravdess-emotional-speech-audio` as inputs; set Accelerator GPU T4 ×2 and Internet On; paste the cells from `KAGGLE.md`
- [ ] [USER] Run only S0 in the editor and paste its output here, so I can check the CUDA subprocess test and the re-estimated times
- [ ] [USER] Save Version → Save & Run All (Commit); if it fails part-way, follow the resume steps in `KAGGLE.md`
- [ ] [USER] Download `emotion_outputs.zip` from the version's Output tab into `data/kaggle/` (git-ignored)
- **Done when:** `emotion_outputs.zip` is downloaded from the version's Output tab.

## P6 Import and parity

- [ ] Unpack `emotion_outputs.zip`: `sound_head.pt`, `sound_head.json`, `text_model/` and `decision.json` into `models/`; `metrics.json` into `results/`; transcripts and predictions as decided in F3
- [ ] Training results (the S8 results block, per-run dev and test scores) → `insights.md`
- [ ] Fusion weight search on the Kaggle dev probabilities → `models/fusion.json` (F9; §14 lists it in P7)
- [ ] `src/emotion_analyzer/evaluate.py` (parity part): the CPU int8 pipeline on all of MELD dev (features, transcripts, quantised text model) and the weighted-F1 comparison for sound, text and fused → `results/parity.md`
- [ ] Only if the sound gap is over 1.5 points: retrain the head on local CPU-int8 features (§16) → `models/sound_head.pt`
- **Done when:** AC-07 is checked and the training results are in `insights.md`. AC-07 (§11): CPU parity, weighted-F1 difference of at most 1.5 points on dev, from the §10.5 report.

## P7 Evaluation

- [ ] `src/emotion_analyzer/evaluate.py` → `results/results_table.md` and `results/results_table.csv`: rows R0–R8 (§10.2) with weighted-F1, macro-F1, accuracy, 95 % bootstrap CIs and seed mean ± sd (F5)
- [ ] `evaluate.py` → `results/per_class.md` and confusion matrices `results/confusion_*.png` (150 dpi)
- [ ] `evaluate.py` → `results/wer.md`: WER for dev and test in both windows, and the window decision
- [ ] Calibration and offline check, if F1 is accepted → `results/calibration.md`, `results/reliability.png`
- [ ] [USER] Laptop plugged in for the latency run
- [ ] `src/emotion_analyzer/latency.py` → `results/latency.md`: 2 warm-up and 20 timed runs on a 5 s clip; median and p90 per stage and in total; server peak memory
- [ ] `evaluate.py` → `results/own_recordings.md`: per-clip predictions, accuracy, weighted-F1, small-sample caveat
- [ ] [USER] §17 decision: chatbot comparison through the Gemini free API (default) or ChatGPT by hand
- [ ] [USER] If Gemini: add `GEMINI_API_KEY` to `.env` yourself (never paste it into the chat)
- [ ] [USER] If ChatGPT: send each clip with the §10.7 instruction and log every answer in `results/chatbot_raw.csv`
- [ ] `src/emotion_analyzer/chatbot_compare.py` → `results/chatbot.md`: accuracy, weighted-F1 and latency next to ours; model name and date; online and not private
- [ ] `evaluate.py` → `results/error_analysis.md`: 10 MELD test clips where sound and text disagree, and the confusions per class
- [ ] Results, figures and a verdict on every AC → `insights.md`
- **Done when:** AC-02 to AC-10 are checked and reported. From §11:
  - AC-02: WER reported for dev and test in both windows, window chosen by the §8.1 rule (`insights.md`, `decision.json`)
  - AC-03: sound only (R1), MELD test weighted-F1 ≥ 40.0 (mean of 3 seeds)
  - AC-04: text on real transcripts (R4) ≥ 58.0
  - AC-05: fused with Whisper transcripts (R7) ≥ 52.0 and ≥ text on Whisper transcripts (R5)
  - AC-06: every model row beats the majority baseline (31.3 weighted-F1)
  - AC-07: CPU parity within 1.5 points on dev (checked in P6, reported here)
  - AC-08: median ≤ 2.0 s per 5 s clip end to end, laptop plugged in (stretch ≤ 1.2 s), from `latency.py`
  - AC-09: server peak memory ≤ 2.5 GB, from `latency.py`
  - AC-10: own recordings evaluated, and the chatbot comparison done on the same clips (`results/` tables)
  - Any failed criterion is reported with its measured value, never hidden.

## P8 App

- [ ] [USER] §17 decisions: overall label for multi-segment audio (duration-weighted mean, the default, or majority vote) and the disagreement threshold (0.40, the default, or 0.30 / 0.50) → `config.py`
- [ ] [USER] Choose which of your clips can be demo samples (only speakers who agreed) → demo folder (F12)
- [ ] `app/main.py`: FastAPI, models loaded once at start-up, `GET /`, `GET /api/health`, `POST /api/analyze`, errors 400 / 413 / 422 in the §5.3 shape
- [ ] `app/static/index.html`, `app/static/app.js`, `app/static/style.css`: record and upload, the fused result card, the "How it sounds" and "What was said" cards, transcript, disagreement banner, timeline for recordings over 10 s, processing time, demo samples, About panel (citations and limitations), phone-width layout, no CDNs
- [ ] `tests/test_api.py`: normal clip, silence, long recording (segmented), unsupported format, too large, too short (no MELD audio committed as a fixture)
- [ ] [USER] Try the app locally (record and upload) and tell me what you think
- **Done when:** AC-11 passes and you have tried the app locally. AC-11 (§11): the API tests pass for a normal clip, silence, a long recording (segmented), an unsupported format, a file that is too large and one that is too short (`pytest`).

## P9 Deployment

- [ ] [USER] §17 decision: internet link, an optional Cloudflare quick tunnel on demand (default) or local network only
- [ ] Port 8443 confirmed free → `insights.md`
- [ ] `scripts/make_cert.py` → `certs/key.pem` and `certs/cert.pem` (SANs `localhost`, `127.0.0.1` and the current LAN IP)
- [ ] `scripts/serve.ps1`: activates the venv, checks the models are present, starts uvicorn on 8443 with one worker, prints the LAN and localhost URLs
- [ ] `scripts/tunnel.ps1`: the Cloudflare quick tunnel (if enabled)
- [ ] `scripts/smoke.ps1`: calls `/api/health` and `/api/analyze` through the real LAN address
- [ ] `README.md`: the "Running in production" section, with the firewall line and the working directory before every command
- [ ] [USER] In an administrator PowerShell, add the inbound rule for TCP 8443 on the Private profile, and make sure the Wi-Fi network is set to Private (F13)
- [ ] [USER] Open the app on your phone on the same Wi-Fi, accept the certificate warning once, then test upload and record
- [ ] [USER] If the tunnel is enabled, open its `trycloudflare.com` address on mobile data and test it
- [ ] Deployment check (phone, microphone, tunnel) → `insights.md`
- **Done when:** AC-12 is verified from a phone. AC-12 (§11): the app is reachable from a phone on the same Wi-Fi over HTTPS and analysis works (upload and record); the optional internet link works if enabled. Recorded as the deployment check in `insights.md`.

## P10 Wrap-up

- [ ] `README.md` complete: install, run, train (via `KAGGLE.md`), deploy, citations (§18)
- [ ] `specs.md` matches the build, with every change recorded in §20
- [ ] `tests/test_repo_rules.py`: the AC-13 scan (no MELD audio tracked in git or among the demo samples; no banned checkpoint in code or config)
- [ ] Final full test run, including `slow` → `insights.md`
- [ ] Fresh-clone walkthrough of the README (install, tests, serve) → `insights.md`
- [ ] [USER] Read the README end to end and confirm a new user could follow it (the AC-14 manual check)
- [ ] `tools/transcript_to_html.py`
- [ ] [USER] Run `/export transcript.md` at the end of the session (F14)
- [ ] `transcript.html` built from `transcript.md`: "Turn N" headings, each response in a collapsed block
- **Done when:** AC-13 to AC-15 pass. From §11:
  - AC-13: no MELD audio in git or in the demo samples, and no banned checkpoint anywhere in the code (a test scans the repository and config)
  - AC-14: the README lets a new user install, run, train (via `KAGGLE.md`) and deploy from scratch (manual check)
  - AC-15: the transcript is exported and converted to `transcript.html` with Turn N headings and collapsed responses
