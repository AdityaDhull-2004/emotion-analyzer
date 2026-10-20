"""Chatbot comparison (spec §10.7): the user's own recordings sent to Gemini through the
free API, with the same instruction for every clip, scored next to our system.

    python -m emotion_analyzer.chatbot_compare            (after `evaluate own`)

GEMINI_API_KEY is read from the git-ignored .env and never printed. Each clip is decoded
to 16 kHz mono and sent as WAV, the same audio our system hears. Only the own recordings
are sent, never MELD clips (copyright). Generation settings are the API defaults, as a
chatbot user would get. Writes results/chatbot.md and results/chatbot_raw.csv.
"""

import argparse
import io
import re
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import config, data, metrics, speech

INSTRUCTION = ("Classify the speaker's emotion into exactly one of: anger, disgust, fear, joy, "
               "neutral, sadness, surprise. Answer with the label only.")
# Tried in order until one answers; the newest Flash models first (the free API's chat models).
MODELS = ("gemini-3.8-flash", "gemini-3.7-flash", "gemini-3.5-flash", "gemini-2.5-flash")
RAW_CSV = config.RESULTS_DIR / "chatbot_raw.csv"
MIN_INTERVAL_S = 6.5  # stays under the free tier's requests-per-minute limit


def parse_label(answer):
    """The first of the 7 labels named in the answer, or '' when there is none."""
    for word in re.findall(r"[a-z]+", (answer or "").lower()):
        if word in config.LABEL_TO_ID:
            return word
    return ""


