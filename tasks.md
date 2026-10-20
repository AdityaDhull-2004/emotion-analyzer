# Emotion Analyzer: build tasks

Derived from `specs.md` v1.2, §14. The spec is the source of truth. If a task here and the spec disagree, the spec wins and this file is corrected.

**Markers**
- `[ ]` to do, `[x]` done.
- **USER**: the build stops here until the user has done it.
- **USER-ANYTIME**: the user does it in parallel. The build doesn't stop. Each one names the phase that needs it; until it's done, every phase summary reminds the user. The build stops only if that phase arrives and it still isn't done.

**Every phase ends the same way (§14):**
1. Its tests pass.
2. Its tasks are ticked here.
3. Problems go in `issues.md`, and results in `insights.md`.
4. A commit named `Pn: …`.
5. A short summary.

Then the build carries straight on to the next phase.

---

## Spec review (done, recorded in specs.md v1.1 §20)

- [x] F1 Calibration (ECE, reliability diagram, temperatures fitted on dev) and an offline check added → AC-16 (P7), AC-17 (P9)
- [x] F2 S7 exports all three text seeds; the ensemble is chosen by the §8.3 rule (moved from P8 to the start of P6 in v1.2)
- [x] F3 Per-utterance transcripts and predictions stay in the git-ignored `data/kaggle/`; `results/` holds aggregates only
- [x] F4 VAD runs on every clip (silence detection)
- [x] F5 Every trained row is reported as a seed mean ± sd; R7 and R8 pair seed *i* with seed *i*; R9 is the deployed system; the ACs use the means
- [x] F6 Model size (small.en or base.en) settled in P3, before any training
- [x] F7 Clips longer than the window are transcribed in chunks and the text joined
- [x] F8 Resuming searches `state/` in every attached input under `/kaggle/input/*/`
- [x] F9 Temperatures and fusion weight fitted at the start of P6
- [x] F10 WER wording corrected (about 3% on LibriSpeech test-clean, 14% on IEMOCAP, about 35% expected on MELD)
- [x] F11 `pyproject.toml` and a versioned `.githooks/pre-commit`
- [x] F12 Demo samples in the git-ignored `app/static/samples/`, chosen through `data/own/demo_ok.txt`
- [x] F13 Wi-Fi isolation and network-profile risk, with the hotspot or tunnel fallback
- [x] F14 Trial `/export` at the end of the first sitting; the converter is built against it
- [x] F15 Gemini consent, noted in the README
- [x] §17 decisions settled: Gemini free API; optional Cloudflare quick tunnel; duration-weighted overall label; disagreement threshold 0.40; text ensemble by the §8.3 rule

## Plan fixes (done, recorded in specs.md v1.2 §20)

- [x] Text-ensemble rule applied at the start of P6, before the temperatures and fusion weight; +1.0 text-only weighted-F1 on dev Whisper transcripts, and AC-08 and AC-09 kept; `latency.py` built in P6
- [x] §15 matches `CLAUDE.md`: one commit per phase, same flow and stop rules
- [x] Window rule as three cases from P3 timing in both windows: (a) S4 chooses by WER; (b) fixed at 10 s, S4 records the WER cost; (c) `base.en` before P4
- [x] Speech test clips generated once with Windows' text-to-speech and committed in `tests/fixtures/`
- [x] Mains-power check moved to the P3 timing task

## User tasks to do in parallel

- [x] **USER-ANYTIME** **Needed by the Kaggle run:** Kaggle account phone-verified (required for Internet On)
- [ ] **USER-ANYTIME** **Needed by P10:** at the end of the first sitting, run a trial `/export transcript-backup-1.md` (F14)
- [x] **USER-ANYTIME** **Needed by P7:** record 30–50 clips of 3–8 s, with at least 4 per emotion and varied everyday sentences, into `data/own/{emotion}_{nn}.{ext}`. The speakers' consent covers sending the clips to Gemini (F15). *(28 clips, 4 per emotion, 3.5–6.7 s, M4A: two short of 30, noted in `issues.md`.)*
- [x] **USER-ANYTIME** **Needed by P7:** copy `.env.example` to `.env` and add `GEMINI_API_KEY` (never paste it into the chat)
- [x] **USER-ANYTIME** **Needed by P8:** list the clips whose speakers agreed to be demo samples in `data/own/demo_ok.txt`, one file name per line *(7 clips, one per emotion)*

