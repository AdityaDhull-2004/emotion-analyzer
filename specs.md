# Emotion Analyzer: Specification

| | |
|---|---|
| Version | 1.2 (approved for build; changes in §20) |
| Date | 2026-10-20 |
| Course | Applied Data Science and AI (UMC 301), project 4 |
| Method | Spec-driven development. This file is the source of truth; every change goes through the change log (§20) |
| Repository | `E:\AIDS\Project\emotion-analyzer` |

---

## 1. Goal

**Recognise a speaker's emotion from a short voice recording by combining how it sounds and what is said, offline on a laptop CPU, in about one second.**

The problem it solves:
- A model that reads only the words misses the tone.
- A model that hears only the tone misses the words.
- A general chatbot needs the internet, sends the user's voice to a third party, and gives unmeasured answers.

This app runs two specialised models: one on the sound (through its spectrogram), one on the words (through an automatic transcript). It fuses their answers, and it shows the user both opinions plus a flag when they disagree. Disagreement is where sarcasm and masked emotion show up.

What it does better than a general chatbot. Every point here is **measured in §10**, not assumed:
- accuracy on the same clips, against a chatbot asked the same question;
- it runs fully offline and the audio never leaves the laptop;
- about one second per clip on a laptop CPU;
- a fixed 7-class answer with calibrated probabilities, and transparent reasoning across the two branches.

## 2. Scope

**In scope:**
- English speech.
- Single utterances, or recordings up to 120 s, which are split into segments.
- 7 emotion classes.
- A web app usable from the laptop and from other devices on the local network.

**Out of scope (non-goals):**
- Conversation context across utterances.
- Speaker identification.
- Video.
- Languages other than English.
- Clinical or mental-health use.
- Commercial use.
- Real-time streaming. The app processes a finished recording.

## 3. Course requirements

1. **Deployed.** The project runs as a production server, not a development server. It is usable from this computer and from other devices on the local network (intranet), with an optional internet link (§12).
2. **Transcript.** The whole build happens in **one Claude Code session**, resumed across sittings. At the end it is exported with `/export transcript.md` and converted into a standalone `transcript.html`. That page shows each user message as "Turn 1, 2, 3 …" with the response beneath it as a collapsed block.
3. **Spec-driven.** Plan, implement and verify against this spec. When the design changes, this file changes first, with the reason recorded in §20.

## 4. Constraints

### 4.1 Compute

