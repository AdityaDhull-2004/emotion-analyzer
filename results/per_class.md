# Per-class results on MELD test (§10.1)

The deployed system's branches and its fused output (R9). Precision, recall and F1 in points; support is the number of test utterances.

## Sound (how it sounds)

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| anger | 48.8 | 36.8 | 42.0 | 345 |
| disgust | 17.2 | 14.7 | 15.9 | 68 |
| fear | 27.8 | 10.0 | 14.7 | 50 |
| joy | 42.8 | 38.6 | 40.6 | 402 |
| neutral | 64.1 | 75.4 | 69.3 | 1256 |
| sadness | 39.0 | 14.4 | 21.1 | 208 |
| surprise | 38.7 | 49.1 | 43.3 | 281 |

Weighted-F1 52.2, macro-F1 35.2, accuracy 54.1. Confusion matrix: `confusion_sound.png`.

## Text (what was said, fp32, Whisper transcripts)

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| anger | 38.6 | 31.9 | 34.9 | 345 |
| disgust | 100.0 | 2.9 | 5.7 | 68 |
| fear | 11.8 | 12.0 | 11.9 | 50 |
| joy | 51.2 | 35.8 | 42.2 | 402 |
| neutral | 63.6 | 76.4 | 69.4 | 1256 |
| sadness | 34.7 | 32.2 | 33.4 | 208 |
| surprise | 46.4 | 48.0 | 47.2 | 281 |

Weighted-F1 52.6, macro-F1 35.0, accuracy 54.5. Confusion matrix: `confusion_text.png`.

## Fused (deployed)

| Class | Precision | Recall | F1 | Support |
|---|---:|---:|---:|---:|
| anger | 48.0 | 37.7 | 42.2 | 345 |
| disgust | 21.4 | 8.8 | 12.5 | 68 |
| fear | 29.4 | 10.0 | 14.9 | 50 |
| joy | 50.0 | 40.0 | 44.5 | 402 |
| neutral | 64.2 | 79.1 | 70.9 | 1256 |
| sadness | 43.0 | 19.2 | 26.6 | 208 |
| surprise | 45.2 | 53.0 | 48.8 | 281 |

Weighted-F1 54.5, macro-F1 37.2, accuracy 56.9. Confusion matrix: `confusion_fused.png`.
