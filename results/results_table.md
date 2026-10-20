# MELD test results (§10.2)

MELD test, 2610 utterances. Weighted-F1 is the headline (points). Trained rows show the mean ± sd over seeds 0, 1 and 2; the 95% interval is a bootstrap of the seed mean over test utterances (1000 resamples, seed 0). Fused rows use the deployed weight (w_sound 0.75, fitted on dev).

| Row | Condition | Seeds | Weighted-F1 | 95% CI | Macro-F1 | Accuracy | Dev weighted-F1 |
|---|---|---:|---:|---|---:|---:|---:|
| R0 | Majority baseline (always neutral) | – | **31.3** | 29.4–33.2 | 9.3 | 48.1 | – |
| R1 | Sound only (main) | 3 | **52.3 ± 0.4** | 50.3–54.1 | 35.2 ± 0.5 | 54.1 ± 0.5 | 52.3 ± 0.8 |
| R2 | Sound only, ablation A (plus acted corpora) | 3 | **50.9 ± 0.3** | 49.1–52.6 | 31.5 ± 0.5 | 53.5 ± 0.8 | 51.6 ± 0.8 |
| R3 | Sound only, ablation W (other window) | 3 | **51.4 ± 0.9** | 49.4–53.1 | 33.9 ± 1.0 | 53.0 ± 1.5 | 51.2 ± 0.4 |
| R4 | Text on real transcripts | 3 | **61.5 ± 0.8** | 59.8–63.2 | 44.6 ± 1.1 | 61.5 ± 1.3 | 59.0 ± 2.0 |
| R5 | Text on Whisper transcripts | 3 | **52.3 ± 0.5** | 50.5–54.0 | 36.3 ± 1.2 | 53.4 ± 1.2 | 50.0 ± 0.2 |
| R6 | Text, ablation T (trained on real only), Whisper transcripts | 3 | **52.1 ± 1.5** | 50.1–53.9 | 36.2 ± 1.4 | 53.6 ± 1.9 | 49.9 ± 0.7 |
| R7 | Fused, Whisper transcripts (sound seed i with text seed i) | 3 | **54.2 ± 0.2** | 52.3–56.0 | 37.3 ± 0.4 | 56.3 ± 0.3 | 54.5 ± 0.8 |
| R8 | Fused, real transcripts (same pairing) | 3 | **57.9 ± 0.9** | 56.0–59.7 | 40.9 ± 0.9 | 59.6 ± 0.9 | 57.1 ± 1.2 |
| R9 | Deployed system, Whisper transcripts | 1 | **54.5** | 52.4–56.4 | 37.2 | 56.9 | 54.7 |

- R1–R8 are the Kaggle models' own probabilities (fp16 on the GPU). In R7 and R8 each model is temperature-scaled with its own T, fitted on dev (§8.4), before fusing at the deployed weight.
- R9 is a single run: the deployed sound head (main, seed 1) with its Kaggle test probabilities, and the deployed text model (fp32) on the laptop CPU, run on Kaggle's test Whisper transcripts, fused with `models/fusion.json` (T_sound 0.814, T_text 1.009). MELD test audio isn't kept on the laptop (§7.4), so the remaining CPU difference (int8 Whisper features and transcripts) is measured on dev by the parity check (`parity.md`); R9's dev value is that check's end-to-end CPU result.
- Fusion gain on test, as a difference of seed means with a paired bootstrap 95% interval (both rows scored on the same resampled utterances): R7 − R5 +1.9 [+0.6, +3.3]; R7 − R1 +1.9 [+1.2, +2.5].