**Training: Kaggle notebooks.**
- **GPUs:** 2× NVIDIA T4 with 16 GB each.
- **Time limits:**
  - at most 12 hours of execution per session (Kaggle's documented limit for CPU and GPU);
  - about 30 GPU-hours a week (Kaggle does not publish a fixed figure);
  - interactive editor sessions stop after about 60 minutes idle;
  - background **Save & Run All (Commit)** runs have no idle timeout and continue with the browser closed.
- **Resources:** about 30 GB of RAM. `/kaggle/working` holds 20 GB and is saved as the version's output; `/tmp` is scratch space that is not saved.
- **Internet** needs a phone-verified account.
- **Division of work:** the user runs the notebook; the build writes every cell (§9).

**Inference: the laptop.**
- Windows 11, Intel i7-1260P, CPU only (PyTorch cannot use the Iris Xe GPU).
- 16 GB RAM, but often only about 3 GB free. So models are int8 where possible, loaded once, and the server's peak memory stays at or below 2.5 GB.

**Local Python:**
- A project virtual environment built from `py -3.12`.
- The `python` on PATH is a 3.14 interpreter from another project and must not be used.
- `ffmpeg` is installed. Audio decoding uses faster-whisper's PyAV-based `decode_audio`.

### 4.2 Cost

Free only: no paid APIs, no paid hosting.

### 4.3 Licences and data handling

- **MELD** is GPL-3.0. The *Friends* audio is copyrighted by its owners. Therefore:
  - never commit MELD audio to git;
  - never use MELD clips as demo samples in the app;
  - keep any Kaggle copy of MELD-derived data private.
- **CREMA-D** is ODbL; attribution is required.
- **RAVDESS** is CC BY-NC-SA 4.0: non-commercial use, with attribution.
- Citations (§18) appear in `README.md` and in the app's About panel.
- Per-utterance MELD transcripts and predictions stay in the git-ignored `data/kaggle/`. The committed `results/` folder holds only aggregate tables, figures and `metrics.json`; the error analysis may quote its 10 transcripts as text, never audio.
- The only audio committed to git is the small text-to-speech test fixtures in `tests/fixtures/` (§13), generated with Windows' built-in text-to-speech.

### 4.4 Banned

- **Any checkpoint already trained on MELD.** It would leak the test set:
  - `j-hartmann/emotion-english-distilroberta-base`
  - `j-hartmann/emotion-english-roberta-large`
  - `tae898/emoberta-base` and `tae898/emoberta-large`
  - `michellejieli/emotion_text_classifier`
  - `andreasvc/segue-meld-multitask`
  - any `emotion2vec_plus_*`
- Paid APIs.
- Secrets in the repository or in the session. Keys live only in `.env`, which is git-ignored.
- MELD audio in the repository.

### 4.5 Ports

Ports 8000 (another project's app) and 8765 (another project's demo) are taken. This app uses **8443 (HTTPS)**. Check it is free in Phase 9.

## 5. Inputs and outputs

### 5.1 Input audio

- **Accepted formats:** WAV, FLAC, MP3, M4A/AAC, OGG/Opus, and WebM (browser recordings).
- **Decoding:** `faster_whisper.decode_audio(path, sampling_rate=16000)` produces mono float32 at 16 kHz.
- **Limits:**
  - upload of at most 25 MB;
  - duration between 0.5 s and 120 s.

### 5.2 Segmentation

- Silero VAD (`faster_whisper.vad.get_speech_timestamps`) runs on **every** clip.
- If it finds no speech, the response has `"speech_detected": false` and no labels.
- Audio of 10 s or less that contains speech stays one segment: the whole clip.
- Longer audio is split into the VAD's speech segments, merged or split so each lasts 1–10 s.

### 5.3 API

- `GET /` serves the web UI.
- `GET /api/health` returns `{"status": "ok", "models_loaded": true, "version": "1.0.0"}`.
- `POST /api/analyze` takes `multipart/form-data` with one field, `audio`. A successful response looks like this:

```json
{
  "speech_detected": true,
  "duration_s": 4.82,
  "segments": [
    {
      "start_s": 0.0,
      "end_s": 4.82,
      "transcript": "I can't believe you did that!",
      "sound": {"label": "anger", "confidence": 0.61,
                "probs": {"anger": 0.61, "disgust": 0.03, "fear": 0.04, "joy": 0.05,
                          "neutral": 0.17, "sadness": 0.03, "surprise": 0.07}},
      "text":  {"label": "surprise", "confidence": 0.55, "probs": {"...": 0.0}},
      "fused": {"label": "anger", "confidence": 0.48, "probs": {"...": 0.0}},
      "disagreement": true
    }
  ],
  "overall": {"label": "anger", "confidence": 0.48, "probs": {"...": 0.0}},
  "timing_ms": {"decode": 12, "encode": 480, "transcribe": 270, "sound": 3,
                "text": 65, "fusion": 1, "total": 840},
  "models": {"asr": "faster-whisper small.en int8", "window_s": 10,
             "sound": "attnpool-v1", "text": "roberta-base-meld-v1", "fusion_w_sound": 0.35}
}
```

- **Fixed label order** everywhere: `["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]`. These are MELD's label strings, in alphabetical order.
- **`disagreement`** is true when `sound.label != text.label` and both confidences are at least 0.40. The threshold is in the config.
- **`overall`** is the duration-weighted mean of the segments' fused probabilities.
- **Errors** return `{"error": "...", "detail": "..."}`:
  - 400: undecodable or unsupported file;
  - 413: larger than 25 MB;
  - 422: shorter than 0.5 s or longer than 120 s.

### 5.4 Web UI

The UI is a single page in plain HTML, CSS and JavaScript, with no external CDNs, so it works offline. It contains:
- **Input:** a Record button (MediaRecorder) and Upload.
- **Result card:** the fused emotion with a confidence bar.
- **Two side cards:** "How it sounds" and "What was said", each with probability bars for the 7 classes.
- **Transcript.**
- **Disagreement banner**, for example: "Tone and words disagree: it sounds angry, but the words read as surprised."
- **Timeline** of segments, for recordings longer than 10 s.
- **Processing time.**
- **Demo samples:** only the user's own recordings, with consent. They are served from the git-ignored folder `app/static/samples/`, filled in Phase 8 from the clips listed in `data/own/demo_ok.txt`.
- **About panel:** citations, plus the limitations ("trained on TV dialogue; not for clinical use; English only").
- **Layout:** works at phone width.
- **Microphone access:** browsers allow microphone recording only in a secure context (HTTPS or localhost). The local-network server therefore uses HTTPS with a self-signed certificate (§12). Upload always works.

## 6. System design

```
                ┌───────────────────────── one faster-whisper small.en pass ─────────────────────────┐
 audio ─► decode ─► VAD segments (≤10 s) ─► log-mel ─► Whisper encoder (frozen) ─┬─► greedy decoder ─► transcript ─► RoBERTa-base ─► p_text ──┐
  16 kHz mono                                    (80 × 1000 frames for 10 s)     │                                                            ├─► fusion ─► label, confidence,
                                                                                 └─► encoder frames (T × 768) ─► attention-pooling head ─► p_sound ┘    disagreement flag
```

### 6.1 The shared Whisper pass

These calls were verified with faster-whisper on the target laptop. The 10 s window produced an encoder output of shape (1, 500, 768) and the same transcript as the 30 s window on a test clip.

```python
model = WhisperModel("small.en", device="cpu", compute_type="int8")
tok   = Tokenizer(model.hf_tokenizer, False, task="transcribe", language="en")   # faster_whisper.tokenizer
feats = model.feature_extractor(audio)                     # log-mel, 100 frames per second
x     = np.ascontiguousarray(pad_or_trim(feats, W))        # W = 1000 (10 s window) or 3000 (30 s window)
enc   = model.encode(x)                                    # encoder output, shape (1, W/2, 768)
ids   = model.model.generate(enc, [list(tok.sot_sequence) + [tok.no_timestamps]], beam_size=1)[0].sequences_ids[0]
text  = tok.decode([i for i in ids if i < tok.eot])
frames = np.array(enc)[0, :ceil(duration_s / 0.02)]        # valid frames only; 1 encoder frame = 20 ms
```

- **Window choice:** set by the window rule in §8.1: latency first, then word error rate. Either the 10 s window is used for segments of 10 s or less, or the standard 30 s window.
- **Training features** are computed on Kaggle with the same model on GPU (`device="cuda", compute_type="float16"`). Phase 6 checks that the laptop's CPU int8 features give the same results (§10.5).

### 6.2 Modules

| Module | Responsibility |
|---|---|
| `config.py` | Labels, paths, the window, thresholds and seeds, all in one place |
| `data.py` | MELD manifests and the CSV join with defect handling; CREMA-D and RAVDESS loaders with label maps; own-recordings loader |
| `speech.py` | `SpeechPipeline`: decode, VAD segmentation, the shared encode, transcript from the encoder output, valid frames, per-stage timing |
| `features.py` | Batch encoder-frame extraction and fp16 sharded caching, for Kaggle and local use |
| `sound_model.py` | The attention-pooling head; training loop; inference |
| `text_model.py` | RoBERTa classifier; training loop; int8 dynamic quantisation; inference |
| `fusion.py` | Weighted log-probability fusion, weight search, the disagreement rule |
| `metrics.py` | Weighted-F1, macro-F1, accuracy, per-class report, confusion matrix, bootstrap confidence intervals, WER |
| `transcribe.py` | Batch transcription of MELD and WER in both windows |
| `evaluate.py` | Builds every results table and figure from the saved probabilities |
| `latency.py` | Per-stage CPU timing benchmark |
| `chatbot_compare.py` | Runs the chatbot comparison on the user's own recordings |
| `app/main.py` | FastAPI app: loads models once, serves the API and the static UI |

## 7. Data

### 7.1 MELD (main dataset)

**Source:** the Hugging Face dataset `ajyy/MELD_audio` (GPL-3.0, not gated). It holds:
- `archive/train.tar.gz` (1.09 GB), `archive/dev.tar.gz` (0.12 GB) and `archive/test.tar.gz` (0.32 GB);
- `train.csv`, `dev.csv` and `test.csv` at the top level.

Fetch them with `huggingface_hub.hf_hub_download(repo_id="ajyy/MELD_audio", repo_type="dataset", filename=...)`. The repository's loading script is not needed.
- **Audio:** FLAC, 16 kHz, mono, stored as `{split}/dia{Dialogue_ID}_utt{Utterance_ID}.flac`.
- **Fallback:** the Kaggle dataset `ngocson2002/meld-datasetv2`, which holds the same FLAC files and CSVs.
- **Original release:** <https://github.com/declare-lab/MELD>. The 10.9 GB of raw video is not needed.

**CSV columns:** `Sr No., Utterance, Speaker, Emotion, Sentiment, Dialogue_ID, Utterance_ID, Season, Episode, StartTime, EndTime`.

**Join:**
- Inner-join the CSV rows to the audio files on (`Dialogue_ID`, `Utterance_ID`).
- Files not in a CSV are ignored.

**Known defects:**
- Train `dia125_utt3` is absent (corrupt in the original release), leaving **9,988** train pairs.
- Dev `dia110_utt7` is missing, leaving **1,108** dev pairs.
- Test has **2,610** pairs.
- That makes **13,706** in total.
- The loader asserts these counts. It drops and logs (in `issues.md`) any other unreadable clip, or any clip shorter than 0.1 s.

**Text cleaning:** MELD utterances contain encoding artefacts, for example `â€™` in place of an apostrophe. Repair them with `ftfy`, then strip whitespace. Never alter the labels.

**Published class counts** (from the MELD paper; dev includes the missing clip):

| Emotion | Train | Dev | Test |
|---|---:|---:|---:|
| anger | 1,109 | 153 | 345 |
| disgust | 271 | 22 | 68 |
| fear | 268 | 40 | 50 |
| joy | 1,743 | 163 | 402 |
| neutral | 4,710 | 470 | 1,256 |
| sadness | 683 | 111 | 208 |
| surprise | 1,205 | 150 | 281 |
| **total** | **9,989** | **1,109** | **2,610** |

**Splits:** use the official splits only, with no re-splitting. The same main cast appears in every split, so MELD scores say little about new voices. The user's own recordings (§7.3) test that instead.

### 7.2 Acted corpora (used only for one sound-model ablation)

| Corpus | Kaggle input | Contents | Label map onto the 7 classes |
|---|---|---|---|
| CREMA-D (ODbL) | `ejlok1/cremad` | `AudioWAV/*.wav`: 7,442 clips, 91 actors, 16 kHz. File name `ActorID_Sentence_EMO_Level.wav` | ANG→anger, DIS→disgust, FEA→fear, HAP→joy, NEU→neutral, SAD→sadness. No surprise. |
| RAVDESS speech (CC BY-NC-SA 4.0) | `uwrfkaggler/ravdess-emotional-speech-audio` | 1,440 clips, 24 actors, 48 kHz. **The folder tree is duplicated: use one copy and de-duplicate by file name.** File name `03-01-EE-II-SS-RR-AA.wav` | EE: 01 neutral, 02 calm→neutral, 03 happy→joy, 04 sad→sadness, 05 angry→anger, 06 fearful→fear, 07 disgust, 08 surprised→surprise |

- Resample both to 16 kHz mono.
- Both use fixed sentences, so they are never used for the text model.
- Excluded:
  - TESS: its licence may be NoDerivatives.
  - SAVEE: needs registration.
  - IEMOCAP and MSP-Podcast: gated behind a request form or a signed licence.

### 7.3 The user's own recordings (new-voice test)

- **Clips:** 30–50 clips of 3–8 s each, of the user and friends saying varied everyday sentences in each emotion, with at least 4 clips per emotion.
- **Location:** `data/own/`, named `{emotion}_{nn}.{wav|m4a|mp3|webm}`. The label is read from the file name.
- **Privacy:** recorded with consent and git-ignored. The consent also covers sending the clips to Google's Gemini for the chatbot comparison (§10.7), and the README says so.
- **Used for:**
  - evaluation (§10.6);
  - the chatbot comparison (§10.7);
  - app demo samples (only the clips whose speakers agree).

### 7.4 Local copies

- **Only MELD dev** (`archive/dev.tar.gz` plus `dev.csv`) is downloaded locally, into `data/meld/dev/`. It is used for smoke tests, the preliminary WER check, latency and CPU-parity checks.
- All MELD training happens on Kaggle.

## 8. Models

### 8.1 Speech-to-text

- **Model:** faster-whisper `small.en`.
  - Laptop: int8 on the CPU.
  - Kaggle: CUDA float16.
- **Decoding:** greedy (`beam_size=1`), no timestamps, English.
- **Window rule.** Phase 3 times small.en end to end on a 5 s clip in **both** windows (§10.4 method, on mains power). Then exactly one case applies:
  - **(a) small.en meets AC-08 in both windows.** S4 chooses the window: 10 s if, on MELD dev, WER(10 s) − WER(30 s) ≤ 2.0 points absolute; otherwise 30 s.
  - **(b) small.en meets AC-08 only with the 10 s window.** The build doesn't stop. The window is fixed at 10 s for clips up to 10 s, and S4 records the WER cost, WER(10 s) − WER(30 s) on dev and test, instead of choosing the window.
  - **(c) small.en fails AC-08 even with the 10 s window.** The spec switches to `base.en` before Phase 4, and the same timing check is repeated for it.
- The case, the window and the WER figures are recorded in `models/decision.json` and in `insights.md`.
- **WER computation:** apply Whisper's English text normaliser (the Whisper tokenizer's `normalize()` in `transformers`, or an equivalent) to both the reference and the hypothesis, then compute WER with `jiwer`.
- **Expected WER on MELD:** about 35%. MELD's references are subtitles and the audio is noisy TV dialogue. For comparison, small.en gets about 3% on clean read speech (LibriSpeech test-clean) and about 14% on acted speech (IEMOCAP).
- **Clips longer than the window** are transcribed in consecutive chunks of up to the window's length, and the text is joined. This applies to both windows (2.1% of MELD clips exceed 10 s, and 3 exceed 30 s), so the window comparison is fair.
- **Model size is settled in Phase 3, before any training,** by case (c) of the window rule. `base.en` is not a drop-in fallback after training: its encoder output is 512-wide where the sound head expects small.en's 768, and the text model trains on small.en's transcripts.

