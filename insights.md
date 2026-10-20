# Insights

Results, figures and decisions with numbers, phase by phase.

## P1 Scaffold

- Environment: Python 3.12.10 venv, torch 2.14.1+cpu, faster-whisper 1.2.1 (ctranslate2 4.8.3), transformers 5.20.2. All pinned in `requirements.txt`.
- Every API from §6.1 exists in these versions: `decode_audio`, `pad_or_trim`, `Tokenizer`, `get_speech_timestamps`, `WhisperModel.encode`. So do `quantize_dynamic` and transformers' `EnglishTextNormalizer`.

## P2 Data

MELD dev, downloaded locally from `ajyy/MELD_audio` (`archive/dev.tar.gz` and `dev.csv`) into `data/meld/dev/`:

- The archive holds 1,112 FLAC files (16 kHz mono) and the CSV has 1,109 rows. The inner join gives **1,108 pairs**, as §7.1 expects (AC-01 on dev).
- `dia110_utt7` is the only CSV row with no audio (the known defect). Four audio files have no CSV row and are ignored: `dia49_utt4`, `dia49_utt5`, `dia66_utt9`, `dia66_utt10`.
- Two joined clips are 0.064 s long, under the 0.1 s floor, so they are dropped and logged in `issues.md`: `dia99_utt3` ("Ooohhhh!!", surprise) and `dia108_utt5` ("Ow!", anger). That leaves **1,106 usable dev clips**.
- Class counts after the drops: anger 152, disgust 22, fear 40, joy 163, neutral 469, sadness 111, surprise 149. The join alone gives the paper's counts minus the missing clip; the test checks this.
- Durations: mean 3.13 s, median 2.46 s, min 0.13 s, max 28.5 s, 57.7 minutes in total. 23 clips (2.1%) are over 10 s and none over 30 s, which matches the CSV-timestamp estimate behind §8.1.
- Text repair: `ftfy` changed 308 of 1,109 utterances. The artefacts here are Windows-1252 bytes such as `\x92` for an apostrophe ("he\x92s" becomes "he's"). Labels are untouched.
- Speakers: 47, led by the main cast (Ross 217, Phoebe 183, Rachel 164, Joey 149, Monica 137, Chandler 101).
- Loaders for CREMA-D and RAVDESS (label maps, RAVDESS de-duplication by file name, speech only) and for the own recordings and `demo_ok.txt` are tested on synthetic files. The real corpora are only read on Kaggle (S2).

## P3 Speech pipeline

**Shared Whisper pass.** faster-whisper small.en int8 on the laptop CPU loads in 2.7 s, and the process uses about 0.45 GB. On the 4.97 s fixture, both windows give the same transcript ("I can't believe you did that. That was the best surprise ever.") and 249 valid frames (T × 768). A 10 s window gives encoder output of shape (1, 500, 768), as §6.1 states.

**Segmentation (§5.2).** VAD runs on every clip. Pure silence gives no segments, so `speech_detected` is false. The 4.97 s fixture is one segment. The 24.1 s fixture splits into three segments: 0–7.9 s, 9.5–18.1 s and 19.6–22.5 s.

**Chunking long clips (§8.1, §8.2).** Equal-length chunks cut a word on the long fixture ("because you are all here" was lost at an 8 s boundary). `chunk_audio` now moves each cut to the quietest 20 ms frame within 1.5 s of the equal split, and the full sentence comes back.

**WER on 300 random MELD dev clips** (seed 0; Whisper normaliser and `jiwer`; corpus WER):

| Window | WER | Substitutions | Deletions | Insertions | CPU s/clip |
|---|---:|---:|---:|---:|---:|
| 10 s | 26.52% | 198 | 175 | 331 | 0.40 |
| 30 s | 23.65% | 193 | 168 | 267 | 1.56 |

- The two windows give identical hypotheses on 63.7% of clips. The 10 s window's extra errors are mostly insertions and a few garbled short clips ("Good." became "the").
- On the 6 sampled clips over 10 s, the chunked 10 s transcripts are better (7.7% against 11.2%). The 10 s window's deficit comes from short clips.
- WER is below the expected 35%. This is a sample of 300; S3 measures the full splits.
- **Preliminary WER rule:** WER(10 s) − WER(30 s) = +2.87 points, which is more than 2.0, so the rule points to the 30 s window. S4 decides on the full dev set.

**End-to-end CPU latency** (on mains power, 5 s fixture, 2 warm-up and 20 timed runs). The text and sound stages use same-sized untrained models: int8 RoBERTa-base and a random attention-pooling head.

