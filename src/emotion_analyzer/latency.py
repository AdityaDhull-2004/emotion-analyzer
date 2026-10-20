"""Per-stage CPU timing benchmark (spec §10.4): 2 warm-up runs, then 20 timed runs on a
5 s clip; median and 90th percentile per stage and in total, plus peak memory.

--preliminary (Phase 3) times the real speech stages and stands in for the untrained
models with same-sized ones: an int8 RoBERTa-base with an untrained 7-way head and a
random attention-pooling head. Run it on mains power.

    python -m emotion_analyzer.latency --preliminary --windows 10 30
"""

import argparse
import json
import platform
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import psutil

from . import config, speech

STAGES = ["decode", "encode", "transcribe", "sound", "text", "fusion"]


def on_mains_power():
    """True on AC power, False on battery, None if unknown (Windows only)."""
    if platform.system() != "Windows":
        return None
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_Battery | Select-Object -First 1).BatteryStatus"],
            capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return None
    if not out:
        return True  # no battery: a desktop on mains
    return out == "2"


def peak_memory_gb():
    info = psutil.Process().memory_info()
    peak = getattr(info, "peak_wset", None) or getattr(info, "rss", 0)
    return peak / 2**30


def summarize(runs):
    """runs: list of {stage: ms}. Returns {stage: {median, p90}} including total."""
    out = {}
    for stage in STAGES + ["total"]:
        vals = np.array([r.get(stage, 0.0) for r in runs])
        out[stage] = {"median": float(np.median(vals)), "p90": float(np.percentile(vals, 90))}
    return out


class _ProxyModels:
    """Same-sized stand-ins for the sound head and text model (Phase 3 only)."""

    def __init__(self):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        torch.manual_seed(0)
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained("FacebookAI/roberta-base")
        model = AutoModelForSequenceClassification.from_pretrained(
            "FacebookAI/roberta-base", num_labels=config.NUM_LABELS)
        self.text_model = torch.ao.quantization.quantize_dynamic(
            model.eval(), {torch.nn.Linear}, dtype=torch.qint8)
        self.proj = torch.nn.Sequential(torch.nn.LayerNorm(768), torch.nn.Linear(768, 256),
                                        torch.nn.GELU())
        self.att_w = torch.nn.Linear(256, 256)
        self.att_v = torch.nn.Linear(256, 1, bias=False)
        self.out = torch.nn.Linear(256, config.NUM_LABELS)

    def sound(self, frames):
        torch = self.torch
        with torch.inference_mode():
            h = self.proj(torch.from_numpy(np.ascontiguousarray(frames, dtype=np.float32)))
            a = torch.softmax(self.att_v(torch.tanh(self.att_w(h))).squeeze(-1), dim=0)
            return torch.softmax(self.out((a[:, None] * h).sum(0)), -1).numpy()

    def text(self, transcript):
        torch = self.torch
        enc = self.tok(transcript, truncation=True, max_length=64, return_tensors="pt")
        with torch.inference_mode():
            return torch.softmax(self.text_model(**enc).logits[0], -1).numpy()


def preliminary_run(pipe, models, clip_path, window_s):
    timer = speech.Timer()
    with timer.stage("decode"):
        audio = speech.decode(str(clip_path))
        speech.check_duration(audio)
        segs = speech.segment(audio)
    sr = config.SAMPLE_RATE
    for s, e in segs:
        frames, text, _ = pipe.analyze_segment(audio[int(s * sr):int(e * sr)], timer, window_s)
        with timer.stage("sound"):
            p_sound = models.sound(frames)
        with timer.stage("text"):
            p_text = models.text(text)
        with timer.stage("fusion"):
            logp = 0.35 * np.log(p_sound + 1e-12) + 0.65 * np.log(p_text + 1e-12)
            np.exp(logp - logp.max()) / np.exp(logp - logp.max()).sum()
    ms = dict(timer.ms)
    ms["total"] = sum(ms.get(s, 0.0) for s in STAGES)
    return ms


def benchmark_preliminary(clip, windows, warmup=2, runs=20, model_size=config.ASR_MODEL):
    pipe = speech.SpeechPipeline(model_size, window_s=windows[0])
    models = _ProxyModels()
    results = {}
    for w in windows:
        for _ in range(warmup):
            preliminary_run(pipe, models, clip, w)
        timed = [preliminary_run(pipe, models, clip, w) for _ in range(runs)]
        results[f"{w}s"] = summarize(timed)
    return results


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clip", default=str(config.FIXTURES_DIR / "speech_short.wav"))
    ap.add_argument("--windows", type=int, nargs="+", default=list(config.WINDOWS_S))
    ap.add_argument("--model", default=config.ASR_MODEL)
    ap.add_argument("--warmup", type=int, default=2)
    ap.add_argument("--runs", type=int, default=20)
    ap.add_argument("--preliminary", action="store_true")
    ap.add_argument("--json", default=None, help="write the results here")
    args = ap.parse_args(argv)

    mains = on_mains_power()
    if mains is False:
        print("WARNING: the laptop is on battery; timings are not valid for AC-08.",
              file=sys.stderr)
    if not args.preliminary:
        ap.error("the full benchmark arrives in Phase 6; use --preliminary")
    t0 = time.perf_counter()
    res = benchmark_preliminary(args.clip, args.windows, args.warmup, args.runs, args.model)
    report = {"mode": "preliminary", "model": args.model, "clip": Path(args.clip).name,
              "mains_power": mains, "peak_memory_gb": round(peak_memory_gb(), 3),
              "runs": args.runs, "warmup": args.warmup, "stages_ms": res,
              "wall_s": round(time.perf_counter() - t0, 1)}
    for w, stages in res.items():
        row = "  ".join(f"{s} {v['median']:.0f}/{v['p90']:.0f}" for s, v in stages.items())
        print(f"{w}: median/p90 ms  {row}")
    print(f"peak memory {report['peak_memory_gb']:.2f} GB; mains power: {mains}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