### 8.2 Sound model: `attnpool-v1`

**Input:** valid encoder frames, T × 768, from the frozen Whisper encoder.

**Architecture** (about 0.2 M parameters):

```
LayerNorm(768) → Linear(768, 256) → GELU → Dropout(0.2)
→ attention pooling: scores = v·tanh(W·h) over valid frames (masked softmax) → weighted sum (256)
→ Dropout(0.2) → Linear(256, 7)
```

**Training:**
- **Optimiser:** AdamW, learning rate 1e-3, weight decay 0.01, batch 64.
- **Schedule:** up to 40 epochs, cosine with 1 warm-up epoch.
- **Early stopping:** patience 6, on dev weighted-F1.
- **Augmentation:** randomly drop 10% of frames, and randomly crop to at least 1 s.
- **Loss:** class-weighted cross-entropy, with w_c = sqrt(N / (K · n_c)) normalised to a mean of 1.
- **Seeds:** {0, 1, 2}.

**Long clips** (over 10 s, in training and evaluation): split into consecutive chunks of up to 10 s, encode each chunk, and concatenate the valid frames.

**Runs:**
- **Main:** MELD train only.
- **Ablation A (acted corpora):** MELD train plus CREMA-D plus RAVDESS.
- **Ablation W (window):** the other window's features.
- All runs are evaluated on MELD only.

**Deployed model:** the main run's seed with the best dev weighted-F1.

### 8.3 Text model: `roberta-base-meld-v1`

- **Base:** `FacebookAI/roberta-base` with a 7-label classification head (`AutoModelForSequenceClassification`).
- **Input:** the utterance text only, with no speaker name and no context. `max_length` 64, truncating longer input.
- **Training data:** MELD train's real utterances plus the Whisper transcripts (in the chosen window) of the same clips, with the same labels.
  - Drop empty transcripts.
  - Drop exact duplicates within the same label.
- **Recipe:**
  - learning rate 2e-5, weight decay 0.01, batch 32;
  - 6 epochs, linear decay with 10% warm-up, fp16;
  - class weights as in §8.2;
  - seeds {0, 1, 2}.
