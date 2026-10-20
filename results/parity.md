# CPU parity on MELD dev (§10.5, AC-07)

Kaggle: faster-whisper small.en float16 on a T4 and the text model in fp16 on the GPU. Laptop: small.en int8 on the CPU, the same sound head, and the text model in fp32 on the CPU. 1106 dev clips, 30 s window, the same fusion.json temperatures and weight on both sides.

| Branch | Kaggle fp16 | Laptop CPU | Difference | Within 1.5 |
|---|---:|---:|---:|---|
| sound | 53.13 | 53.76 | +0.63 | yes |
| text | 50.30 | 50.51 | +0.21 | yes |
| fused | 55.24 | 54.77 | -0.46 | yes |

Weighted-F1 in points; difference = laptop minus Kaggle.

- Same predicted label on both paths: sound 98.4% of clips, text 97.2%.
- Transcripts: 87.3% identical; WER 26.03% on Kaggle and 26.07% on the laptop.
- The fp32 text model on Kaggle's own transcripts scores 50.19, so the text model on the CPU alone moves text by -0.11; the rest of the text difference comes from the transcripts.

**AC-07: pass** (every difference must be within 1.5 points).
