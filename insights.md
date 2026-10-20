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
