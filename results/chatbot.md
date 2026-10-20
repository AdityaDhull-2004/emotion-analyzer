# Chatbot comparison on the own recordings (§10.7, AC-10)

- **Chatbot:** Google Gemini through the free API (`google-genai`), model `gemini-3.5-flash` (the API reported serving `gemini-3.6-flash`), run on 2026-10-20 with the API's default generation settings.
- **Instruction**, the same for every clip: "Classify the speaker's emotion into exactly one of: anger, disgust, fear, joy, neutral, sadness, surprise. Answer with the label only."
- **Clips:** the user's 27 own recordings, decoded to 16 kHz mono WAV (the same audio our system hears). No MELD clips were sent.
- **Partial:** Gemini has answered 27 of the 28 recordings so far (the free tier allows 20 requests a day per model), so both systems are scored on those clips only. Running `python -m emotion_analyzer.chatbot_compare` again after the quota resets finishes the rest.
- **Ours:** the deployed system on the laptop CPU (the fused answer), from `own_recordings.md`.

| System | Accuracy | 95% CI (accuracy) | Weighted-F1 | Macro-F1 | Median latency per clip | Offline | Audio stays on the laptop |
|---|---:|---|---:|---:|---:|---|---|
| Emotion Analyzer (ours) | 37.0 | 18.5–55.6 | 30.7 | 30.8 | 1.60 s (CPU) | yes | yes |
| Gemini (`gemini-3.5-flash`) | 85.2 | 70.4–96.3 | 84.7 | 85.2 | 15.48 s (online) | no | no |

Gemini gave an answer outside the 7 labels 0 time(s) (counted as wrong). The two systems agree on 37% of clips. Gemini's latency is the API round trip from the laptop, upload included, plus any retries the client library makes while the service is busy (the slowest answer took 105 s), so the median is the fair figure.

**Online and not private.** Each clip leaves the laptop and is processed by Google. Under the Gemini API's free-tier terms, Google may use submitted content to improve its products. The speakers consented to this for the comparison (§7.3). Our system runs offline and the audio never leaves the laptop.

| File | True | Ours (fused) | Gemini |
|---|---|---|---|
| anger_01.m4a | anger | **anger** | **anger** |
| anger_02.m4a | anger | disgust | **anger** |
| anger_03.m4a | anger | neutral | sadness |
| anger_04.m4a | anger | neutral | **anger** |
| disgust_01.m4a | disgust | neutral | **disgust** |
| disgust_02.m4a | disgust | joy | **disgust** |
| disgust_03.m4a | disgust | neutral | fear |
| disgust_04.m4a | disgust | surprise | anger |
| fear_01.m4a | fear | neutral | **fear** |
| fear_02.m4a | fear | sadness | **fear** |
| fear_03.m4a | fear | neutral | **fear** |
| fear_04.m4a | fear | neutral | sadness |
| joy_01.m4a | joy | surprise | **joy** |
| joy_02.m4a | joy | **joy** | **joy** |
| joy_03.m4a | joy | **joy** | **joy** |
| joy_04.m4a | joy | **joy** | **joy** |
| neutral_01.m4a | neutral | **neutral** | **neutral** |
| neutral_02.m4a | neutral | **neutral** | **neutral** |
| neutral_03.m4a | neutral | **neutral** | **neutral** |
| neutral_04.m4a | neutral | **neutral** | **neutral** |
| sadness_01.m4a | sadness | neutral | **sadness** |
| sadness_02.m4a | sadness | **sadness** | **sadness** |
| sadness_03.m4a | sadness | neutral | **sadness** |
| sadness_04.m4a | sadness | neutral | **sadness** |
| surprise_01.m4a | surprise | **surprise** | **surprise** |
| surprise_02.m4a | surprise | joy | **surprise** |
| surprise_03.m4a | surprise | neutral | **surprise** |

Bold = correct. With 27 clips, one clip is 3.7 accuracy points: treat the difference as indicative, and see the confidence intervals.