- **Model selection:** dev weighted-F1 measured on **dev Whisper transcripts**, the condition the app runs in.
- **Ablation T:** the same recipe trained on real transcripts only.
- **Inference:** `torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)` on the CPU.
- **Deployed model:** decided at the start of Phase 6, before the temperatures and the fusion weight are fitted (§8.4), by a fixed rule. Use the 3-seed ensemble (the mean of the three seeds' probabilities) only if:
  - it adds at least 1.0 point of text-only weighted-F1 on the dev Whisper transcripts over the best single seed; **and**
  - the end-to-end latency still meets AC-08; **and**
  - the server's peak memory still meets AC-09.

  Otherwise use the best single seed. The F1 test comes first; latency and memory are measured with `latency.py` only if it passes. S7 exports all three main-seed checkpoints, so the rule needs no second Kaggle run.

### 8.4 Fusion

```
log p_fused = w · log p_sound + (1 − w) · log p_text   →   softmax-renormalise
```

- **Weight search:** w ∈ {0.00, 0.05, …, 1.00}, chosen to maximise dev weighted-F1. The search uses the deployed models' dev probabilities: sound from the audio, text from the dev Whisper transcripts.
- **Calibration first:** before fusing, each model's log-probabilities are temperature-scaled with T_sound and T_text, each fitted on dev by minimising negative log-likelihood. The weight search then runs on the calibrated dev probabilities.
- **When:** at the start of Phase 6, right after the text-ensemble rule (§8.3) has fixed the deployed text model, because the parity check needs the fused output.
- **Saved:** `models/fusion.json`, holding both temperatures and the weight.
- **Disagreement rule:** see §5.3.

## 9. Training plan (Kaggle)

### 9.1 How the run is executed

- **Notebook:** `emotion-analyzer-train`.
- **Inputs:**
  - the private dataset `emotion-analyzer-code` (built from `kaggle/code/` by `scripts/package_kaggle.py`);
  - `ejlok1/cremad`;
  - `uwrfkaggler/ravdess-emotional-speech-audio`.
- **Settings:** Accelerator **GPU T4 ×2**, Internet **On**.

The run happens in **two passes**:

1. **Interactive check, about 10–15 minutes.** In the editor, run only cell S0. It:
   - prints the GPUs, RAM, free disk and package versions;
   - installs the pinned packages;
   - downloads a handful of MELD dev clips;
   - confirms CTranslate2 runs on CUDA (§9.2);
   - prints the measured per-clip times and the re-estimated total for every stage;
   - writes the same report to `/kaggle/working/s0_check.txt`. The user downloads it from the editor's Output panel into `C:\Users\adity\Downloads`, and the session reads it from there.

   The long run doesn't happen here, because interactive sessions stop after about 60 minutes idle.
2. **Main run, as a background commit.** Use **Save Version → Save & Run All (Commit)**. Kaggle then:
   - starts a clean session;
   - runs every cell from top to bottom, unattended (there's no idle timeout, and the browser can be closed);
   - saves `/kaggle/working` as the version's output.

   It must finish within 12 hours; the plan needs about 2 hours (§9.4).

**Cells must work unattended under Run All:**
- one config cell at the top (paths, seeds, and flags such as `RUN_ABLATIONS = True`);
- no manual step between cells;
- each stage prints a one-line status, and an error message that says what to do.

**Getting the results:** open the finished version → **Output** → download `emotion_outputs.zip` (into `C:\Users\adity\Downloads`; Phase 6 moves it into the git-ignored `data/kaggle/`). If the browser download fails, use the Kaggle CLI instead: `kaggle kernels output <username>/emotion-analyzer-train -p <local folder>`.

### 9.2 Environment on Kaggle

**Packages.**
- Kaggle's image already provides PyTorch, transformers, scikit-learn and pandas. S0 records their versions in the log.
- S0 installs the pinned extras from `requirements-kaggle.txt`: `faster-whisper` (with its `ctranslate2`), `jiwer`, `ftfy`, `huggingface_hub` and `soundfile`.

**CTranslate2 on the GPU** needs cuBLAS for CUDA 12 and cuDNN 9 (ctranslate2 4.5 and later). The commonly reported failure is "Unable to load libcudnn_ops.so.9". The documented fixes:
- install `nvidia-cublas-cu12` and `nvidia-cudnn-cu12==9.*`, and put their `lib` folders on `LD_LIBRARY_PATH`;
- or pin `ctranslate2==4.4.0`, the last build made for cuDNN 8.

`LD_LIBRARY_PATH` is only read when a process starts. So the GPU stages S3 and S5 run as **subprocesses** (`python -m emotion_analyzer.transcribe …`, `python -m emotion_analyzer.features …`) launched with the corrected environment. S0 proves this works with a tiny GPU encode in a subprocess before the main run is committed.

**Fallback**, if CTranslate2 cannot use the GPU at all: run S3 and S5 with the Hugging Face `transformers` implementation of `openai/whisper-small.en` on the GPU. It uses the same weights, and the CPU parity check (§10.5) then covers the difference in implementation.

**Using both GPUs:**
- S3 and S5 split the clip list into two halves and run one subprocess per GPU (`CUDA_VISIBLE_DEVICES=0` and `1`).
- S7 runs two training runs at a time, one per GPU.

### 9.3 Stages

**Resuming.** Every stage writes its results and a marker file into `/kaggle/working/state/`. When a stage starts, it skips work that is already present, either there or in the `state/` folder of **any** attached input under `/kaggle/input/*/`. A previous version's output, attached through **Add Input**, mounts under that notebook's own name, so the code searches every input rather than one fixed path. `KAGGLE.md` also describes the alternative: save the output as a new private dataset and attach that. If a run fails part-way:
1. Attach the failed version's output through **Add Input**.
2. Run **Save & Run All** again.

Finished stages are then skipped. Features are cheap to recompute, so they are not carried over.

**Session guard:** no new training run starts after 11 hours of elapsed time.

| Stage | What it does |
|---|---|
| S0 | **Environment check, installs and quick benchmark**, as in §9.1 and §9.2. |
| S1 | **Download MELD** from Hugging Face with `hf_hub_download`, and extract it to `/tmp/meld`. If that fails, attach the fallback input `ngocson2002/meld-datasetv2`. |
| S2 | **Build manifests:** the CSV join, defect handling, count assertions and class tables, for MELD and the acted corpora. Copy RAVDESS from **one** of its duplicated folder trees, resampled to 16 kHz in `/tmp`. |
| S3 | **Transcribe** every MELD split in **both** windows, across both GPUs. Write `transcripts/{split}_{10s,30s}.csv`, and WER per split and window. |
| S4 | **Window decision** by the rule in §8.1. The Phase 3 case is set in the config cell: in case (a), choose the window by the WER rule; in case (b), keep the fixed 10 s window and record its WER cost on dev and test. Write `decision.json`. |
| S5 | **Encoder frames** in the chosen window, for MELD (all splits) plus CREMA-D plus RAVDESS, and for MELD in the other window (ablation W). Trim to the valid length and store as fp16 in shards, with an index, under `/tmp/features`. |
| S6 | **Sound heads:** main ×3 seeds, ablation A ×3, ablation W ×3. Save the best checkpoints, and dev and test probabilities. |
| S7 | **Text models:** main ×3 seeds and ablation T ×3, two runs in parallel (one per GPU). Save **all three** main-seed checkpoints (fp16 safetensors), plus dev and test probabilities on both real and Whisper transcripts for every run. |
| S8 | **Export:** `predictions/*.npz`, `metrics.json` and the logs. Print **one compact final results block**, save it as `logs/final_results.txt`, and zip everything needed into `/kaggle/working/emotion_outputs.zip` (target about 1 GB). |

### 9.4 GPU-hours

These are estimates; S0 re-measures them.

| Stage | Arithmetic | GPU-hours |
|---|---|---:|
| S0 (interactive) | Install and a 1-minute benchmark | 0.2 |
| S3 | 13,706 clips × (≈0.15 s for the 30 s window + ≈0.08 s for the 10 s window) ≈ 52 min | 0.9 (about 0.5 wall-clock on 2 GPUs) |
| S5 | (13,706 + 7,442 + 1,440) clips × ≈0.04 s ≈ 15 min, plus about 9 min for MELD's other window | 0.4 |
| S6 | 9 runs × ≈3 min | 0.45 |
| S7 | about 20k examples × 6 epochs ≈ 10 min per run × 6 runs | 1.0 (about 0.5 wall-clock) |
| S1, S2, S8 | Download, manifests, export | 0.3 |
| **Total** | | **≈3.2 (about 2 h wall-clock for the commit)** |

The budget cap is 6 GPU-hours, comfortably inside one 12-hour commit and the weekly quota.

### 9.5 Disk and memory

**`/kaggle/working`** (20 GB, saved as the output). Keep only what is needed, with a target under 2 GB:
- transcripts and `decision.json`;
- `sound_head.pt` and its config;
- the three text-model seeds (fp16, about 250 MB each);
- predictions, `metrics.json`, logs and the state markers;
- `emotion_outputs.zip`.

**`/tmp`** (scratch, not saved):
- MELD audio, about 1.5 GB extracted;
- resampled RAVDESS, about 0.2 GB;
- encoder features, fp16 and trimmed (MELD clips average about 3.2 s, about 160 frames): about 3.4 GB per MELD window plus about 2.2 GB for the acted corpora, about 9 GB in total.

S0 prints the free space in both. If `/tmp` has less than 15 GB free, extract features in the chosen window only and skip ablation W, recording the reason in `insights.md`.

**RAM:** about 30 GB, so one window's features fit in memory for training the heads.

**`emotion_outputs.zip`** contains:
- `models/`: `sound_head.pt`, `sound_head.json`, `text_model_seed0/`, `text_model_seed1/` and `text_model_seed2/` (fp16 safetensors plus tokenizer) and `decision.json`;
- `predictions/`: dev and test probabilities for every run;
- `transcripts/`, `metrics.json` and `logs/` (including `final_results.txt`).

## 10. Evaluation

### 10.1 Metrics

- **Headline:** weighted-F1 (scikit-learn `average="weighted"`).
- **Also reported:**
  - macro-F1 and accuracy;
  - per-class precision, recall and F1;
  - confusion matrices;
  - 95% bootstrap confidence intervals (1,000 resamples of the test utterances, fixed seed);
  - for trained models, the mean ± standard deviation over the 3 seeds.

### 10.2 MELD test results table

| Row | Condition |
|---|---|
| R0 | Majority baseline: always "neutral". Expected accuracy 48.1%, weighted-F1 31.3. |
| R1 | Sound only (main) |
| R2 | Sound only, ablation A (plus acted corpora) |
| R3 | Sound only, ablation W (other window) |
| R4 | Text on **real** transcripts (the text upper bound) |
| R5 | Text on **Whisper** transcripts (realistic) |
| R6 | Text, ablation T (trained on real transcripts only), tested on Whisper transcripts |
| R7 | **Fused, with Whisper transcripts**: sound seed *i* fused with text seed *i* at the deployed weight, mean ± sd over *i* |
| R8 | Fused, with real transcripts (reference), same pairing |
| R9 | **The deployed system**: the deployed models, temperatures and weight, on Whisper transcripts (a single run) |

Every trained row reports the mean ± sd over its 3 seeds. The acceptance criteria use these means.

### 10.3 Other checks

**10.3 Word error rate.** Per split and per window, normalised as in §8.1.

**10.4 CPU latency.**
- Measured on the laptop, **plugged in**, on a 5 s clip.
- Before timing, check that the laptop is on mains power; ask the user only if it is on battery.
- 2 warm-up runs, then 20 timed runs.
- Report the median and 90th percentile per stage (decode, encode, transcribe, sound, text, fusion) and in total, plus the server's peak memory.

**10.4b Calibration.** Expected calibration error (15 equal-width bins) and a reliability diagram for the fused output on test, before and after temperature scaling (§8.4).

**10.4c Offline check.** With Wi-Fi switched off and `HF_HUB_OFFLINE=1`, the server starts and analyses a clip on localhost. The user runs `scripts/offline_check.ps1` while the Claude Code session is idle, because the session itself needs the internet. The script writes `results/offline_check.txt`.

**10.5 CPU parity.**
- Compare the CPU int8 pipeline with the Kaggle fp16 results on MELD dev.
- The weighted-F1 difference must be at most 1.5 points, for sound, text and fused.

**10.6 New voices.** On the user's own recordings, report per-clip predictions, accuracy and weighted-F1, with a caveat about the small sample.

**10.7 Chatbot comparison.**
- **Clips:** the same own recordings, sent to a general multimodal chatbot.
- **Instruction**, identical for every clip: "Classify the speaker's emotion into exactly one of: anger, disgust, fear, joy, neutral, sadness, surprise. Answer with the label only."
- **How it is run:**
  - Gemini, through the free API with a key the user puts in `.env`, using the `google-genai` package; record the model name used.
  - Fallback, only if the free API is unavailable: ChatGPT by hand, with each answer logged in `results/chatbot_raw.csv`.
- **Report:** accuracy and weighted-F1 next to ours, the latency, and the fact that it is online and not private.
- **Never send MELD clips** (copyright).

**10.8 Error analysis.**
- Show 10 MELD test clips where sound and text disagree: transcript, both predictions, the fused prediction and the true label.
- Discuss the confusions per class.

### 10.9 Expected ranges

These are estimates from published results, not targets. Sources are in §18.

| Condition | Weighted-F1 |
|---|---|
| Sound only | 40–46 |
| Text on real transcripts | 60–63 |
| Text on Whisper transcripts | 50–57 |
| Fused, with Whisper transcripts | 52–59 |

Typical fusion gains reported on MELD are +0.5 to +2.5 points.

## 11. Acceptance criteria

| ID | Criterion | How it is checked |
|---|---|---|
| AC-01 | MELD joins to 9,988 / 1,108 / 2,610 audio–label pairs | Loader assertion and a test |
| AC-02 | WER reported for dev and test in both windows, and the window set by the §8.1 rule (chosen by WER in case (a); fixed at 10 s with its WER cost recorded in case (b)) | `insights.md`, `decision.json` |
| AC-03 | Sound only (R1), MELD test weighted-F1 ≥ 40.0 (mean of 3 seeds) | Results table |
| AC-04 | Text on real transcripts (R4) ≥ 58.0 (mean of 3 seeds) | Results table |
| AC-05 | Fused, with Whisper transcripts (R7), ≥ 52.0 **and** ≥ text on Whisper transcripts (R5), both as seed means | Results table |
| AC-06 | Every model row beats the majority baseline (31.3 weighted-F1) | Results table |
| AC-07 | CPU parity: weighted-F1 difference ≤ 1.5 points on dev | §10.5 report |
| AC-08 | Latency: median ≤ 2.0 s per 5 s clip, end to end, laptop plugged in. Stretch: ≤ 1.2 s | `latency.py` output |
| AC-09 | Server peak memory ≤ 2.5 GB | `latency.py` output |
| AC-10 | Own recordings evaluated, and the chatbot comparison done on the same clips | `results/` tables |
| AC-11 | API tests pass: normal clip, silence, long recording (segmented), unsupported format, too large, too short | `pytest`, with the committed speech fixtures |
| AC-12 | App reachable from a phone on the same Wi-Fi over HTTPS, and analysis works (upload and record). The optional internet link works if enabled | The server access log, and the deployment check in `insights.md` |
| AC-13 | No MELD audio in git or in the demo samples (the only tracked audio is the fixtures in `tests/fixtures/`); no banned checkpoint anywhere in the code | Test that scans the repository and config |
| AC-14 | README lets a new user install, run, train (via `KAGGLE.md`) and deploy from scratch | Manual check in Phase 10 |
| AC-15 | Transcript exported and converted to `transcript.html` with Turn N headings and collapsed responses | Phase 10 |
| AC-16 | Fused test calibration error reported before and after temperature scaling, with the reliability diagram | `results/calibration.md` |
| AC-17 | With Wi-Fi off and `HF_HUB_OFFLINE=1`, the server starts and analyses a clip on localhost | Offline check in `insights.md` |

Criteria that fail are reported honestly with the measured value. They are never hidden.

## 12. Deployment

- **Server:**

  ```
  uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem --workers 1
  ```

  It uses a single worker, because the work is CPU-bound and memory is limited. The models load once at start-up.
- **One-click start:** `scripts/serve.ps1`. It activates the virtual environment, checks the models are present, starts the server, and prints the LAN and localhost URLs.
- **Certificate:** `scripts/make_cert.py` (using `cryptography`) creates a self-signed certificate. Its Subject Alternative Names cover `localhost`, `127.0.0.1` and the laptop's current LAN IP address. `certs/` is git-ignored. On the phone, accept the browser warning once; the microphone then works. Verify this in Phase 9, and fall back to upload if it doesn't.
- **Network:** Windows must treat the Wi-Fi as a **Private** network, because the firewall rule applies only there. Campus Wi-Fi often blocks device-to-device traffic (client isolation). If the phone cannot reach the laptop, put both on a phone hotspot, or use the tunnel.
- **Firewall:** one inbound rule for TCP 8443 on the Private profile. It is run by the user in an administrator PowerShell; the exact line goes in the README.
- **Optional internet link:** `scripts/tunnel.ps1` runs `cloudflared tunnel --url https://localhost:8443 --no-tls-verify`. That is a quick tunnel with a random `trycloudflare.com` HTTPS address, which lasts only while it runs. `cloudflared` is already installed.
- **Smoke check:** `scripts/smoke.ps1` calls `/api/health` and `/api/analyze` through the real LAN address.
- **Offline check:** `scripts/offline_check.ps1` sets `HF_HUB_OFFLINE=1`, starts the server, analyses a demo clip on localhost, writes `results/offline_check.txt` and stops the server. The user runs it with Wi-Fi off (§10.4c).
- **Access log:** the app writes one line per request to the git-ignored `logs/server.log`: time, client IP, user agent, endpoint, status and processing time, plus Cloudflare's `CF-Connecting-IP` header when present. The deployment check (AC-12) reads it to confirm the phone's requests over Wi-Fi and through the tunnel.
- **Content:** demo samples are only the user's own recordings, with consent. Citations are shown in the About panel.
- **Documentation:** `README.md` gets a "Running in production" section, with the working directory before every command.

## 13. Repository layout and output files

```
emotion-analyzer/
├── specs.md                  this specification
├── tasks.md                  build checklist derived from §14
├── CLAUDE.md                 working rules (§15)
├── README.md                 user guide: install, run, train, deploy, citations
├── KAGGLE.md                 numbered Kaggle cells with expected output and run time
├── issues.md                 known problems and errors
├── insights.md               results, figures, decisions with numbers
├── requirements.txt          local CPU environment, pinned
├── requirements-kaggle.txt   Kaggle extras, pinned
├── .gitignore                data/, models/, certs/, .env, .venv/, kaggle/code/, __pycache__/, app/static/samples/, logs/
├── pyproject.toml            package metadata (src layout), pytest `slow` marker
├── .githooks/pre-commit      runs the fast tests; enabled with `git config core.hooksPath .githooks`
├── .env.example              GEMINI_API_KEY= (empty)
├── src/emotion_analyzer/     __init__.py, config.py, data.py, speech.py, features.py, sound_model.py,
│                             text_model.py, fusion.py, metrics.py, transcribe.py, evaluate.py,
│                             latency.py, chatbot_compare.py
├── app/                      main.py, static/index.html, static/app.js, static/style.css, static/samples/ (git-ignored demo clips)
├── scripts/                  package_kaggle.py, serve.ps1, tunnel.ps1, make_cert.py, smoke.ps1, offline_check.ps1
├── kaggle/code/              built by package_kaggle.py (git-ignored)
├── models/                   sound_head.pt, sound_head.json, text_model_seed{0,1,2}/, fusion.json, decision.json (git-ignored)
├── data/                     meld/dev/, own/ (with demo_ok.txt), kaggle/ (git-ignored)
├── results/                  aggregate tables (.csv/.md), figures (.png, 150 dpi), metrics.json (committed)
├── logs/                     server.log, the app's access log (git-ignored)
├── tests/                    test_data.py, test_speech.py, test_models.py, test_fusion.py,
│                             test_metrics.py, test_api.py, test_repo_rules.py,
│                             fixtures/ (text-to-speech WAV clips, 16 kHz mono, under 1 MB in total; committed)
└── tools/                    transcript_to_html.py, make_fixtures.ps1 (generates tests/fixtures/ once)
```

## 14. Build phases

`tasks.md` mirrors these phases. Each phase ends with its tests passing, `tasks.md` ticked, results in `insights.md`, and a commit.

| Phase | Deliverables | Done when |
|---|---|---|
| P1 Scaffold | Folder tree (§13), `.venv` from `py -3.12`, pinned requirements, `pyproject.toml`, `.githooks/pre-commit`, `.gitignore`, README stub, `config.py` | `pytest` runs (trivial tests pass) and the hook runs them on commit |
| P2 Data | `data.py`: MELD dev downloaded locally, the join with defects, label maps for CREMA-D and RAVDESS, own-recordings loader. A short data report in `insights.md` | AC-01 logic tested on dev (1,108 pairs); label-map tests pass |
| P3 Speech pipeline | `speech.py` (shared pass, both windows, VAD on every clip, chunked transcription of long clips, timing); the text-to-speech fixtures in `tests/fixtures/`. WER on 300 local dev clips in both windows; per-stage and end-to-end CPU times in both windows | Numbers in `insights.md`; preliminary WER rule evaluated; the §8.1 window case (a), (b) or (c) settled, and with it the model size; tests pass |
| P4 Training code | `features.py`, `sound_model.py`, `text_model.py`, `fusion.py`, `metrics.py`, `transcribe.py`, smoke-tested locally on a few dev clips with tiny settings | Every stage's code runs end to end locally on tiny settings |
| P5 Kaggle package | `scripts/package_kaggle.py` → `kaggle/code/`; `requirements-kaggle.txt`; `KAGGLE.md` with the inputs and settings, the two-pass run from §9.1 (the interactive S0 check, then the Save & Run All commit), cells S0–S8 with expected output and run time, how to resume from a previous version's output, and how to download the results; a local dry-run of the cell sequence on a tiny subset | Dry-run passes; the GPU-hours estimate is stated |
| — | **User runs S0 interactively, then commits the notebook (Save & Run All)** | `emotion_outputs.zip` downloaded from the version's Output tab |
| P6 Import and parity | The zip moved from Downloads into `data/kaggle/` and unpacked (models into `models/`, aggregates into `results/`); `latency.py`; the text-ensemble rule (§8.3) applied; then temperatures and fusion weight fitted on dev; the CPU int8 parity check on dev | AC-07 checked; the deployed text model recorded; training results in `insights.md` |
| P7 Evaluation | The full results table (§10.2) with CIs and seed means; calibration; latency; own recordings; chatbot comparison; error analysis; figures | AC-02 to AC-10 and AC-16 checked and reported |
| P8 App | FastAPI app and UI (§5) with demo samples; API tests | AC-11 passes; the user tries the app locally |
| P9 Deployment | Certificate, serve, tunnel and smoke scripts; firewall and network instructions; offline check; README "Running in production" | AC-12 verified from a phone; AC-17 checked |
| P10 Wrap-up | README complete; spec matches the build; final test run; transcript converter built against the trial export | AC-13 to AC-15 |

## 15. Working rules for the build (copy into CLAUDE.md)

- **Source of truth:**
  - This spec is the source of truth. When the design or direction changes, update it first and record the reason in §20.
  - `README.md` is the user guide, not the plan. The build checklist is `tasks.md`.
- **Flow:**
  - Work through `tasks.md` in order, phase by phase.
  - At the end of each phase: make sure its tests pass; tick its tasks; record problems in `issues.md` and results in `insights.md`; commit as `Pn: …`; give a short summary. Then carry straight on to the next phase.
  - Tasks marked `USER` block the build. Stop and ask; don't do them or work around them.
  - Tasks marked `USER-ANYTIME` don't block. Remind the user of them in each phase summary until they're done. Stop only if the phase that needs one arrives and it still isn't done.
  - Also stop if something would contradict this spec, or if a result fails an acceptance criterion in a way that changes the plan.
- **After each finished task:** tick it in `tasks.md`; note problems in `issues.md`; note results and figures in `insights.md`.
- **Tests:**
  - Tests are the acceptance criteria. Every phase ends with tests that pass.
  - The git pre-commit hook (`.githooks/pre-commit`, enabled with `git config core.hooksPath .githooks`) runs the fast tests: under 60 s, no model downloads.
  - Tests that need model weights are marked `slow`.
  - Speech test clips are fixtures generated once with Windows' built-in text-to-speech (`tools/make_fixtures.ps1`) and committed in `tests/fixtures/`. Tests never call text-to-speech at run time and never use MELD audio.
- **Python:** use only the project virtual environment, built from `py -3.12` (`.venv\Scripts\python.exe`). Never the system `python`: the one on PATH is a 3.14 interpreter from another project.
- **Commands given to the user:** put the working directory on its own line before every command.
- **Timing:** before timing anything, check that the laptop is on mains power. Ask only if it is on battery.
- **Kaggle:**
  - Training code lives in the project (`src/emotion_analyzer/`). `scripts/package_kaggle.py` builds `kaggle/code/` from it.
  - The Kaggle steps live in `KAGGLE.md` as complete numbered cells, each with its expected output and run time. Update `KAGGLE.md` whenever a cell changes.
  - The run has two passes: S0 interactively, then Save & Run All (Commit) in the background.
  - Kaggle code uses both T4s where it helps; runs the GPU stages as subprocesses with the corrected `LD_LIBRARY_PATH`; keeps features in `/tmp` and only small results in `/kaggle/working`; resumes from `state/` markers found in `/kaggle/working` or any `/kaggle/input/*/`; stops safely before 12 h; and ends with one compact results block.
  - Smoke-test locally on a tiny subset before any Kaggle run.
- **Data, licences and secrets:**
  - Never commit MELD audio, and never use it as demo samples.
  - Per-utterance transcripts and predictions stay in the git-ignored `data/kaggle/`. `results/` holds aggregates only.
  - Never use a banned checkpoint (§4.4).
  - Never print or commit secrets. Read keys from `.env`, which is git-ignored.

## 16. Risks and mitigations

| Risk | Mitigation |
|---|---|
| MELD audio is noisy (laugh tracks, music, overlapping speech), so the sound branch is weak | Expected (40–46). Report it honestly. Fusion and the disagreement flag still add value |
| Subtitle references inflate WER | Normalise the text. State the caveat. Compare windows on the same references |
| The 10 s window is untested on noisy speech | The WER rule in §8.1 decides in case (a); in case (b), where latency fixes the window at 10 s, its WER cost is recorded. Ablation W measures the effect on the sound model |
| GPU fp16 features differ from CPU int8 features | Parity check (AC-07). If it fails, retrain the head on CPU-int8 features extracted locally |
| CTranslate2 cannot load cuBLAS 12 or cuDNN 9 on the Kaggle image | S0 checks it in a subprocess before the commit. Fixes in §9.2: the pip NVIDIA libraries plus `LD_LIBRARY_PATH`, or `ctranslate2==4.4.0`. Final fallback: `transformers` Whisper on the GPU |
| The interactive session times out during a long run | The main run is a background commit (§9.1); interactive use is limited to the S0 check |
| A commit fails part-way | Stage markers, plus the previous version's output attached as an input, so finished stages are skipped (§9.3) |
| Campus Wi-Fi blocks device-to-device traffic, or Windows treats the network as Public | Set the network to Private. If the phone still can't connect, use a phone hotspot or the tunnel for AC-12 |
| The `/export` format, or its behaviour after context compaction, is unknown until tried | A trial export at the end of the first sitting; the converter is built against it; the session's `.jsonl` log is the fallback source |
| The Hugging Face download fails on Kaggle | Fallback input `ngocson2002/meld-datasetv2` |
| Class imbalance (fear and disgust about 2.7% of train) | Class-weighted loss. Report macro-F1 too |
| The same cast in every split (speaker-dependent) | The own-recordings test of new voices |
| Laptop has about 3 GB of free RAM | int8 models loaded once, a single worker, AC-09 |
| Browser microphone needs HTTPS | Self-signed HTTPS on the local network, tunnel HTTPS, upload as fallback |
| *Friends* audio is copyrighted | No MELD audio in the repository or the demo; the Kaggle copy is private |
| Chatbot free-tier limits or changes | Record the model and date. Manual ChatGPT fallback |

## 17. Decisions (settled in v1.1)

| Decision | Settled as | Alternative not taken |
|---|---|---|
| Internet link | Optional Cloudflare quick tunnel, on demand | Local network only |
| Chatbot comparison | Gemini free API (ChatGPT by hand only if the API is unavailable) | ChatGPT by hand |
| Text model at inference | The rule in §8.3, applied at the start of Phase 6 | Fixed single seed or fixed ensemble |
| Overall label for multi-segment audio | Duration-weighted mean of fused probabilities | Majority vote of the segments |
| Disagreement threshold | Both confidences ≥ 0.40 | 0.30 or 0.50 |

## 18. References

- Poria et al., "MELD: A Multimodal Multi-Party Dataset for Emotion Recognition in Conversations", ACL 2019. <https://arxiv.org/abs/1810.02508>. Data: <https://github.com/declare-lab/MELD>. Audio mirror: <https://huggingface.co/datasets/ajyy/MELD_audio>.
- Hsu et al., "EmotionLines: An Emotion Corpus of Multi-Party Conversations", LREC 2018. MELD asks that this be cited too.
- Cao et al., "CREMA-D: Crowd-sourced Emotional Multimodal Actors Dataset", IEEE TAC 2014. <https://github.com/CheyneyComputerScience/CREMA-D>
- Livingstone and Russo, "The Ryerson Audio-Visual Database of Emotional Speech and Song (RAVDESS)", PLoS ONE 2018. <https://zenodo.org/records/1188976>
- Radford et al., "Robust Speech Recognition via Large-Scale Weak Supervision" (Whisper), 2022. faster-whisper: <https://github.com/SYSTRAN/faster-whisper>. CTranslate2 Whisper API: <https://opennmt.net/CTranslate2/python/ctranslate2.models.Whisper.html>
- Liu et al., "RoBERTa: A Robustly Optimized BERT Pretraining Approach", 2019.
- Evidence for the design choices:
  - EmoBox (Whisper encoder strongest on 23 of 32 datasets): <https://arxiv.org/abs/2406.07162>
  - CARE (MELD audio-only and ASR-text results): <https://arxiv.org/abs/2409.05566>
  - Whisper-AT (one Whisper pass for transcript and audio tags): <https://arxiv.org/abs/2307.03183>
  - COSMIC: <https://arxiv.org/abs/2010.02795>; EmoBERTa: <https://arxiv.org/abs/2108.12009> (MELD text results)
  - Fusion gains on MELD: <https://arxiv.org/abs/2302.02447>
  - Effect of ASR errors: <https://arxiv.org/abs/2406.08353>
  - Whisper WER on MELD versus IEMOCAP: <https://arxiv.org/abs/2305.16065>
- Kaggle execution facts (12-hour limit for CPU and GPU sessions, 20 GB auto-saved `/kaggle/working`, background Save & Run All commits without an idle timer, the interactive idle timeout): <https://www.kaggle.com/docs/notebooks>, <https://www.kaggle.com/docs/efficient-gpu-usage>, <https://www.kaggle.com/product-feedback/302908>, <https://www.kaggle.com/general/232625>
- CTranslate2 and cuDNN 9 on CUDA, with the documented fixes: <https://github.com/SYSTRAN/faster-whisper/discussions/1114>, <https://github.com/OpenNMT/CTranslate2/issues/1780>

## 19. Glossary

| Term | Meaning |
|---|---|
| ASR | Automatic speech recognition (speech-to-text) |
| CI | Confidence interval |
| CPU / GPU | Central / graphics processing unit |
| fp16 / int8 | 16-bit floating point / 8-bit integer number formats; int8 makes CPU inference smaller and faster |
| Log-mel spectrogram | The time–frequency picture of audio that Whisper's encoder reads |
| MELD | Multimodal EmotionLines Dataset |
| SER | Speech emotion recognition |
| VAD | Voice activity detection: finding where speech is |
| WER | Word error rate |
| Weighted-F1 / macro-F1 | F1 averaged over classes, weighted by class size / unweighted |

## 20. Change log

| Version | Date | Change | Reason |
|---|---|---|---|
| 1.0 | 2026-10-20 | Initial specification | — |
| 1.1 | 2026-10-20 | Accepted the 15 findings from the spec review in `tasks.md`: calibration and an offline check added (F1; AC-16, AC-17); all three text seeds exported and the ensemble chosen by a rule (F2); per-utterance outputs kept out of git (F3); VAD on every clip (F4); seed means for every trained row, plus a deployed-system row (F5); model size settled in Phase 3 (F6); chunked transcription of long clips (F7); resume searches every attached input (F8); fusion weight and temperatures fitted at the start of Phase 6 (F9); WER wording corrected (F10); `pyproject.toml` and a versioned pre-commit hook (F11); demo-sample folder (F12); Wi-Fi isolation risk (F13); trial export (F14); Gemini consent (F15). Settled every §17 decision. Kaggle zip goes from Downloads to `data/kaggle/`. Hand-offs go through files instead of pasted text: `s0_check.txt`, `logs/final_results.txt` in the zip, the server access log and `results/offline_check.txt` | Spec review before the build; avoids a second Kaggle run and unnecessary stops during the build |
| 1.2 | 2026-10-20 | Text-ensemble rule applied at the start of Phase 6, before the temperatures and the fusion weight are fitted. The +1.0 is text-only weighted-F1 on the dev Whisper transcripts, and the ensemble must also keep AC-08 and AC-09. `latency.py` moves to Phase 6 for this check (§8.3, §8.4, §14, §17) | The Phase 6 fit, the Phase 6 parity check, and R9 and the latency report in Phase 7 all need the deployed text model, which v1.1 decided only in Phase 8. Three int8 RoBERTa copies add about 0.5 GB against the memory cap |
| 1.2 | 2026-10-20 | §15 brought in line with `CLAUDE.md`: one commit per phase, and the same flow and stop rules | §15 still said to commit after every task, and lacked the flow rules that `CLAUDE.md` follows |
| 1.2 | 2026-10-20 | Window rule rewritten as three cases, set by timing small.en in both windows in Phase 3 (§6.1, §8.1, §9.3 S4, AC-02, §14, §16): (a) both windows meet AC-08, so S4 chooses by WER; (b) only the 10 s window meets AC-08, so the window is fixed at 10 s and S4 records the WER cost; (c) neither does, so `base.en` is adopted before Phase 4 | v1.1 settled the model size against the preliminary window, but S4 makes the final window choice after training is fixed. Had S4 picked 30 s, AC-08 could have failed with no cheap way back |
| 1.2 | 2026-10-20 | Speech test clips generated once with Windows' built-in text-to-speech (`tools/make_fixtures.ps1`) and committed in `tests/fixtures/`, the only audio in git (§4.3, AC-11, AC-13, §13, §14, §15) | With VAD on every clip, a synthetic tone reads as silence, so the normal-clip and long-recording tests need real speech. Committed fixtures keep the tests independent of text-to-speech at run time |
| 1.2 | 2026-10-20 | `tasks.md` only: the mains-power check moved from the Phase 3 WER task to the timing task | Only timing needs mains power |