def wav_bytes(path):
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, speech.decode(str(path)), config.SAMPLE_RATE, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def api_key():
    from dotenv import dotenv_values

    key = (dotenv_values(config.ROOT / ".env").get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise SystemExit("GEMINI_API_KEY is missing from .env (copy .env.example and add it)")
    return key


class Gemini:
    def __init__(self, models=MODELS):
        from google import genai

        self.client = genai.Client(api_key=api_key())
        self.models = list(models)
        self.model = None
        self.last = 0.0

    def _call(self, model, audio):
        from google.genai import types

        wait = MIN_INTERVAL_S - (time.monotonic() - self.last)
        if wait > 0:
            time.sleep(wait)
        self.last = time.monotonic()
        t0 = time.perf_counter()
        r = self.client.models.generate_content(
            model=model, contents=[INSTRUCTION, types.Part.from_bytes(data=audio, mime_type="audio/wav")])
        return (r.text or "").strip(), time.perf_counter() - t0, getattr(r, "model_version", None) or model

    def ask(self, audio, retries=5):
        """(answer, seconds, model version). The first call picks the first model that
        answers; rate-limit and server errors are retried with a growing pause."""
        from google.genai import errors

        candidates = [self.model] if self.model else self.models
        for model in candidates:
            for attempt in range(retries):
                try:
                    out = self._call(model, audio)
                    self.model = model
                    return out
                except errors.APIError as e:
                    if e.code in (429, 500, 503) and attempt < retries - 1:
                        time.sleep(min(60, 8 * 2 ** attempt))
                        continue
                    if self.model is None and e.code in (400, 403, 404, 429):
                        print(f"  {model}: unavailable ({e.code}); trying the next model")
                        break
                    raise
        raise SystemExit("no Gemini model answered; use the manual ChatGPT fallback (§10.7)")


def run(manifest, bot, log=print):
    rows = []
    for r in manifest.itertuples():
        answer, seconds, version = bot.ask(wav_bytes(r.path))
        rows.append({"file": Path(r.path).name, "label": r.label, "answer": answer,
                     "parsed": parse_label(answer), "latency_s": round(seconds, 2), "model": version})
        log(f"  {rows[-1]['file']}: true {r.label}, Gemini '{answer}' ({seconds:.1f} s)")
    return pd.DataFrame(rows)


def scores(labels, preds):
    y = np.array([config.LABEL_TO_ID[l] for l in labels])
    p = np.array([config.LABEL_TO_ID.get(l, -1) for l in preds])
    p = np.where(p >= 0, p, (y + 1) % config.NUM_LABELS)  # no valid label counts as wrong
    s = metrics.summary(y, p)
    lo, hi = metrics.bootstrap_ci(y, p, metric=metrics.accuracy)
    return {**s, "acc_ci": (lo, hi)}


def markdown(raw, ours, date):
    df = raw.merge(ours[["file", "fused", "fused_conf", "total_ms"]], on="file", how="left")
    g, o = scores(df["label"], df["parsed"]), scores(df["label"], df["fused"].fillna(""))
    invalid = int((df["parsed"] == "").sum())
    agree = 100 * float((df["parsed"] == df["fused"]).mean())
    model = df["model"].iloc[0]
    lines = [
        "# Chatbot comparison on the own recordings (§10.7, AC-10)", "",
        f"- **Chatbot:** Google Gemini through the free API (`google-genai`), model `{model}`, run on {date} "
        "with the API's default generation settings.",
        f"- **Instruction**, the same for every clip: \"{INSTRUCTION}\"",
        f"- **Clips:** the user's {len(df)} own recordings, decoded to 16 kHz mono WAV (the same audio our "
        "system hears). No MELD clips were sent.",
        "- **Ours:** the deployed system on the laptop CPU (the fused answer), from `own_recordings.md`.", "",
        "| System | Accuracy | 95% CI (accuracy) | Weighted-F1 | Macro-F1 | Median latency per clip | Offline | Audio stays on the laptop |",
        "|---|---:|---|---:|---:|---:|---|---|",
        f"| Emotion Analyzer (ours) | {o['accuracy']:.1f} | {o['acc_ci'][0]:.1f}–{o['acc_ci'][1]:.1f} | "
        f"{o['weighted_f1']:.1f} | {o['macro_f1']:.1f} | {df['total_ms'].median() / 1000:.2f} s (CPU) | yes | yes |",
        f"| Gemini (`{model}`) | {g['accuracy']:.1f} | {g['acc_ci'][0]:.1f}–{g['acc_ci'][1]:.1f} | "
        f"{g['weighted_f1']:.1f} | {g['macro_f1']:.1f} | {df['latency_s'].median():.2f} s (online) | no | no |", "",
        f"Gemini gave an answer outside the 7 labels {invalid} time(s) (counted as wrong). The two systems "
        f"agree on {agree:.0f}% of clips. Gemini's latency is the API round trip from the laptop, upload "
        "included.", "",
        "**Online and not private.** Each clip leaves the laptop and is processed by Google. Under the "
        "Gemini API's free-tier terms, Google may use submitted content to improve its products. The "
        "speakers consented to this for the comparison (§7.3). Our system runs offline and the audio never "
        "leaves the laptop.", "",
        "| File | True | Ours (fused) | Gemini |", "|---|---|---|---|"]
    for r in df.itertuples():
        mark = lambda lab: f"**{lab}**" if lab == r.label else (lab or "–")
        lines.append(f"| {r.file} | {r.label} | {mark(r.fused)} | {mark(r.parsed)}"
                     + ("" if r.parsed == r.answer.lower().strip(" .") else f" (\"{r.answer}\")") + " |")
    lines += ["", f"Bold = correct. With {len(df)} clips, one clip is {100 / len(df):.1f} accuracy points: "
              "treat the difference as indicative, and see the confidence intervals."]
    return "\n".join(lines) + "\n", {"gemini": g, "ours": o, "model": model, "invalid": invalid}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--ours", default=str(config.DATA_DIR / "own_eval.csv"),
                    help="per-clip results of `python -m emotion_analyzer.evaluate own`")
    ap.add_argument("--models", nargs="+", default=list(MODELS))
    ap.add_argument("--reuse", action="store_true", help="re-score results/chatbot_raw.csv without calling the API")
    args = ap.parse_args(argv)

    ours = pd.read_csv(args.ours, keep_default_na=False)
    if args.reuse and RAW_CSV.exists():
        raw = pd.read_csv(RAW_CSV, keep_default_na=False)
    else:
        manifest, _ = data.own_manifest()
        raw = run(manifest, Gemini(args.models), log=lambda m: print(m, flush=True))
        config.RESULTS_DIR.mkdir(exist_ok=True)
        raw.to_csv(RAW_CSV, index=False)
    md, s = markdown(raw, ours, time.strftime("%Y-%m-%d"))
    (config.RESULTS_DIR / "chatbot.md").write_text(md, encoding="utf-8")
    print(f"Gemini {s['model']}: accuracy {s['gemini']['accuracy']:.1f}, weighted-F1 "
          f"{s['gemini']['weighted_f1']:.1f}; ours: accuracy {s['ours']['accuracy']:.1f}, weighted-F1 "
          f"{s['ours']['weighted_f1']:.1f}")


if __name__ == "__main__":
    main()
