# Word error rate (§10.3, AC-02)

faster-whisper small.en, greedy, no timestamps, float16 on Kaggle's T4s. Whisper's English normaliser on reference and hypothesis, then corpus WER with `jiwer`. MELD's references are subtitles, which inflates the figures.

| Split | Window | Clips | Ref. words | Subst. | Del. | Ins. | WER |
|---|---|---:|---:|---:|---:|---:|---:|
| train | 10 s | 9976 | 86409 | 6900 | 8316 | 19904 | **40.64%** |
| train | 30 s | 9976 | 86409 | 6370 | 8166 | 11889 | **30.58%** |
| dev | 10 s | 1106 | 9570 | 720 | 756 | 1575 | **31.88%** |
| dev | 30 s | 1106 | 9570 | 685 | 720 | 1086 | **26.03%** |
| test | 10 s | 2610 | 23253 | 1882 | 1986 | 6290 | **43.68%** |
| test | 30 s | 2610 | 23253 | 1742 | 1990 | 4029 | **33.38%** |

## Window decision (§8.1)

- Phase 3 timing put the build in **case a**: small.en met AC-08 in both windows on the laptop, so S4 chose the window by WER on dev.
- Rule: case a: dev WER gap <= 2.0 -> 10 s, else 30 s.
- WER(10 s) − WER(30 s): **+5.85** points on dev and +10.30 on test.
- Chosen window: **30 s**, recorded in `models/decision.json`.