## P1 Scaffold

- [x] `.gitignore`: the initial §13 entries (created with the plan commit)
- [x] `.gitignore`: add `app/static/samples/` and `logs/`
- [x] Folder tree from §13:
  - `src/emotion_analyzer/`, `app/static/samples/`, `scripts/`, `tests/`, `tools/`, `results/`
  - `data/meld/dev/`, `data/own/`, `data/kaggle/`, `models/`, `kaggle/code/`
- [x] `.venv/` built with `py -3.12` (never the 3.14 `python` on PATH)
- [x] `requirements.txt`: the local CPU environment, pinned (CPU-only torch, faster-whisper, transformers, FastAPI, uvicorn, jiwer, ftfy, scikit-learn and the rest)
- [x] `pyproject.toml`: src layout and the pytest `slow` marker; editable install into `.venv` (F11)
- [x] `.githooks/pre-commit` running the fast tests, enabled with `git config core.hooksPath .githooks` (F11)
- [x] `.env.example` containing an empty `GEMINI_API_KEY=`
- [x] `src/emotion_analyzer/__init__.py` and `config.py`, holding:
  - the labels in the fixed order;
  - paths and the window;
  - the disagreement threshold (0.40) and the overall-label rule (duration-weighted);
  - the seeds (0, 1, 2)
- [x] `README.md` stub, plus empty `issues.md` and `insights.md`
- [x] `tests/test_repo_rules.py`: first trivial checks (label order, `.gitignore` entries). The full AC-13 scan comes in P10
- **Done when:** `pytest` passes and the hook runs it on commit; commit "P1: scaffold".

## P2 Data

- [x] `data/meld/dev/`: `archive/dev.tar.gz` and `dev.csv` from `ajyy/MELD_audio`, via `hf_hub_download`
- [x] `src/emotion_analyzer/data.py`, the MELD part:
  - manifests, and the inner join on (`Dialogue_ID`, `Utterance_ID`);
  - `ftfy` text repair;
  - count assertions;
  - unreadable clips, or clips under 0.1 s, dropped and logged in `issues.md`
- [x] `data.py`: CREMA-D and RAVDESS loaders with the §7.2 label maps (RAVDESS from one folder tree, de-duplicated by file name, resampled to 16 kHz)
- [x] `data.py`: own-recordings loader (label read from `{emotion}_{nn}.{ext}`) and the `demo_ok.txt` reader
- [x] `tests/test_data.py`:
  - the dev join gives 1,108 pairs, with `dia110_utt7` missing;
  - the label maps;
  - file-name parsing;
  - text repair never touches the labels
- [x] `insights.md`: a short data report (class counts, durations, defects found)
- **Done when:** the AC-01 logic is tested on dev (1,108 pairs) and the label-map tests pass. AC-01: MELD joins to 9,988 / 1,108 / 2,610 audio–label pairs (train and test are asserted on Kaggle in S2).

## P3 Speech pipeline

- [x] `src/emotion_analyzer/speech.py`: `SpeechPipeline`, which provides:
  - decoding to 16 kHz mono, with the 0.5–120 s limits;
  - VAD on every clip (no speech → `speech_detected: false`);
  - a clip of 10 s or less with speech kept as one segment; longer audio split into 1–10 s segments;
  - the shared encode in both windows;
  - the transcript from the encoder output, with clips longer than the window transcribed in chunks and the text joined (F7);
  - valid frames;
  - per-stage timing
