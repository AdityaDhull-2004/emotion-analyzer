# CPU latency (§10.4)

Deployed system on the laptop CPU (Intel i7-1260P), on mains power: True. Clip `speech_short.wav` (4.96 s); 2 warm-up and 20 timed runs; 2026-10-20.

Models: faster-whisper small.en int8, 30 s window; attnpool-v1; roberta-base-meld-v1 (fp32); fusion w_sound 0.5.

| Stage | Median (ms) | p90 (ms) |
|---|---:|---:|
| decode | 121 | 130 |
| encode | 1225 | 1267 |
| transcribe | 273 | 283 |
| sound | 2 | 2 |
| text | 33 | 38 |
| fusion | 0 | 0 |
| **total (end to end)** | **1648** | **1710** |

`decode` includes the VAD pass. The total is wall-clock per request, so it also covers the small gaps between stages.

- Model loading: 7.0 s, once at start-up.
- Peak memory of the process (models loaded, then the timed runs): **1.40 GB**.

**AC-08** (median ≤ 2.0 s per 5 s clip): 1.65 s, **pass**; the 1.2 s stretch target is not met.  
**AC-09** (server peak memory ≤ 2.5 GB): 1.40 GB, **pass**.
