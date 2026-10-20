"""Fusion (spec §8.4, §5.3): temperature scaling, weighted log-probability fusion, the
weight search, the disagreement rule, and the per-recording answer that the app and
the latency benchmark both use (`Analyzer`).

    log p_fused = w * log p_sound' + (1 - w) * log p_text'   ->  softmax-renormalise
where p' = softmax(log p / T) is each branch after temperature scaling.
"""

import json
import time
from pathlib import Path

import numpy as np
from scipy.optimize import minimize_scalar

from . import config, metrics

EPS = 1e-12


def _softmax(logits):
    z = logits - logits.max(axis=-1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=-1, keepdims=True)


def calibrate(probs, temperature=1.0):
    """Temperature-scale probabilities: softmax(log p / T). Works on (7,) or (N, 7)."""
    return _softmax(np.log(np.asarray(probs, dtype=np.float64) + EPS) / temperature)


def fit_temperature(probs, labels):
    """T minimising the negative log-likelihood of `labels` on dev (§8.4)."""
    logp = np.log(np.asarray(probs, dtype=np.float64) + EPS)
    labels = np.asarray(labels)

    def nll(log_t):
        p = _softmax(logp / np.exp(log_t))
        return -np.mean(np.log(p[np.arange(len(labels)), labels] + EPS))

    res = minimize_scalar(nll, bounds=(np.log(0.05), np.log(20.0)), method="bounded")
    return float(np.exp(res.x))


def fuse(p_sound, p_text, w, t_sound=1.0, t_text=1.0):
    """Weighted log-probability fusion of the temperature-scaled branches."""
    ls = np.log(calibrate(p_sound, t_sound) + EPS)
    lt = np.log(calibrate(p_text, t_text) + EPS)
    return _softmax(w * ls + (1.0 - w) * lt)


def search_weight(p_sound, p_text, labels, t_sound=1.0, t_text=1.0,
                  grid=config.FUSION_WEIGHT_GRID):
    """w maximising dev weighted-F1 over the grid; ties go to the smallest w.
    Returns (w, [(w, weighted-F1), ...])."""
    table = [(w, metrics.weighted_f1(labels, fuse(p_sound, p_text, w, t_sound, t_text).argmax(1)))
             for w in grid]
    best = max(table, key=lambda r: (r[1], -r[0]))
    return best[0], table


def disagreement(sound, text, min_conf=config.DISAGREEMENT_MIN_CONF):
    """True when the branches pick different labels and both are confident (§5.3)."""
    return (sound["label"] != text["label"] and sound["confidence"] >= min_conf
            and text["confidence"] >= min_conf)


def answer(probs):
    """{"label", "confidence", "probs"} in the fixed label order (§5.3)."""
    probs = np.asarray(probs, dtype=np.float64)
    i = int(probs.argmax())
    return {"label": config.LABELS[i], "confidence": round(float(probs[i]), 4),
            "probs": {label: round(float(p), 4) for label, p in zip(config.LABELS, probs)}}


def overall(fused_probs, durations):
    """Duration-weighted mean of the segments' fused probabilities (§5.3, §17)."""
    fused_probs, durations = np.asarray(fused_probs), np.asarray(durations, dtype=np.float64)
    return (fused_probs * durations[:, None]).sum(0) / durations.sum()


def save_params(path, t_sound, t_text, w_sound, extra=None):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"t_sound": t_sound, "t_text": t_text, "w_sound": w_sound,
                                **(extra or {})}, indent=2))


def load_params(path):
    return json.loads(Path(path).read_text())


