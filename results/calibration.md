# Calibration on MELD test (§10.4b, AC-16)

Expected calibration error (ECE, 15 equal-width confidence bins, in points) and negative log-likelihood, before and after temperature scaling. The temperatures were fitted on dev by NLL: T_sound 0.814, T_text 1.009. Both fused rows use the deployed weight w_sound 0.75.

| Output | ECE before | ECE after | NLL before | NLL after | Accuracy |
|---|---:|---:|---:|---:|---:|
| Fused (deployed weight) | 9.51 | 6.04 | 1.257 | 1.242 | 56.9 |
| Sound branch | 7.70 | 4.39 | 1.311 | 1.299 | 54.1 |
| Text branch | 2.42 | 1.98 | 1.321 | 1.321 | 54.5 |

Reliability diagram: `reliability.png` (bins with at least 10 utterances).

**AC-16:** fused test ECE 9.51 before and 6.04 after temperature scaling, with the reliability diagram: **reported**.
