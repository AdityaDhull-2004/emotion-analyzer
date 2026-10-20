# Insights

Results, figures and decisions with numbers, phase by phase.

## P1 Scaffold

- Environment: Python 3.12.10 venv, torch 2.14.1+cpu, faster-whisper 1.2.1 (ctranslate2 4.8.3), transformers 5.20.2. All pinned in `requirements.txt`.
- Every API from §6.1 exists in these versions: `decode_audio`, `pad_or_trim`, `Tokenizer`, `get_speech_timestamps`, `WhisperModel.encode`. So do `quantize_dynamic` and transformers' `EnglishTextNormalizer`.