| Window | decode + VAD | encode | transcribe | sound | text | fusion | **total, median / p90** |
|---|---:|---:|---:|---:|---:|---:|---:|
| 10 s | 117 | 283 | 140 | 2 | 18 | 0 | **558 / 583 ms** |
| 30 s | 123 | 1,309 | 272 | 2 | 20 | 0 | **1,711 / 1,930 ms** |

Peak memory in that process was 1.86 GB, including loading RoBERTa in fp32 before quantising it.

**Window case (§8.1): (a).** small.en meets AC-08 (median ≤ 2.0 s) in both windows. Nothing changes: the model stays small.en and S4 chooses the window by WER. The preliminary choice is 30 s, which would meet AC-08 with about 0.3 s to spare but miss the 1.2 s stretch target. Recorded in `config.py` (`WINDOW_CASE = "a"`).

## P4 Training code

**Smoke run of every stage** (local CPU, int8; 36 train / 14 dev / 14 test clips drawn from MELD dev, plus 8 more as a stand-in for the acted corpora; 376 s in total):

| Stage | What ran | Result |
|---|---|---|
| S2 | manifests from the MELD loader | 4 CSVs with `id`, `path`, `label_id` |
| S3 | `transcribe` in both windows; train split in two parts (`--parts 2`), then `--merge` | WER train 34.2 / 37.0, dev 19.1 / 16.4, test 21.4 / 19.7 (10 s / 30 s); about 0.36 s and 1.5 s per clip |
| S4 | `transcribe --decide --case a` | dev gap +2.73, so the 30 s window was chosen; `decision.json` written |
| S5 | `features` in the chosen window (MELD, the acted stand-in) and in the other window (ablation W); train in two parts; a rerun skipped the existing shards | 31 MB of fp16 shards; about 1.3 s per clip at 30 s on CPU |
| S6 | `sound_model`: main ×2 seeds, A, W (4 epochs) | dev weighted-F1 28.6–29.2; checkpoint, history and `pred_{dev,test}.npz` per run |
| S7 | `text_model`: main seed 0 (saved, fp16 safetensors) and T (real only, not saved), 1 epoch | 67 and 36 training examples; `pred_{dev,test}_{real,whisper}.npz` |
| Fusion | `fusion --sound … --text …` | T_sound 0.95, T_text 20 (the upper bound: a 1-epoch text model is near-constant), w_sound 0.25 |
| Deployed path | `SoundClassifier` + int8 `TextClassifier` + `Analyzer` on both fixtures | §5.3 responses: 1 segment (short) and 3 segments (long), with timings and model names |

- The tiny scores mean nothing. One epoch on 67 examples leaves RoBERTa predicting one class. The smoke run checks that every stage's code runs, not how well it learns.
- The unit tests cover the rules themselves:
  - the majority baseline reproduces R0 (accuracy 48.1, weighted-F1 31.3);
  - temperature fitting recovers T = 2.5 on synthetic data;
  - the weight search breaks ties toward the smallest w;
  - padding doesn't change the sound head's output;
  - the head has about 0.27 M parameters;
  - text-model training and int8 quantisation run, and the quantised layers are `torch.ao.nn.quantized.dynamic.Linear`.
- The transformers fallback (§9.2) runs the same pipeline through `openai/whisper-*`: features from faster-whisper's extractor and the encoder layers run directly, so the 10 s window works. Tested with tiny.en on CPU, where both windows return the right transcript and 249 frames. S3 and S5 pass it with `--backend hf`.
- Transcripts now carry the manifest `id`, so the text and sound predictions join on the same key (`fusion.align` checks that the labels agree).

## P5 Kaggle package

- `scripts/package_kaggle.py` builds `kaggle/code/`:
  - the dataset tree, plus `emotion-analyzer-code.zip` (36 kB, 12 modules, `requirements-kaggle.txt`, `CODE_VERSION.json` with the git commit);
  - `emotion-analyzer-train.ipynb`;
  - the cells as plain files.

  The cells come from `KAGGLE.md`, so the notebook and the document can't drift apart.
- **Local dry run** (`package_kaggle.py --dry-run`, laptop CPU): cells C and S0–S8 run in one Python process, as in a notebook kernel. The settings were 12 clips per split, 2 seeds, 3 sound epochs and 1 text epoch, with stand-ins for the acted corpora (RAVDESS with its duplicated tree).
  - **Pass 1:** 410 s. S0 took 147 s: it downloaded and extracted 32 dev clips, ran the subprocess transcription test in both windows, timed features and benchmarked training.
  - S3 transcribed in two parts and merged them. S4 chose a window. S5 built 7 feature sets. S6 ran 6 sound runs and S7 ran 4 text runs. S8 wrote `metrics.json`, the final results block and `emotion_outputs.zip`: 106 files, 0.50 GB with 2 text seeds, so about 0.75 GB with 3.
  - **Pass 2, resumed:** 172 s. A fresh session had the first output attached as an input. All 14 finished stages were reused (S3 ×3, S4, S6 ×6, S7 ×4) and S5 was skipped, since no sound run was left. S8 exported again.
  - `/kaggle/working` after pass 1 was 0.97 GB with 2 text seeds, so about 1.5 GB with 3, inside the 2 GB target (§9.5).
