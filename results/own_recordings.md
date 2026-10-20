# Own recordings: new voices (§10.6, AC-10)

The deployed system (faster-whisper small.en int8, 30 s window; attnpool-v1; roberta-base-meld-v1 fp32; w_sound 0.5) on the user's 28 recordings in `data/own/`, labelled by file name. Transcripts stay out of this file (the recordings are private); they are in the git-ignored `data/own_eval.csv`.

| Output | Accuracy | 95% CI (accuracy) | Weighted-F1 | Macro-F1 |
|---|---:|---|---:|---:|
| Sound | 28.6 | 10.7–46.4 | 20.4 | 20.4 |
| Text | 60.7 | 42.9–78.6 | 59.7 | 59.7 |
| Fused (the app's answer) | 57.1 | 39.3–75.0 | 58.0 | 58.0 |

Chance is 14.3% accuracy with 7 balanced classes. Median processing time 1682 ms per clip (mean duration 5.1 s).

## Before and after the fusion refit

**The fusion weight was changed after these recordings were first scored, and because of that result.** The first run (w_sound 0.75, chosen on all of MELD dev) had the app right on 35.7% of the clips while the text branch alone got 60.7%. The weight was then chosen again (spec v1.4, §8.4) on MELD dev, using only the clips from speakers outside the six main characters. These recordings weren't used to choose it, but the change came after seeing them, so they are no longer a blind test.

| Output | Accuracy before | Accuracy after | Weighted-F1 before | Weighted-F1 after |
|---|---:|---:|---:|---:|
| Sound | 28.6 | 28.6 | 20.4 | 20.4 |
| Text | 60.7 | 60.7 | 59.7 | 59.7 |
| Fused (the app's answer) | 35.7 | 57.1 | 29.8 | 58.0 |

The sound and text branches don't change; only the weight that combines them does.

| File | True | Sound | Text | Fused | Fused before | Disagreement |
|---|---|---|---|---|---|---|
| anger_01.m4a | anger | surprise 0.27 | **anger** 0.60 | **anger** 0.35 | **anger** 0.24 |  |
| anger_02.m4a | anger | joy 0.23 | **anger** 0.56 | **anger** 0.31 | disgust 0.22 |  |
| anger_03.m4a | anger | neutral 0.52 | **anger** 0.43 | neutral 0.38 | neutral 0.45 | yes |
| anger_04.m4a | anger | neutral 0.40 | neutral 0.42 | neutral 0.42 | neutral 0.41 |  |
| disgust_01.m4a | disgust | neutral 0.29 | surprise 0.28 | surprise 0.22 | neutral 0.19 |  |
| disgust_02.m4a | disgust | joy 0.32 | **disgust** 0.37 | **disgust** 0.24 | joy 0.23 |  |
| disgust_03.m4a | disgust | neutral 0.48 | sadness 0.33 | neutral 0.29 | neutral 0.39 |  |
| disgust_04.m4a | disgust | neutral 0.31 | surprise 0.78 | surprise 0.53 | surprise 0.37 |  |
| fear_01.m4a | fear | neutral 0.38 | neutral 0.45 | neutral 0.43 | neutral 0.41 |  |
| fear_02.m4a | fear | sadness 0.46 | **fear** 0.52 | **fear** 0.31 | sadness 0.39 | yes |
| fear_03.m4a | fear | neutral 0.52 | sadness 0.39 | neutral 0.36 | neutral 0.44 |  |
| fear_04.m4a | fear | neutral 0.69 | neutral 0.57 | neutral 0.65 | neutral 0.67 |  |
| joy_01.m4a | joy | surprise 0.46 | surprise 0.66 | surprise 0.58 | surprise 0.53 |  |
| joy_02.m4a | joy | **joy** 0.25 | **joy** 0.80 | **joy** 0.54 | **joy** 0.39 |  |
| joy_03.m4a | joy | neutral 0.25 | **joy** 0.63 | **joy** 0.43 | **joy** 0.34 |  |
| joy_04.m4a | joy | **joy** 0.47 | **joy** 0.63 | **joy** 0.56 | **joy** 0.52 |  |
| neutral_01.m4a | neutral | **neutral** 0.76 | **neutral** 0.67 | **neutral** 0.72 | **neutral** 0.75 |  |
| neutral_02.m4a | neutral | **neutral** 0.58 | **neutral** 0.71 | **neutral** 0.66 | **neutral** 0.62 |  |
| neutral_03.m4a | neutral | **neutral** 0.46 | surprise 0.51 | surprise 0.35 | **neutral** 0.40 | yes |
| neutral_04.m4a | neutral | **neutral** 0.92 | **neutral** 0.73 | **neutral** 0.85 | **neutral** 0.89 |  |
| sadness_01.m4a | sadness | neutral 0.29 | **sadness** 0.32 | **sadness** 0.29 | neutral 0.27 |  |
| sadness_02.m4a | sadness | **sadness** 0.39 | **sadness** 0.62 | **sadness** 0.52 | **sadness** 0.45 |  |
| sadness_03.m4a | sadness | neutral 0.49 | neutral 0.44 | neutral 0.48 | neutral 0.49 |  |
| sadness_04.m4a | sadness | neutral 0.38 | neutral 0.48 | neutral 0.45 | neutral 0.43 |  |
| surprise_01.m4a | surprise | **surprise** 0.49 | **surprise** 0.78 | **surprise** 0.68 | **surprise** 0.60 |  |
| surprise_02.m4a | surprise | joy 0.22 | **surprise** 0.69 | **surprise** 0.33 | joy 0.20 |  |
| surprise_03.m4a | surprise | neutral 0.53 | **surprise** 0.82 | **surprise** 0.40 | neutral 0.37 | yes |
| surprise_04.m4a | surprise | neutral 0.54 | **surprise** 0.51 | **surprise** 0.33 | neutral 0.43 | yes |

Bold = correct. Fused confusion (rows true, columns predicted, order anger, disgust, fear, joy, neutral, sadness, surprise):

```
 2  0  0  0  2  0  0
 0  1  0  0  1  0  2
 0  0  1  0  3  0  0
 0  0  0  3  0  0  1
 0  0  0  0  3  0  1
 0  0  0  0  2  2  0
 0  0  0  0  0  0  4
```

**Caveat: a small sample.** 28 clips (4 per emotion), acted on purpose rather than spontaneous speech like MELD's. One clip moves accuracy by 3.6 points, and the bootstrap interval above is wide. These numbers show whether the system transfers to new voices at all; they don't estimate its accuracy precisely.
