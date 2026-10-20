"""Text model `roberta-base-meld-v1` (spec §8.3): RoBERTa-base with a 7-label head on
the utterance text alone, its training loop, int8 dynamic quantisation and inference.

Training data: MELD train's real utterances plus the Whisper transcripts of the same
clips, empty transcripts dropped and exact duplicates within a label removed. Model
selection uses dev weighted-F1 on the dev Whisper transcripts.
"""

import json
import math
import time
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from torch import nn

from . import config, data, metrics

MODEL_NAME = "roberta-base-meld-v1"
BASE_MODEL = "FacebookAI/roberta-base"
DEFAULTS = {"lr": 2e-5, "weight_decay": 0.01, "batch_size": 32, "epochs": 6,
            "warmup_ratio": 0.1, "max_length": 64, "fp16": True}


def build_training_set(real_texts, real_labels, whisper_texts=None, whisper_labels=None):
    """Real utterances plus Whisper transcripts with the same labels (§8.3). Returns a
    DataFrame with `text`, `label_id` and `source`."""
    parts = [pd.DataFrame({"text": list(real_texts), "label_id": list(real_labels),
                           "source": "real"})]
    if whisper_texts is not None:
        parts.append(pd.DataFrame({"text": list(whisper_texts), "label_id": list(whisper_labels),
                                   "source": "whisper"}))
    df = pd.concat(parts, ignore_index=True)
    df["text"] = df["text"].fillna("").astype(str).str.strip()
    df = df[df["text"] != ""]
    return df.drop_duplicates(subset=["text", "label_id"]).reset_index(drop=True)


def _linear_with_warmup(step, warmup, total):
    if step < warmup:
        return (step + 1) / max(1, warmup)
    return max(0.0, (total - step) / max(1, total - warmup))


def new_model():
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    from transformers.utils import logging as hf_logging

    hf_logging.set_verbosity_error()  # the new-head load report is expected; keep logs short
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    model = AutoModelForSequenceClassification.from_pretrained(
        BASE_MODEL, num_labels=config.NUM_LABELS,
        id2label=dict(enumerate(config.LABELS)), label2id=config.LABEL_TO_ID)
    return model, tok


@torch.inference_mode()
def predict_proba(model, tok, texts, batch_size=64, device="cpu", max_length=64):
    model.eval()
    texts = [t if isinstance(t, str) else "" for t in texts]
    out = np.zeros((len(texts), config.NUM_LABELS), dtype=np.float32)
    order = np.argsort([len(t) for t in texts])
    for b in range(0, len(order), batch_size):
        idx = order[b:b + batch_size]
        enc = tok([texts[i] for i in idx], truncation=True, max_length=max_length,
                  padding=True, return_tensors="pt").to(device)
        with torch.autocast(device_type="cuda", dtype=torch.float16,
                            enabled=str(device).startswith("cuda")):
            logits = model(**enc).logits
        out[idx] = torch.softmax(logits.float(), -1).cpu().numpy()
    return out