- **Memory:** a batch of 32 full 30 s windows doesn't fit the laptop's free RAM and dies silently. The cells use `BATCH = 16` on Kaggle (fp16, 15 GB T4) and 4 in the dry run.
- **GPU-hours:** about 3.2 GPU-hours and 2 h wall-clock (§9.4, stated in `KAGGLE.md`). S0 re-measures on the T4s and prints a go/check verdict against the 6 GPU-hour budget and the 11 h guard. On the laptop CPU it estimates about 18 GPU-hours and reads CHECK, as expected.

## Kaggle run

- **One pass instead of two.** The user committed the notebook directly with Save & Run All and skipped the interactive S0 check. S0 ran at the top of the commit and its report (`logs/s0_check.txt` in the outputs) was read afterwards:
  - 2× Tesla T4 (15 GB each), 34 GB RAM, 21 GB free in `/kaggle/working`, 1,146 GB in `/tmp`;
  - Python 3.13.15, torch 2.11.0+cu128; the pinned extras installed, with cuBLAS 12.8.4.1 and cuDNN 9.19.0.56;
  - **CUDA subprocess test: OK, backend ct2 on the GPU**, so the transformers fallback wasn't needed (`metrics.json`: backend ct2, 2 GPUs);
  - measured per clip: transcription 0.136 s (10 s window) and 0.126 s (30 s), features 0.062 s and 0.094 s, sound step 0.040 s, text step 0.093 s;
  - re-estimate 3.48 GPU-hours and 1.89 h wall-clock against the 6 GPU-hour budget: GO.
- **Actual run: 1.87 h**, every stage finished, nothing skipped. The zip was 731 MB unpacked.
- **AC-01 on the full data:** S2's assertions passed, so MELD joined to 9,988 / 1,108 / 2,610 pairs. After dropping clips under 0.1 s (12 in train, 2 in dev, none in test), 9,976 / 1,106 / 2,610 clips were used. CREMA-D gave 7,441 clips and RAVDESS 1,440 after de-duplicating its two trees.
- **Window (S4, case a):** WER(10 s) − WER(30 s) = +5.85 points on dev (31.88% against 26.03%), more than the 2.0 limit, so the window is **30 s**. On test the gap is +10.30 (43.68% against 33.38%). The 10 s window's extra errors are mostly insertions (test: 6,290 against 4,029).

**Training results** (`logs/final_results.txt`; weighted-F1, seed mean ± sd; seeds in brackets are dev / test per seed):

| Row | Run | Dev | Test | Per seed, dev / test |
|---|---|---:|---:|---|
| R0 | majority | – | 31.3 | – |
| R1 | sound main | 52.3 ± 0.8 | 52.3 ± 0.4 | 52.37/52.07, **53.13**/52.17, 51.54/52.80 |
| R2 | sound + acted (A) | 51.6 ± 0.8 | 50.9 ± 0.3 | 52.27/50.64, 50.69/51.17, 51.88/50.92 |
| R3 | sound, 10 s window (W) | 51.2 ± 0.4 | 51.4 ± 0.9 | 51.40/52.46, 51.55/50.73, 50.76/50.89 |
| R4 | text, real transcripts | 59.0 ± 2.0 | 61.5 ± 0.8 | 60.74/62.19, 59.49/61.63, 56.82/60.61 |
| R5 | text, Whisper transcripts | 50.0 ± 0.2 | 52.3 ± 0.5 | **50.30**/52.64, 49.95/52.55, 49.89/51.80 |
| R6 | text, real-only training (T) | 49.9 ± 0.7 | 52.1 ± 1.5 | 50.67/52.62, 49.41/50.39, 49.58/53.31 |

- The sound branch is far above the expected 40–46 (§10.9): the frozen Whisper encoder carries lexical as well as acoustic information. Adding the acted corpora (A) costs 1.4 points on test, and the 10 s window's features (W) cost 0.9.
- The sound heads stop early: best dev epoch 2–5, stopped at 8–11 epochs (patience 6). The main text seeds peak at epoch 1–2 on dev Whisper transcripts and then overfit; real-only training (T) peaks later (epoch 2–5).
- Training on Whisper transcripts as well as real ones (R5 against R6) gains only +0.2 on test, within the seed spread.
- Kaggle's provisional fusion (per-seed weight and temperatures fitted on dev) gave 55.1 ± 0.5 on test.