- [x] `src/emotion_analyzer/metrics.py`: WER with Whisper's English normaliser and `jiwer` (the rest of the module comes in P4)
- [x] `tools/make_fixtures.ps1` → `tests/fixtures/`: speech clips generated once with Windows' built-in text-to-speech (System.Speech), WAV 16 kHz mono, under 1 MB in total, committed. At least a short clip (about 4 s) and a long one (about 25 s, with pauses between sentences) for the segmentation and API tests
- [x] `tests/test_speech.py`, using the fixtures: decoding and limits, segmentation rules, frame counts (500 for the 10 s window), the no-speech case. Tests that need weights are marked `slow`.
- [x] WER on 300 local dev clips in both windows → `insights.md`
- [x] Check the laptop is on mains power (ask only if it's on battery), then time per-stage and end-to-end CPU latency on a 5 s clip in both windows → `insights.md`
- [x] Preliminary WER rule (§8.1: WER(10 s) − WER(30 s) ≤ 2.0 points) → `insights.md`
- [x] Window case settled by §8.1, recorded in `insights.md` and `config.py`:
  - (a) small.en meets AC-08 (median ≤ 2.0 s) in both windows: nothing changes, and S4 chooses the window by WER;
  - (b) it meets AC-08 only with the 10 s window: no stop; the window is fixed at 10 s for clips up to 10 s, and S4 records the WER cost instead of choosing;
  - (c) it fails AC-08 even with the 10 s window: switch to base.en, with `specs.md` updated (§20), and repeat the timing for base.en before P4
- **Done when:** the numbers are in `insights.md`, the preliminary WER rule is evaluated, the window case (and with it the model size) is settled, and the tests pass.

## P4 Training code

- [x] `src/emotion_analyzer/features.py`: batched encoder frames, long clips in chunks of up to 10 s, fp16 shards with an index, on CPU or CUDA
- [x] `src/emotion_analyzer/transcribe.py`:
  - batch transcription in both windows, with chunking for long clips, and WER per split;
  - runnable as `python -m`, with an option to process one half of the clip list (one GPU each)
- [x] `src/emotion_analyzer/sound_model.py`:
  - the attention-pooling head (§8.2);
  - its training loop: AdamW, cosine schedule with warm-up, early stopping on dev weighted-F1, frame drop and crop, class weights;
  - inference
- [x] `src/emotion_analyzer/text_model.py`:
  - the RoBERTa classifier (§8.3);
  - its training set: real plus Whisper transcripts, de-duplicated;
  - the training loop, saving every seed's checkpoint (F2);
  - int8 dynamic quantisation, inference, and the optional 3-seed ensemble
- [x] `src/emotion_analyzer/fusion.py`: temperature fitting (F1), weighted log-probability fusion, the weight grid search, the disagreement rule
- [x] `src/emotion_analyzer/metrics.py`: weighted-F1, macro-F1, accuracy, per-class report, confusion matrix, bootstrap CIs, seed mean ± sd, ECE and reliability-diagram data
- [x] `tests/test_models.py`, `tests/test_fusion.py`, `tests/test_metrics.py`
- [x] Local smoke run of every stage on a few dev clips with tiny settings → `insights.md`
- **Done when:** every stage's code runs end to end locally on tiny settings, and the tests pass.

## P5 Kaggle package

- [x] `requirements-kaggle.txt`: pinned `faster-whisper` and `ctranslate2`, `jiwer`, `ftfy`, `huggingface_hub`, `soundfile`, plus the cuBLAS/cuDNN fix from §9.2
- [x] `scripts/package_kaggle.py` → `kaggle/code/`
- [x] `KAGGLE.md`, covering:
  - inputs and settings;
  - the two passes (S0 interactive, then Save & Run All);
  - one config cell at the top, including the P3 window case;
  - S4 choosing the window by WER in case (a), or recording the WER cost of the fixed 10 s window in case (b);
  - cells S0–S8, each complete, with expected output and run time;
  - GPU stages as subprocesses with the corrected `LD_LIBRARY_PATH`;
  - resume markers in `/kaggle/working/state/`, searched in every `/kaggle/input/*/` (F8), and the save-as-dataset alternative;
  - the 11 h guard; both T4s; S7 exporting all three seeds;
  - the final results block;
  - downloading to `C:\Users\adity\Downloads`, with the Kaggle CLI as a fallback
- [x] Local dry-run of the S0–S8 sequence on a tiny subset, on CPU → `insights.md`
- [x] GPU-hours estimate stated in `KAGGLE.md` (§9.4: about 3.2 GPU-hours, about 2 h wall-clock)
- **Done when:** the dry-run passes and the GPU-hours estimate is stated.

## Kaggle run (between P5 and P6)

- [x] **USER** Upload `kaggle/code/` as the private dataset `emotion-analyzer-code`
- [x] **USER** Create the private notebook `emotion-analyzer-train`:
  - add `emotion-analyzer-code`, `ejlok1/cremad` and `uwrfkaggler/ravdess-emotional-speech-audio` as inputs;
  - set Accelerator GPU T4 ×2 and Internet On;
  - paste the cells from `KAGGLE.md`
- [x] **USER** Run only cells 1 and 2 (stage S0) in the editor, download `s0_check.txt` from the Output panel into `C:\Users\adity\Downloads`, and say so *(not done as written: the user committed directly, so S0 ran inside the commit; specs.md §20, v1.3)*
- [x] Read `C:\Users\adity\Downloads\s0_check.txt` and check it against `KAGGLE.md` (the CUDA subprocess test, free disk, the re-estimated times), then give the go-ahead or the fix *(read afterwards from `logs/s0_check.txt` in the outputs: CUDA subprocess test OK with ct2 on the GPU, 21 GB free in /kaggle/working, re-estimate 3.48 GPU-hours, verdict GO)*
- [x] **USER** Save Version → Save & Run All (Commit). If it fails part-way, follow the resume steps in `KAGGLE.md`. *(finished in 1.87 h)*
- [x] **USER** Download `emotion_outputs.zip` into `C:\Users\adity\Downloads` and say so *(the user extracted it into `models/emotion_outputs/`; P6 moved it to `data/kaggle/emotion_outputs/`)*
- **Done when:** `emotion_outputs.zip` is in Downloads.

## P6 Import and parity

- [x] Move `emotion_outputs.zip` from Downloads into `data/kaggle/` and unpack it *(arrived unpacked in `models/emotion_outputs/`; moved to `data/kaggle/emotion_outputs/`)*:
  - `sound_head.pt`, `sound_head.json`, `text_model_seed{0,1,2}/` and `decision.json` into `models/`;
  - `metrics.json` into `results/`;
  - transcripts and per-utterance predictions stay in `data/kaggle/` (F3)
- [x] Training results (`logs/final_results.txt` from the zip, per-run dev and test scores) → `insights.md`
- [x] `src/emotion_analyzer/latency.py` (§10.4): per-stage timing on a 5 s clip and peak memory, for the single-seed or ensemble text configuration
- [x] Text-ensemble rule (§8.3), before anything is fitted → `config.py` and `insights.md` *(ensemble +0.73 < 1.0: seed 0 alone)*:
  - first, text-only weighted-F1 on the dev Whisper transcripts: the 3-seed ensemble (mean of the seeds' probabilities) against the best single seed;
  - only if the ensemble adds ≥ 1.0: check mains power, then run `latency.py` with the ensemble, which must still meet AC-08 and AC-09;
  - otherwise, or if it fails either: the best single seed
- [x] *(Added at the user's request)* Check mains power, then run `latency.py` with the text model in fp32; if it still meets AC-08 and AC-09, deploy it in fp32 (§8.3, v1.3) *(1.71 s median, 1.40 GB peak: fp32 deployed)*
- [x] T_sound, T_text and the fusion weight fitted on the deployed models' dev probabilities (the sound head's Kaggle dev probabilities; the text model's CPU outputs in its deployed precision on Kaggle's dev Whisper transcripts, §8.4 v1.3) → `models/fusion.json` (F1, F9) *(T_sound 0.814, T_text 1.009, w_sound 0.75)*
- [x] `src/emotion_analyzer/evaluate.py`, the parity part: the CPU int8 pipeline on all of MELD dev (features, transcripts, the deployed text model), and the weighted-F1 comparison for sound, text and fused → `results/parity.md` (aggregates only) *(+0.63 / +0.21 / −0.93: pass)*
- [x] Only if the sound gap is over 1.5 points: retrain the head on local CPU-int8 features (§16) → `models/sound_head.pt` *(not needed: +0.63)*
- **Done when:** AC-07 is checked, the deployed text model is recorded, and the training results are in `insights.md`. AC-07: CPU parity, a weighted-F1 difference of at most 1.5 points on dev.

## P7 Evaluation

- [x] Confirm the P7 user tasks are done: clips in `data/own/` and `GEMINI_API_KEY` in `.env`. If not, stop and remind. *(28 clips; key present)*
- [x] `evaluate.py` → `results/results_table.md` and `.csv`: rows R0–R9 (§10.2) with weighted-F1, macro-F1, accuracy, 95% bootstrap CIs and seed mean ± sd (F5) *(R9 54.5; fusion gain +1.9 [+0.6, +3.3])*
- [x] `evaluate.py` → `results/per_class.md` and the confusion matrices `results/confusion_*.png` (150 dpi)
- [x] `evaluate.py` → `results/wer.md`: WER for dev and test in both windows, and the window decision
- [x] `evaluate.py` → `results/calibration.md` and `results/reliability.png`: fused test ECE before and after temperature scaling (AC-16) *(9.51 → 6.04)*
- [x] Check mains power (ask only if on battery), then run `latency.py` on the deployed system → `results/latency.md` *(1.59 s median, 1.40 GB)*:
  - 2 warm-up and 20 timed runs on a 5 s clip;
  - median and p90 per stage and in total;
  - server peak memory
- [x] `evaluate.py` → `results/own_recordings.md`: per-clip predictions, accuracy, weighted-F1, small-sample caveat *(fused 35.7%, text 60.7%, sound 28.6%)*
- [x] `src/emotion_analyzer/chatbot_compare.py` (Gemini free API; ChatGPT by hand only if the API is unavailable) → `results/chatbot.md` *(gemini-3.5-flash on 27 of 28 clips so far, 85.2% against our 37.0%)*:
  - accuracy, weighted-F1 and latency next to ours;
  - the model name and date;
  - a note that it's online and not private
- [ ] Send the last clip (surprise_04) to the same model after the daily quota resets (12:30 IST on 2026-10-21), regenerate `results/chatbot.md` as complete, and commit *(added: the user's choice)*
- [x] `evaluate.py` → `results/error_analysis.md`: 10 MELD test clips where sound and text disagree (transcripts quoted as text), and the confusions per class *(352 disagreements; written discussion added)*
- [x] Results, figures and a verdict on every AC → `insights.md`
- [x] *(Spec v1.4: the user's choice, made after seeing the 36% on the own recordings)* Fusion weight for new speakers (§8.4):
  - MELD's metadata CSVs (no audio) in `data/meld/meta/`, and a speaker loader;
  - T_sound and T_text still fitted on all of dev; w chosen on the 155 dev clips from speakers outside the six main characters → `models/fusion.json`;
  - re-run the parity comparison, the report, latency, the own-recordings evaluation and the chatbot report (no API calls);
  - `own_recordings.md` shows the result before and after, and says the refit came after the 36% result (§10.6);
  - update the error-analysis discussion, the app's About panel and `insights.md` *(w_sound 0.50; R9 55.7; own recordings fused 35.7% → 57.1%)*
- **Done when:** AC-02 to AC-10 and AC-16 are checked and reported:
  - AC-02: WER reported for dev and test in both windows, and the window set by the §8.1 rule (chosen by WER in case (a); fixed at 10 s with its WER cost in case (b))
  - AC-03: sound only (R1), MELD test weighted-F1 ≥ 40.0 (seed mean)
  - AC-04: text on real transcripts (R4) ≥ 58.0 (seed mean)
  - AC-05: fused with Whisper transcripts (R7) ≥ 52.0 and ≥ text on Whisper transcripts (R5), both seed means
  - AC-06: every model row beats the majority baseline (31.3 weighted-F1)
  - AC-07: CPU parity within 1.5 points on dev (checked in P6, reported here)
  - AC-08: median ≤ 2.0 s per 5 s clip end to end, on mains power (stretch ≤ 1.2 s)
  - AC-09: server peak memory ≤ 2.5 GB
  - AC-10: own recordings evaluated, and the chatbot comparison done on the same clips
  - AC-16: fused test calibration error reported before and after temperature scaling, with the reliability diagram
  - Any failed criterion is reported with its measured value, never hidden.

## P8 App

- [x] Copy the clips listed in `data/own/demo_ok.txt` into `app/static/samples/`. If the file is missing, stop and remind. *(7 clips and index.json)*
- [x] `app/main.py`: FastAPI, with the models loaded once at start-up, `GET /`, `GET /api/health`, `POST /api/analyze`, and errors 400 / 413 / 422 in the §5.3 shape
- [x] `app/static/index.html`, `app.js` and `style.css`, with:
  - record and upload;
  - the fused result card, and the "How it sounds" and "What was said" cards;
  - transcript, disagreement banner, and the timeline for recordings over 10 s;
  - processing time, demo samples, and the About panel (citations and limitations);
  - a phone-width layout and no CDNs
- [x] `tests/test_api.py`: normal clip, silence, long recording (segmented), unsupported format, too large, too short. Speech comes from the committed `tests/fixtures/` clips; silence, too short, too large and unsupported inputs are built in the test; no MELD audio, and no text-to-speech at run time. *(8 tests, including one slow test on the real models; all pass)*
- [x] Start the app locally and give the user the link *(http://localhost:8443, HTTP until P9 adds the certificate)*
- [x] *(Spec v1.5, the user's request for the class demo)* JSON aggregates for the web page in `results/`, from `evaluate report`, `evaluate own` and `chatbot_compare`. Own recordings and the chatbot are re-rendered from their saved results (`--reuse`): no new analysis and no API calls *(six new `.json` files; the `.md` and `.png` outputs are unchanged)*
- [x] `app/report.py` and `GET /api/report` (§5.3): assembled once at start-up from `results/` and `models/fusion.json`; aggregates only; missing sections marked unavailable
- [x] Presentation-grade page (§5.4, v1.5), plain HTML, CSS and JavaScript, no CDNs:
  - three tabs: Try it, How it works, Results;
  - Try it: level meter and timer while recording, Space to start and stop, drag and drop, animated bars, session history, demo clips with true labels and right/wrong marks, Run all demos with a scoreboard;
  - How it works: the SVG pipeline with the last analysis's stage timings and the deployed T and w, plus why two models are fused;
  - Results: R0–R9 with R9 highlighted, per-class F1, three confusion matrices, WER, calibration, latency against AC-08 and AC-09, own recordings, the chatbot comparison (partial while clips are missing), what it does that a chatbot can't, limitations;
  - one colour and emoji per emotion everywhere, light and dark themes, projector-sized text, phone width
- [x] `tests/test_api.py`: the report endpoint (sections, aggregates only, missing files) and no external resources in the page; the AC-11 tests still pass *(66 fast tests and the slow API test pass)*
- [x] Restart the app with the new page and give the user the link *(http://localhost:8443)*
- [x] **USER** Try the app locally (record and upload) and give feedback *(2026-10-20: all three tabs work: recording with Space, upload, drag and drop, the demo clips, Run all demos, the history, the theme button and the Results tab)*
- **Done when:** AC-11 passes and the user has tried the app. AC-11: the API tests pass for a normal clip, silence, a long recording, an unsupported format, a file that is too large and one that is too short.

## P9 Deployment

- [ ] Port 8443 confirmed free → `insights.md`
- [ ] `scripts/make_cert.py` → `certs/key.pem` and `certs/cert.pem` (SANs `localhost`, `127.0.0.1` and the current LAN IP)
- [ ] `scripts/serve.ps1`: activates the venv, checks the models are present, starts uvicorn on 8443 with one worker, prints the LAN and localhost URLs
- [ ] `scripts/tunnel.ps1`: the Cloudflare quick tunnel
- [ ] `scripts/smoke.ps1`: calls `/api/health` and `/api/analyze` through the real LAN address
- [ ] Access log in `app/main.py`: one line per request to `logs/server.log` (time, client IP, user agent, endpoint, status, processing time, `CF-Connecting-IP` when present)
- [ ] `scripts/offline_check.ps1`: sets `HF_HUB_OFFLINE=1`, starts the server, analyses a demo clip on `https://localhost:8443`, writes `results/offline_check.txt`, then stops the server
- [ ] `README.md`, the "Running in production" section, covering:
  - the firewall line;
  - setting the Wi-Fi to Private;
  - the hotspot fallback (F13);
  - the working directory before every command
- [ ] **USER** In an administrator PowerShell, add the inbound rule for TCP 8443 on the Private profile, and set the Wi-Fi network to Private
- [ ] **USER** Open the app on your phone on the same Wi-Fi, accept the certificate warning once, then test upload and record. Also open the tunnel's `trycloudflare.com` address on mobile data.
- [ ] **USER** Offline check, while this session is idle (the session itself needs the internet):
  1. Switch Wi-Fi off.
  2. Run `scripts/offline_check.ps1`.
  3. Switch Wi-Fi back on.
  4. Say it's done.
- [ ] Deployment check from `logs/server.log` (the phone's requests over Wi-Fi, with upload and record, and through the tunnel) and the offline result from `results/offline_check.txt` → `insights.md`
- **Done when:** AC-12 is verified from a phone and AC-17 is checked.
  - AC-12: the app is reachable from a phone on the same Wi-Fi over HTTPS, and analysis works (upload and record); the internet link works.
  - AC-17: with Wi-Fi off and `HF_HUB_OFFLINE=1`, the server starts and analyses a clip on localhost.

## P10 Wrap-up

- [ ] `README.md` complete: install, run, train (via `KAGGLE.md`), deploy, the Gemini consent note (F15), citations (§18)
- [ ] `specs.md` matches the build, with every change recorded in §20
- [ ] `tests/test_repo_rules.py`: the AC-13 scan (the only audio tracked in git is `tests/fixtures/`; no MELD audio among the demo samples; no banned checkpoint in code or config)
- [ ] Final full test run, including `slow` → `insights.md`
- [ ] Fresh-clone walkthrough of the README (install, tests, serve) → `insights.md`
- [ ] `tools/transcript_to_html.py`, built and tested against the trial export (F14), with the session's `.jsonl` log as the fallback source
- [ ] **USER** Read the README end to end and confirm a new user could follow it (the AC-14 manual check)
- [ ] **USER** Run `/export transcript.md` at the end of the session
- [ ] `transcript.html` built from `transcript.md`: "Turn N" headings, each response in a collapsed block, the turn count checked against the user's messages; commit
- **Done when:** AC-13 to AC-15 pass.
  - AC-13: no MELD audio in git or in the demo samples, and no banned checkpoint anywhere in the code (a test scans the repository and config)
  - AC-14: the README lets a new user install, run, train (via `KAGGLE.md`) and deploy from scratch (manual check)
  - AC-15: the transcript is exported and converted to `transcript.html`, with Turn N headings and collapsed responses
