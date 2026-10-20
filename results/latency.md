# CPU latency (§10.4)

Deployed system on the laptop CPU (Intel i7-1260P), on mains power: True. Clip `speech_short.wav` (4.96 s); 2 warm-up and 20 timed runs; 2026-10-20.

Models: faster-whisper small.en int8, 30 s window; attnpool-v1; roberta-base-meld-v1 (fp32); fusion w_sound 0.75.

| Stage | Median (ms) | p90 (ms) |
|---|---:|---:|
| decode | 122 | 130 |
| encode | 1180 | 1220 |
| transcribe | 260 | 273 |
| sound | 2 | 2 |
| text | 28 | 35 |
| fusion | 0 | 0 |
| **total (end to end)** | **1590** | **1644** |

`decode` includes the VAD pass. The total is wall-clock per request, so it also covers the small gaps between stages.

- Model loading: 10.6 s, once at start-up.
- Peak memory of the process (models loaded, then the timed runs): **1.40 GB**.

**AC-08** (median ≤ 2.0 s per 5 s clip): 1.59 s, **pass**; the 1.2 s stretch target is not met.  
**AC-09** (server peak memory ≤ 2.5 GB): 1.40 GB, **pass**.