## P6 Import and parity

- **Import.** The outputs moved from `models/emotion_outputs/` to `data/kaggle/emotion_outputs/`. `sound_head.pt` and `.json` (main seed 1, dev 53.13, 10 epochs), `text_model_seed{0,1,2}/` (fp16 safetensors, 249 MB each) and `decision.json` were copied into `models/`, and `metrics.json` into `results/`. Transcripts and per-utterance predictions stay in `data/kaggle/`.
- **Text-ensemble rule (§8.3)**, on the Kaggle dev Whisper-transcript predictions: seeds 50.30 / 49.95 / 49.89, ensemble 51.03, so the gain over the best seed (seed 0) is **+0.73 < 1.0**. The deployed text model is **seed 0 alone** (`config.TEXT_SEEDS_DEPLOYED`), and the ensemble latency check isn't run. For reference, the ensemble's test score would have been 52.79 against 52.64.
- **Text precision on the CPU.** The spec planned int8 dynamic quantisation (§8.3). Measured on the dev Whisper transcripts with seed 0:

  | Text model, seed 0 | Weighted-F1 | Same label as Kaggle | Mean top probability | ECE |
  |---|---:|---:|---:|---:|
  | Kaggle, fp16 on the GPU | 50.30 | – | 0.547 | 3.77 |
  | Laptop, fp32 on the CPU | 50.19 | 99.9% | 0.547 | 3.96 |
  | Laptop, int8 per-tensor (the v1.0 plan) | 49.01–49.40 | 85.2% | 0.388 | 13.56 |
  | Laptop, int8 per-channel weights (tried) | 49.97 | 84.3% | 0.397 | 13.82 |

  - Int8 flattens the probabilities, and per-channel weights don't fix that, so the activation quantisation is the cause.
  - Int8 results also depend on batching: the activation scale is per batch, so the same sentences scored in a different order gave 49.01 and 49.40. The app scores one sentence at a time.
  - First step (v1.3): kept int8 and fitted T_text on the int8 outputs: T_text 0.656, w_sound 0.60, dev fused 54.67. On test that gave R9 54.58, against 53.71 with the fp16-fitted temperature, and text ECE 5.9 against 16.0.
  - **Final (v1.3, the user's decision):** time fp32 on mains power and deploy it if it keeps AC-08 and AC-09. It does (2 warm-up and 20 timed runs on the 5 s fixture, same session):

    | Text model | Median total | p90 | Text stage | Peak memory |
    |---|---:|---:|---:|---:|
    | int8 | 1,566 ms | 1,721 ms | 19 ms | 1.90 GB |
    | **fp32 (deployed)** | **1,714 ms** | **1,762 ms** | 29 ms | **1.40 GB** |

    The text stage costs 10 ms more; most of the 150 ms total gap is run-to-run noise in the Whisper encode (1,177 against 1,284 ms). fp32 uses less memory because nothing is quantised after loading. `config.TEXT_PRECISION = "fp32"`.
- **Temperatures and weight (§8.4)**, fitted on the deployed models' dev probabilities: the sound head's Kaggle dev probabilities, and the fp32 text model's CPU outputs on Kaggle's dev Whisper transcripts. **T_sound 0.814, T_text 1.009, w_sound 0.75**; dev weighted-F1 sound 53.13, text 50.19, fused **55.58** → `models/fusion.json`. No temperature is at a bound. This matches the fit on Kaggle's fp16 text probabilities (kept as `fp16_text_reference`), as expected when fp32 reproduces fp16.
- **CPU parity (AC-07): pass** (`results/parity.md`). The full laptop path ran on all 1,106 dev clips: small.en int8 encode, frames and transcript from one shared encode per clip, sound head, fp32 text model. 1.81 s per clip, 33 minutes.

  | Branch | Kaggle fp16 | Laptop CPU | Difference |
  |---|---:|---:|---:|
  | sound | 53.13 | 53.76 | +0.63 |
  | text | 50.30 | 50.51 | +0.21 |
  | fused | 55.66 | 54.73 | −0.93 |

  - The same label on both paths: sound 98.4% of clips, text 97.2% (83.8% with int8). Transcripts are 87.3% identical, and WER is 26.03% on Kaggle against 26.07% on the laptop.
  - The sound gap is under 1.5, so the head isn't retrained (§16).
  - With int8 text, parity also passed (sound +0.63, text +0.20, fused −0.91).
- `latency.py` times the deployed system (`fusion.load_analyzer`, the object the app serves): 2 warm-up and 20 timed runs, per-stage median and p90, and peak memory. `--text-seeds 0 1 2` times the ensemble and `--text-precision` either precision.

## P7 Evaluation

All on MELD test (2,610 utterances) unless stated. The deployed system has the sound head (main, seed 1), the text model (seed 0, fp32 on the CPU) and `models/fusion.json` (T_sound 0.814, T_text 1.009, w_sound 0.75).

- **Results table** (`results/results_table.md`), weighted-F1 as the seed mean ± sd, with the 95% bootstrap interval of the seed mean:

  | Row | Condition | Weighted-F1 | 95% CI |
  |---|---|---:|---|
  | R0 | Majority (neutral) | 31.3 | 29.4–33.2 |
  | R1 | Sound only | 52.3 ± 0.4 | 50.3–54.1 |
  | R2 | Sound, plus acted corpora | 50.9 ± 0.3 | 49.1–52.6 |
  | R3 | Sound, 10 s window | 51.4 ± 0.9 | 49.4–53.1 |
  | R4 | Text, real transcripts | 61.5 ± 0.8 | 59.8–63.2 |
  | R5 | Text, Whisper transcripts | 52.3 ± 0.5 | 50.5–54.0 |
  | R6 | Text trained on real only, Whisper | 52.1 ± 1.5 | 50.1–53.9 |
  | R7 | Fused, Whisper | 54.2 ± 0.2 | 52.3–56.0 |
  | R8 | Fused, real transcripts | 57.9 ± 0.9 | 56.0–59.7 |
  | R9 | Deployed system (one run) | 54.5 | 52.4–56.4 |

- **The fusion gain is real but small.** Measured as a paired bootstrap of the seed means on the same resampled utterances:
  - R7 − R5 is +1.9 points [+0.6, +3.3].
  - R7 − R1 is +1.9 [+1.2, +2.5].

  This is inside the +0.5 to +2.5 typically reported on MELD (§10.9). The branches give the same label on 64% of test clips.
- **Ablations, none of which helps on MELD test:**
  - Adding CREMA-D and RAVDESS to the sound training costs 1.4 points (R2 against R1). The acted corpora are a different domain, and RAVDESS calm became neutral.
  - The 10 s window costs 0.9 points for sound (R3 against R1). This agrees with the window chosen by WER.
  - Training the text model on real transcripts only (R6) is 0.2 points below training it on both, within the noise (sd 1.5).
- **Whisper errors cost text 9.2 points** (R4 61.5 against R5 52.3) and fused 3.7 points (R8 57.9 against R7 54.2). The sound branch makes up part of what the transcripts lose.
- **The sound branch scores above the published range.** It gets 52.3 against the 40–46 expected in §10.9. Two likely reasons, not proven here:
  - The Whisper encoder is a speech-recognition model, so its frames carry what was said as well as how it sounded.
  - MELD's train and test splits share the six main Friends speakers, so the head can learn speaker-specific habits.

  Both inflate MELD test scores relative to new voices. That matches the own-recordings result below, where the sound branch fell to 28.6% accuracy.
- **Per class (fused, R9):**
  - F1: neutral 70.9, surprise 48.8, joy 44.5, anger 42.2, sadness 26.6, fear 14.9, disgust 12.5.
  - Neutral is the most common wrong answer for every class.
  - Text finds sadness far better than sound (recall 32.2% against 14.4%).
  - Written discussion: `results/error_analysis.md`.
- **Disagreements:** 352 test clips (13.5%) are flagged. On those, the fused answer is right 44.0% of the time, against 58.9% on the rest.
- **Calibration (AC-16):** fused test ECE is 9.51 before temperature scaling and 6.04 after (NLL 1.257 → 1.242). Sound goes 7.70 → 4.39 and text 2.42 → 1.98. The reliability diagram is `results/reliability.png`.
- **Latency (AC-08, AC-09):** measured on mains power on the deployed system with fp32 text, 2 warm-up and 20 runs on the 5 s fixture.
  - Median 1,590 ms, p90 1,644 ms.
  - The Whisper encode is 1,180 ms of that, transcription 260 ms, decoding and VAD 122 ms, and text 28 ms.
  - Peak memory 1.40 GB; loading takes 10.6 s.
- **Own recordings (§10.6):** 28 acted clips, 4 per emotion. Accuracy is 28.6% for sound, 60.7% for text and 35.7% for fused (95% CI 17.9–53.6). Chance is 14.3%.
  - The text branch transfers; the sound branch mostly answers neutral.
  - Because w_sound is 0.75, the fused answer follows the weak sound branch and ends up 25 points below text alone.
  - With 28 clips the intervals are wide, but the direction is clear: on new voices, the app's fused answer is less reliable than its text branch.
- **Chatbot (§10.7):** Gemini `gemini-3.5-flash` (the API reported serving `gemini-3.6-flash`), through the free API with default settings and the §10.7 instruction, has answered **27 of the 28** recordings so far. Both free-tier keys ran out of their 20-a-day quota on that model. The last clip, surprise_04, is sent after the quota resets, and the report is then regenerated as complete.

  On the same 27 clips:

  | System | Accuracy | 95% CI | Weighted-F1 | Median latency |
  |---|---:|---|---:|---:|
  | Ours, fused | 37.0 | 18.5–55.6 | 30.7 | 1.60 s on the CPU, offline |
  | Gemini | 85.2 | 70.4–96.3 | 84.7 | 15.5 s online |

  - Gemini missed 4 clips (anger_03 → sadness, disgust_03 → fear, disgust_04 → anger, fear_04 → sadness) and never answered outside the labels.
  - On these acted, clearly worded clips, Gemini is far more accurate than our system, and even than our text branch alone (60.7%).
  - Its latency includes busy-service retries; the slowest answer took 105 s.
  - It sends the audio to Google, and the free tier may use it for training. Our system is offline, private and about 10 times faster.
- **Acceptance criteria:**

  | AC | Criterion | Measured | Verdict |
  |---|---|---|---|
  | AC-01 | MELD joins | 9,988 / 1,108 / 2,610 (P2) | pass |
  | AC-02 | WER for dev and test in both windows; window by the §8.1 rule | dev 31.88 / 26.03, test 43.68 / 33.38; case a, gap +5.85 > 2.0 → 30 s | pass |
  | AC-03 | R1 ≥ 40.0 | 52.3 | pass |
  | AC-04 | R4 ≥ 58.0 | 61.5 | pass |
  | AC-05 | R7 ≥ 52.0 and ≥ R5 | 54.2 against R5 52.3 (gain +1.9 [+0.6, +3.3]) | pass |
  | AC-06 | Every model row > 31.3 | lowest R2 50.9 | pass |
  | AC-07 | CPU parity ≤ 1.5 on dev | +0.63 / +0.21 / −0.93 | pass |
  | AC-08 | Median ≤ 2.0 s per 5 s clip (stretch ≤ 1.2 s) | 1.59 s | pass; stretch not met |
  | AC-09 | Peak memory ≤ 2.5 GB | 1.40 GB | pass |
  | AC-10 | Own recordings and chatbot on the same clips | own: 28 clips, fused 35.7% accuracy; chatbot: Gemini on the same clips, 27 of 28 so far (85.2% against our 37.0%) | pass, provisional until the last clip is in |
  | AC-16 | Fused ECE before and after, with the diagram | 9.51 → 6.04 | pass (reported) |

  AC-11 to AC-15 and AC-17 belong to P8–P10.

## P7 rework: fusion weight for new speakers (spec v1.4)

- **Why:** on the user's 28 recordings the app was right 35.7% of the time, while the text branch alone got 60.7%, because w_sound 0.75 let the sound branch outvote the text. The user chose this refit **after seeing that result**. The recordings weren't used to choose the new weight, but they are no longer a blind test; `own_recordings.md` says so.
- **Speaker check** (MELD's CSVs, no audio, in `data/meld/meta/`):
  - Train has 260 speaker names. The six main characters are 86% of dev.
  - Only 36 dev clips (3.3%, 14 speakers) and 109 test clips (4.2%, 31 speakers) come from speakers never seen in train.
  - Seed-mean dev weighted-F1 of the sound head is 51.7 on the main six, 55.9 on other speakers and 62.2 on unseen ones. **The sound head doesn't get worse on new MELD speakers**, so speaker overlap isn't the cause of the drop on the own recordings. The likelier cause is the recording conditions (phone microphone, acted, no TV mix).
- **Weight options checked on dev:**
  - The 36 unseen-speaker clips give w 0.80, which varies from 0.30 to 0.80 under resampling, so they were rejected.
  - The 155 clips from speakers outside the main cast give **w 0.50** (61.97 on those clips, against 59.2 at 0.75), stable from 0.50 to 0.70 under resampling. Text is as good as sound on them (55.1 against 53.8 for the deployed models).
- **New `models/fusion.json`:** T_sound 0.814 and T_text 1.009 (still all of dev), **w_sound 0.50**. Dev fused weighted-F1 is 55.24, against 55.58 at 0.75.
- **MELD test** (the weight was not chosen on test):

  | Row | w_sound 0.75 (v1.3) | w_sound 0.50 (v1.4) |
  |---|---:|---:|
  | R7 fused, Whisper | 54.2 ± 0.2 | **55.5 ± 0.3** |
  | R8 fused, real transcripts | 57.9 ± 0.9 | **62.3 ± 0.4** |
  | R9 deployed system | 54.5 | **55.7** (95% CI 53.6–57.6) |
  | Fusion gain R7 − R5 | +1.9 [+0.6, +3.3] | **+3.1 [+2.2, +4.1]** |
  | Fused ECE before → after scaling | 9.51 → 6.04 | 7.91 → 5.40 |
  | Fused sadness recall | 19.2% | 31.2% |

  Weighting on all of dev suited the main six and cost the text-heavy classes. The more even weight is better on MELD test too.
- **Parity (AC-07):** the fused gap is now −0.46 (Kaggle 55.24, laptop 54.77); sound and text are unchanged. Pass.
- **Own recordings** (scored before and after the refit, timed on mains):

  | Output | Before | After |
  |---|---:|---:|
  | Sound | 28.6% | 28.6% |
  | Text | 60.7% | 60.7% |
  | Fused | 35.7% (wF1 29.8) | **57.1% (wF1 58.0)** |

  The app is still 3.6 points (one clip) below the text branch on new voices, and the sound branch itself still doesn't carry over. The next step, if wanted, is option 3: retrain the sound head with recording-condition augmentation, which needs a Kaggle run.
- **Chatbot** (the same 27 clips): ours 37.0% before and **55.6%** after, against Gemini's 85.2%.
- **Latency (mains):** median 1,648 ms, p90 1,710 ms, 1.40 GB peak, unchanged by the weight. The own-recordings pass runs at 1.68 s per clip.
- **Acceptance criteria after v1.4:** all the same verdicts.
  - AC-05 now passes more clearly (R7 55.5 against R5 52.3).
  - AC-07 fused −0.46. AC-08 1.65 s. AC-16 7.91 → 5.40.
  - AC-10 is still provisional until Gemini's last clip.

## P8 App (spec v1.5: the presentation-grade page)

- **JSON aggregates** for the Results tab: `results_table`, `per_class`, `wer`, `calibration`, `own_recordings` and `chatbot` `.json`, next to the existing `latency.json` and `parity.json`.
  - Regenerating them left every `.md` and `.png` in `results/` unchanged.
  - Own recordings and the chatbot were re-rendered from their saved results: no new analysis and no API calls.
- **`GET /api/report`** is about 13.6 KB, assembled once at start-up, field by field from a whitelist. A test plants clip ids, transcripts and file names in the inputs and checks that none reach the output.
- **A new aggregate: the disagreement flag on MELD test.** It comes up on 352 clips (13.5%).
  - On those clips the sound branch is right 37.5% of the time, the text branch 38.6%, and the fused answer 45.7%.
  - On the other clips the fused answer is right 59.9% of the time, so the flag marks the shakier answers.
- **End-to-end check in headless Chrome against the real models**, with no script errors:
  - a demo clip, drag and drop, and a history click all render;
  - Run all demos on the 7 demo clips: **fused 4/7, sound 2/7, words 4/7**;
  - Space with Chrome's fake microphone shows the timer and a moving level meter (its beep tone gives "no speech");
  - no horizontal page scroll at 390 px on any tab (the wide tables scroll inside their own boxes);
  - light and dark themes both render.
- **Tests:** 66 fast tests pass (4 new in `test_api.py`: the report, missing or broken files, dropped per-utterance fields, the offline page), and the slow real-model API test passes. AC-11 still passes.
- **The user tried the app locally (2026-10-20):** recording with Space, upload, drag and drop, the demo clips, Run all demos, the history, the theme button and the Results tab all work. P8 is done (AC-11 passes).

## P9 Deployment

- **Port 8443 was free**, with no listener before the server started. The laptop's LAN address on the campus Wi-Fi is 10.217.15.89.
- **Certificate:** self-signed EC P-256, with SANs `localhost`, `127.0.0.1` and `10.217.15.89`, valid until 2027-10-20. `serve.ps1` renews it only when the LAN address changes or it nears expiry.
- **Checked through the real addresses, not localhost:**
  - `smoke.ps1` through `https://10.217.15.89:8443`, with the certificate checked against `certs/cert.pem`, passes: health, then analyze (joy 45% on the speech fixture). Without trusting the certificate, curl refuses the connection (exit 60), so the check is real.
  - `smoke.ps1` through the quick tunnel (`https://….trycloudflare.com`, Cloudflare's own certificate) passes too.
  - Every page asset (`/`, `app.js`, `style.css`, the demo clips and `/api/report`) returns 200 through both routes, with identical sizes.
  - **Browser, through both routes**, in headless Chrome with a fake microphone: the demo click, drag and drop, history, Run all demos (fused 4/7) and Space-to-record all work with no script errors. Over the LAN, Chrome trusted only this certificate's key, like accepting the warning once. The page is a secure context there and the record button is enabled.
- **Access log:** one JSON line per request in `logs/server.log`. LAN requests show the client address. Tunnel requests carry `cf_ip`, and uvicorn already reports the forwarded client address as `ip`.
- **Offline check, dry run with the Wi-Fi on:** the server started with `HF_HUB_OFFLINE=1` in 12 s and analysed a demo clip (anger, right). The script correctly called the run "NOT VALID" because the internet was reachable. The real check is the user's, with the Wi-Fi off.
- **Tests:** 67 fast tests pass (new: the access log).
- **Firewall and network (USER):** checked after the user's administrator steps. `iiscwlan` is Private, and the rule "Emotion Analyzer (TCP 8443)" is enabled: inbound, TCP 8443, Private profile, LocalSubnet.
- **Phone over Wi-Fi, the LAN part of AC-12: confirmed from `logs/server.log`.** The phone was an Android phone running Chrome 155 at its own Wi-Fi address. It made 28 requests between 22:20 and 22:27, all 200:
  - the page load, `/api/report` and `/api/health`;
  - 6 analyses that weren't demo clips, i.e. the user's uploads and recordings (the log can't tell the two apart, because both are `POST /api/analyze`);
  - one demo click and Run all demos, 8 analyses in all.
  - Server time per analysis was 1.47–1.70 s (median 1.58 s), back at the benchmark speed.
- **Tunnel from the phone: not confirmed** (`issues.md`). The tunnel itself passed the smoke and browser checks from the laptop.
- After the phone test, the tunnel and the server were stopped. Port 8443 is free, no server or cloudflared process is left, and the old tunnel address returns 530.

## P9, spec v1.6: no demo clips

- **The page has no demo clips any more.** The sample buttons, true labels, right/wrong marks, Run all demos and its scoreboard are gone, along with their code and styles. A live demo now uses the microphone or an uploaded file.
- **No audio can be fetched from the server:**
  - `app/static/` holds only `index.html`, `app.js` and `style.css`;
  - `/static/` serves only `.html`, `.js` and `.css` (`PageFiles`), so even an audio file dropped into the folder gives 404;
  - the routes are exactly `/`, `/api/health`, `/api/report`, `/api/analyze` and `/static`, and none reads `data/`.
- **Tests:**
  - New API tests: the old demo paths, `data/own/` and path tricks into it give 404 and never audio, and the page-file filter is checked with audio in a temporary folder.
  - 68 fast tests and the slow API test pass.
- **Offline check, dry run with the Wi-Fi on:** it now analyses the committed fixture `tests/fixtures/speech_short.wav`. The server started in 8.5 s and the fixture came out joy 45% in 1.7 s. The run was correctly called "NOT VALID" because the Wi-Fi was on.
- **After the change, through the real addresses** (server restarted at 22:45, new tunnel address):
  - `smoke.ps1` through `https://10.217.15.89:8443`: health and analyze pass, and all 8 audio paths give 404.
  - Through the tunnel: the same, except that 2 of the paths get 400. Cloudflare rejects the encoded path tricks before they reach the laptop. No audio either way.
  - **Browser, through both routes** (headless Chrome, uploads from a local fixture): no demo controls are left, and upload, drag and drop, history and Space-to-record work with no script errors. Chrome recorded every response the page received: only `/`, `style.css`, `app.js`, `/api/report`, `/api/health` and `/api/analyze`, and none was audio.
  - The Public-network warning in `serve.ps1` is gone now that the Wi-Fi is Private.

## P10 Transcript

- **`transcript.md` (the `/export` after turn 17) starts at the first message** and runs across the session's compactions, so no backup files were needed.
- **Format:** a user message starts with `❯ ` and its lines are padded to 80 columns. A response is everything up to the next `❯`: `●` for text and tool calls, `⎿` for their output, `✻` for the time taken and `※` for Claude Code's recaps. Markdown is already rendered for the terminal, and tables are drawn with box characters.
- **`tools/transcript_to_html.py` → `transcript.html`** (591 KB, one file, no external requests): 17 "Turn N" headings, each with the full message and the whole response in one collapsed block, a list of turns at the top, and Expand all and Collapse all buttons. All transcript text is HTML-escaped.
- **Checks:**
  - **Against the session log:** 17 turns match the 17 messages the user typed before the export, in order and word for word (whitespace aside). The log has one more typed message, the request to convert the export.
  - **Spot-check, turns 1, 9 and 17:** read back from the page, each message and response is identical to the source. So are all 17 turns, and all 9,570 non-blank source lines are on the page.
  - **Headless Chrome:** Expand all opens all 17 blocks and Collapse all closes them. The turn links jump to their turn, the only request is the file itself, there are no script errors, and nothing scrolls sideways at phone width.
- Before committing, `transcript.md` was checked for the Gemini key, the user's email and the own-recording transcripts (whole, and any 5 consecutive words): none were found.