class Analyzer:
    """The whole path from an audio file to the §5.3 response, with per-stage timing.

    speech_pipe: speech.SpeechPipeline; sound: object with predict_proba(list of frames);
    text: object with predict_proba(list of str) and a `name`; params: fusion.json dict.
    """

    def __init__(self, speech_pipe, sound, text, params, sound_name="attnpool-v1",
                 min_conf=config.DISAGREEMENT_MIN_CONF):
        self.speech = speech_pipe
        self.sound = sound
        self.text = text
        self.params = params
        self.sound_name = sound_name
        self.min_conf = min_conf

    def models_info(self):
        return {"asr": self.speech.name, "window_s": self.speech.window_s,
                "sound": self.sound_name, "text": self.text.name,
                "fusion_w_sound": self.params["w_sound"]}

    def analyze(self, source):
        from . import speech

        t_start = time.perf_counter()
        timer = speech.Timer()
        with timer.stage("decode"):
            audio = speech.decode(source)
            duration = speech.check_duration(audio)
            spans = speech.segment(audio)
        response = {"speech_detected": bool(spans), "duration_s": round(duration, 2),
                    "segments": [], "overall": None}
        sr = config.SAMPLE_RATE
        p = self.params
        fused_all, durations = [], []
        for start, end in spans:
            frames, transcript, _ = self.speech.analyze_segment(
                audio[int(start * sr):int(end * sr)], timer)
            with timer.stage("sound"):
                p_sound = calibrate(self.sound.predict_proba([frames])[0], p["t_sound"])
            with timer.stage("text"):
                if transcript.strip():
                    p_text = calibrate(self.text.predict_proba([transcript])[0], p["t_text"])
                else:  # nothing intelligible: the text branch abstains
                    p_text = np.full(config.NUM_LABELS, 1.0 / config.NUM_LABELS)
            with timer.stage("fusion"):
                p_fused = fuse(p_sound, p_text, p["w_sound"])
                s, t, f = answer(p_sound), answer(p_text), answer(p_fused)
                response["segments"].append({
                    "start_s": round(start, 2), "end_s": round(end, 2),
                    "transcript": transcript, "sound": s, "text": t, "fused": f,
                    "disagreement": disagreement(s, t, self.min_conf)})
                fused_all.append(p_fused)
                durations.append(end - start)
        if fused_all:
            with timer.stage("fusion"):
                response["overall"] = answer(overall(fused_all, durations))
        ms = {k: round(timer.ms.get(k, 0.0)) for k in
              ["decode", "encode", "transcribe", "sound", "text", "fusion"]}
        ms["total"] = round(1000 * (time.perf_counter() - t_start))
        response["timing_ms"] = ms
        response["models"] = self.models_info()
        return response


def load_predictions(*paths):
    """Average one or more .npz prediction files (ids, labels, probs) over the same ids:
    one file is a single seed, several are the ensemble mean (§8.3)."""
    files = [np.load(p) for p in paths]
    ids = files[0]["ids"]
    for f in files[1:]:
        if not np.array_equal(f["ids"], ids):
            raise ValueError("prediction files cover different clips")
    return ids, files[0]["labels"], np.mean([f["probs"] for f in files], axis=0)


def align(sound, text):
    """Restrict two (ids, labels, probs) triples to their common ids, in sound order."""
    s_ids, s_lab, s_p = sound
    t_ids, t_lab, t_p = text
    pos = {i: k for k, i in enumerate(t_ids)}
    keep = [k for k, i in enumerate(s_ids) if i in pos]
    tk = [pos[s_ids[k]] for k in keep]
    if not np.array_equal(s_lab[keep], t_lab[tk]):
        raise ValueError("sound and text labels disagree for the same clip")
    return s_ids[keep], s_lab[keep], s_p[keep], t_p[tk]


def fit(p_sound, p_text, labels):
    """F1, F9: temperatures by NLL on dev, then the weight by dev weighted-F1."""
    t_sound, t_text = fit_temperature(p_sound, labels), fit_temperature(p_text, labels)
    w, table = search_weight(p_sound, p_text, labels, t_sound, t_text)
    return {"t_sound": t_sound, "t_text": t_text, "w_sound": w, "grid": table}


def main(argv=None):
    """python -m emotion_analyzer.fusion --sound pred_dev.npz --text pred_dev_whisper.npz
    [more text files = the ensemble] --out models/fusion.json"""
    import argparse

    ap = argparse.ArgumentParser(description="Fit the temperatures and the fusion weight on dev")
    ap.add_argument("--sound", nargs="+", required=True)
    ap.add_argument("--text", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    ids, labels, ps, pt = align(load_predictions(*args.sound), load_predictions(*args.text))
    params = fit(ps, pt, labels)
    fused = fuse(ps, pt, params["w_sound"], params["t_sound"], params["t_text"])
    dev = {name: round(metrics.weighted_f1(labels, p.argmax(1)), 2)
           for name, p in (("sound", ps), ("text", pt), ("fused", fused))}
    save_params(args.out, params["t_sound"], params["t_text"], params["w_sound"],
                {"n_dev": int(len(ids)), "dev_weighted_f1": dev, "grid": params["grid"]})
    print(f"fusion: T_sound {params['t_sound']:.3f}, T_text {params['t_text']:.3f}, "
          f"w_sound {params['w_sound']}, dev wF1 {dev}")


if __name__ == "__main__":
    main()
