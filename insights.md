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