def train(train_df, dev_texts, dev_labels, seed=0, device="cpu", log=print, max_hours=None,
          **overrides):
    """Fine-tune one seed. Returns (model, tokenizer, history, best_dev_f1) with the best
    epoch's weights loaded."""
    from . import sound_model

    hp = {**DEFAULTS, **overrides}
    sound_model.set_seed(seed)
    model, tok = new_model()
    model.to(device)
    use_amp = hp["fp16"] and str(device).startswith("cuda")
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    labels = train_df["label_id"].to_numpy()
    weights = torch.tensor(data.class_weights(labels), dtype=torch.float32, device=device)
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    no_decay = ("bias", "LayerNorm.weight", "layer_norm.weight")
    groups = [
        {"params": [p for n, p in model.named_parameters() if not n.endswith(no_decay)],
         "weight_decay": hp["weight_decay"]},
        {"params": [p for n, p in model.named_parameters() if n.endswith(no_decay)],
         "weight_decay": 0.0},
    ]
    opt = torch.optim.AdamW(groups, lr=hp["lr"])
    steps_per_epoch = math.ceil(len(train_df) / hp["batch_size"])
    total = steps_per_epoch * hp["epochs"]
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: _linear_with_warmup(s, int(hp["warmup_ratio"] * total), total))
    rng = np.random.default_rng(seed)
    texts = train_df["text"].tolist()

    best_f1, best_state, history = -1.0, None, []
    t_start = time.time()
    for epoch in range(hp["epochs"]):
        model.train()
        perm = rng.permutation(len(texts))
        loss_sum = 0.0
        for b in range(0, len(perm), hp["batch_size"]):
            idx = perm[b:b + hp["batch_size"]]
            enc = tok([texts[i] for i in idx], truncation=True, max_length=hp["max_length"],
                      padding=True, return_tensors="pt").to(device)
            y = torch.from_numpy(labels[idx]).long().to(device)
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                loss = loss_fn(model(**enc).logits.float(), y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.unscale_(opt)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(opt)
            scaler.update()
            sched.step()
            loss_sum += loss.item() * len(idx)
        dev_probs = predict_proba(model, tok, dev_texts, device=device, max_length=hp["max_length"])
        f1 = metrics.weighted_f1(dev_labels, dev_probs.argmax(1))
        history.append({"epoch": epoch + 1, "train_loss": loss_sum / len(perm), "dev_wf1": f1})
        log(f"    epoch {epoch + 1}  loss {loss_sum / len(perm):.4f}  dev wF1 (Whisper) {f1:.2f}")
        if f1 > best_f1:
            best_f1 = f1
            best_state = {k: v.detach().to("cpu", copy=True) for k, v in model.state_dict().items()}
        if max_hours and (time.time() - t_start) / 3600 > max_hours:
            log("    stopping: time budget reached")
            break
    model.load_state_dict(best_state)
    return model.cpu().eval(), tok, history, best_f1


def benchmark(steps=20, device="cpu", batch_size=DEFAULTS["batch_size"], tokens=40, warmup=3):
    """Seconds per fp16 training step on a batch of `tokens`-long inputs, for S0."""
    model, _ = new_model()
    model.to(device).train()
    use_amp = str(device).startswith("cuda")
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    opt = torch.optim.AdamW(model.parameters(), lr=2e-5)
    ids = torch.randint(5, 1000, (batch_size, tokens), device=device)
    mask = torch.ones_like(ids)
    y = torch.zeros(batch_size, dtype=torch.long, device=device)
    for i in range(warmup + steps):
        if i == warmup:
            if use_amp:
                torch.cuda.synchronize()
            t0 = time.perf_counter()
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
            loss = nn.functional.cross_entropy(model(input_ids=ids, attention_mask=mask).logits.float(), y)
        opt.zero_grad(set_to_none=True)
        scaler.scale(loss).backward()
        scaler.step(opt)
        scaler.update()
    if use_amp:
        torch.cuda.synchronize()
    return (time.perf_counter() - t0) / steps


def save(model, tok, out_dir, meta):
    """fp16 safetensors plus the tokenizer and a meta file (§9.5)."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    model.half().save_pretrained(out_dir, safe_serialization=True)
    model.float()
    tok.save_pretrained(out_dir)
    (out_dir / "meta.json").write_text(json.dumps({"name": MODEL_NAME, **meta}, indent=2))


def load_cpu(model_dir, precision="int8"):
    """Load a saved model in fp32 on the CPU; with precision "int8", quantise its Linear
    layers to int8 (§8.3)."""
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    if precision not in ("int8", "fp32"):
        raise ValueError(f"text precision must be 'int8' or 'fp32', not {precision!r}")
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForSequenceClassification.from_pretrained(model_dir, dtype=torch.float32).eval()
    if precision == "int8":
        model = torch.ao.quantization.quantize_dynamic(model, {torch.nn.Linear}, dtype=torch.qint8)
    return model, tok


def load_cpu_int8(model_dir):
    return load_cpu(model_dir, "int8")


class TextClassifier:
    """One model, or the 3-seed ensemble (mean of the seeds' probabilities), on the CPU in
    the configured precision."""

    def __init__(self, model_dirs, max_length=64, precision=None):
        self.precision = precision or config.TEXT_PRECISION
        self.models = [load_cpu(d, self.precision) for d in model_dirs]
        self.max_length = max_length
        self.name = MODEL_NAME + ("" if len(model_dirs) == 1 else f" ensemble-{len(model_dirs)}")

    def predict_proba(self, texts):
        return np.mean([predict_proba(m, t, texts, max_length=self.max_length)
                        for m, t in self.models], axis=0)


def _ids(df, split):
    if "id" in df.columns:
        return df["id"].astype(str).tolist()
    return [f"{split}_dia{d}_utt{u}" for d, u in zip(df["dialogue_id"], df["utterance_id"])]


def main(argv=None):
    """One training run from the S3 transcript CSVs:
    python -m emotion_analyzer.text_model --transcripts DIR --window 10 --seed 0 --out DIR
    [--real-only]. Writes the fp16 model, history.json and pred_{dev,test}_{real,whisper}.npz."""
    import argparse

    from .sound_model import save_predictions

    ap = argparse.ArgumentParser(description="Fine-tune one RoBERTa text model")
    ap.add_argument("--transcripts", required=True, help="folder with {split}_{W}s.csv")
    ap.add_argument("--window", type=int, default=config.WINDOW_S)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--real-only", action="store_true", help="ablation T")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--epochs", type=int, default=DEFAULTS["epochs"])
    ap.add_argument("--limit", type=int, default=None, help="tiny smoke runs")
    ap.add_argument("--no-save-model", action="store_true")
    ap.add_argument("--max-hours", type=float, default=None)
    args = ap.parse_args(argv)

    tdir, w = Path(args.transcripts), args.window
    read = lambda split: pd.read_csv(tdir / f"{split}_{w}s.csv", keep_default_na=False)
    tr, dv, te = read("train"), read("dev"), read("test")
    if args.limit:
        tr, dv, te = tr.head(args.limit), dv.head(args.limit), te.head(args.limit)
    lab = lambda df: df["label"].map(config.LABEL_TO_ID).to_numpy()
    train_df = build_training_set(tr["reference"], lab(tr),
                                  None if args.real_only else tr["hypothesis"],
                                  None if args.real_only else lab(tr))
    run = "T" if args.real_only else "main"
    print(f"[text {run} seed {args.seed}] {len(train_df)} training examples", flush=True)
    model, tok, history, best = train(train_df, dv["hypothesis"].tolist(), lab(dv), seed=args.seed,
                                      device=args.device, epochs=args.epochs,
                                      max_hours=args.max_hours, log=lambda m: print(m, flush=True))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "history.json").write_text(json.dumps(history, indent=2))
    model.to(args.device)
    for split, df in (("dev", dv), ("test", te)):
        for kind, col in (("real", "reference"), ("whisper", "hypothesis")):
            probs = predict_proba(model, tok, df[col].tolist(), device=args.device)
            save_predictions(out / f"pred_{split}_{kind}.npz", _ids(df, split), lab(df), probs)
    model.cpu()
    if not args.no_save_model:
        save(model, tok, out / "model", {"seed": args.seed, "run": run, "window_s": w,
                                         "dev_wf1_whisper": best, "train_examples": len(train_df)})
    print(f"[text {run} seed {args.seed}] best dev wF1 (Whisper) {best:.2f}", flush=True)


if __name__ == "__main__":
    main()
