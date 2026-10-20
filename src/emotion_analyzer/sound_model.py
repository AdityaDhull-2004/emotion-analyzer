"""Sound model `attnpool-v1` (spec §8.2): an attention-pooling head over frozen Whisper
encoder frames, its training loop and inference.

    LayerNorm(768) -> Linear(768, 256) -> GELU -> Dropout(0.2)
    -> attention pooling: scores = v . tanh(W h) over valid frames (masked softmax)
    -> Dropout(0.2) -> Linear(256, 7)
"""

import json
import math
import time
from pathlib import Path

import numpy as np
import torch
from torch import nn

from . import config, data, metrics

MODEL_NAME = "attnpool-v1"
DEFAULTS = {
    "d_in": 768, "d_hidden": 256, "dropout": 0.2, "lr": 1e-3, "weight_decay": 0.01,
    "batch_size": 64, "max_epochs": 40, "warmup_epochs": 1, "patience": 6,
    "frame_drop": 0.10, "min_crop_frames": 50, "crop_prob": 0.5,
}


class AttnPoolHead(nn.Module):
    def __init__(self, d_in=768, d_hidden=256, num_labels=config.NUM_LABELS, dropout=0.2):
        super().__init__()
        self.norm = nn.LayerNorm(d_in)
        self.proj = nn.Linear(d_in, d_hidden)
        self.act = nn.GELU()
        self.drop1 = nn.Dropout(dropout)
        self.att_w = nn.Linear(d_hidden, d_hidden)
        self.att_v = nn.Linear(d_hidden, 1, bias=False)
        self.drop2 = nn.Dropout(dropout)
        self.out = nn.Linear(d_hidden, num_labels)

    def forward(self, x, mask):
        """x: (B, T, d_in) frames; mask: (B, T) True for valid frames. Returns logits."""
        h = self.drop1(self.act(self.proj(self.norm(x))))
        scores = self.att_v(torch.tanh(self.att_w(h))).squeeze(-1)
        scores = scores.masked_fill(~mask, float("-inf"))
        attn = torch.softmax(scores, dim=1)
        pooled = torch.bmm(attn.unsqueeze(1), h).squeeze(1)
        return self.out(self.drop2(pooled))


def pad_batch(frames_list, device="cpu"):
    """Pad a list of (T_i, d) arrays to (B, T_max, d) with a validity mask."""
    lengths = [len(f) for f in frames_list]
    t_max, d = max(lengths), frames_list[0].shape[1]
    x = np.zeros((len(frames_list), t_max, d), dtype=np.float32)
    mask = np.zeros((len(frames_list), t_max), dtype=bool)
    for i, f in enumerate(frames_list):
        x[i, :len(f)] = f
        mask[i, :len(f)] = True
    return torch.from_numpy(x).to(device), torch.from_numpy(mask).to(device)


def augment(frames, rng, frame_drop=0.10, min_crop=50, crop_prob=0.5):
    """Random crop to at least min_crop frames (1 s), then drop about frame_drop of
    the frames (§8.2). Always keeps at least one frame."""
    t = len(frames)
    if t > min_crop and rng.random() < crop_prob:
        length = int(rng.integers(min_crop, t + 1))
        start = int(rng.integers(0, t - length + 1))
        frames = frames[start:start + length]
    keep = rng.random(len(frames)) >= frame_drop
    if not keep.any():
        keep[int(rng.integers(0, len(frames)))] = True
    return frames[keep]


def cosine_with_warmup(step, warmup_steps, total_steps):
    if step < warmup_steps:
        return (step + 1) / max(1, warmup_steps)
    progress = (step - warmup_steps) / max(1, total_steps - warmup_steps)
    return 0.5 * (1.0 + math.cos(math.pi * min(1.0, progress)))


def set_seed(seed):
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


@torch.inference_mode()
def predict_proba(model, frames_list, batch_size=128, device="cpu"):
    model.eval()
    out = []
    order = np.argsort([len(f) for f in frames_list])  # similar lengths pad less
    for b in range(0, len(order), batch_size):
        idx = order[b:b + batch_size]
        x, mask = pad_batch([frames_list[i] for i in idx], device)
        out.append((idx, torch.softmax(model(x, mask).float(), -1).cpu().numpy()))
    probs = np.zeros((len(frames_list), config.NUM_LABELS), dtype=np.float32)
    for idx, p in out:
        probs[idx] = p
    return probs


def train(train_frames, train_labels, dev_frames, dev_labels, seed=0, device="cpu",
          log=print, max_hours=None, **overrides):
    """Train one head. Returns (best_model, history, best_dev_f1). Early stopping on
    dev weighted-F1 with the configured patience; the best epoch's weights are kept."""
    hp = {**DEFAULTS, **overrides}
    set_seed(seed)
    rng = np.random.default_rng(seed)
    model = AttnPoolHead(hp["d_in"], hp["d_hidden"], config.NUM_LABELS, hp["dropout"]).to(device)
    weights = torch.tensor(data.class_weights(train_labels), dtype=torch.float32, device=device)
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    opt = torch.optim.AdamW(model.parameters(), lr=hp["lr"], weight_decay=hp["weight_decay"])
    steps_per_epoch = math.ceil(len(train_frames) / hp["batch_size"])
    total = steps_per_epoch * hp["max_epochs"]
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: cosine_with_warmup(s, steps_per_epoch * hp["warmup_epochs"], total))
    labels = np.asarray(train_labels)

    best_f1, best_state, history, stale = -1.0, None, [], 0
    t_start = time.time()
    for epoch in range(hp["max_epochs"]):
        model.train()
        perm = rng.permutation(len(train_frames))
        loss_sum = 0.0
        for b in range(0, len(perm), hp["batch_size"]):
            idx = perm[b:b + hp["batch_size"]]
            batch = [augment(np.asarray(train_frames[i], dtype=np.float32), rng, hp["frame_drop"],
                             hp["min_crop_frames"], hp["crop_prob"]) for i in idx]
            x, mask = pad_batch(batch, device)
            y = torch.from_numpy(labels[idx]).long().to(device)
            loss = loss_fn(model(x, mask), y)
            opt.zero_grad(set_to_none=True)
            loss.backward()
            opt.step()
            sched.step()
            loss_sum += loss.item() * len(idx)
        dev_probs = predict_proba(model, dev_frames, device=device)
        f1 = metrics.weighted_f1(dev_labels, dev_probs.argmax(1))
        history.append({"epoch": epoch + 1, "train_loss": loss_sum / len(perm), "dev_wf1": f1})
        log(f"    epoch {epoch + 1:2d}  loss {loss_sum / len(perm):.4f}  dev wF1 {f1:.2f}")
        if f1 > best_f1:
            best_f1, stale = f1, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            stale += 1
            if stale >= hp["patience"]:
                break
        if max_hours and (time.time() - t_start) / 3600 > max_hours:
            log("    stopping: time budget reached")
            break
    model.load_state_dict(best_state)
    return model.cpu().eval(), history, best_f1


def save(model, path, meta):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save(model.state_dict(), path)
    info = {"name": MODEL_NAME, "labels": config.LABELS, "d_in": model.norm.normalized_shape[0],
            "d_hidden": model.proj.out_features, **meta}
    path.with_suffix(".json").write_text(json.dumps(info, indent=2))


def load(path, device="cpu"):
    path = Path(path)
    info = json.loads(path.with_suffix(".json").read_text())
    model = AttnPoolHead(info["d_in"], info["d_hidden"], len(info["labels"]))
    model.load_state_dict(torch.load(path, map_location=device, weights_only=True))
    return model.eval(), info


def benchmark(steps=20, device="cpu", batch_size=64, frames=160, warmup=3):
    """Seconds per training step on random frames, for S0's time estimate."""
    rng = np.random.default_rng(0)
    model = AttnPoolHead().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
    batch = [rng.normal(size=(frames, 768)).astype(np.float16) for _ in range(batch_size)]
    y = torch.zeros(batch_size, dtype=torch.long, device=device)
    for i in range(warmup + steps):
        if i == warmup:
            if str(device).startswith("cuda"):
                torch.cuda.synchronize()
            t0 = time.perf_counter()
        x, mask = pad_batch([augment(np.asarray(f, dtype=np.float32), rng) for f in batch], device)
        loss = nn.functional.cross_entropy(model(x, mask), y)
        opt.zero_grad(set_to_none=True)
        loss.backward()
        opt.step()
    if str(device).startswith("cuda"):
        torch.cuda.synchronize()
    return (time.perf_counter() - t0) / steps


class SoundClassifier:
    """The deployed head: predict_proba(list of (T, 768) frame arrays) -> (n, 7)."""

    def __init__(self, path):
        self.model, self.info = load(path)
        self.name = self.info.get("name", "attnpool-v1")

    def predict_proba(self, frames_list):
        return predict_proba(self.model, frames_list)


def save_predictions(path, ids, labels, probs):
    np.savez_compressed(path, ids=np.asarray(ids, dtype=str), labels=np.asarray(labels),
                        probs=np.asarray(probs, dtype=np.float32))


def main(argv=None):
    """One training run: python -m emotion_analyzer.sound_model --train DIR [DIR ...]
    --dev DIR --test DIR --seed 0 --out DIR. Writes sound_head.pt/.json, history.json
    and pred_dev.npz / pred_test.npz (ids, labels, probs)."""
    import argparse

    from . import features

    ap = argparse.ArgumentParser(description="Train one attention-pooling sound head")
    ap.add_argument("--train", nargs="+", required=True, help="feature sets to train on")
    ap.add_argument("--dev", required=True)
    ap.add_argument("--test", default=None)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", required=True)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--window", type=int, default=config.WINDOW_S)
    ap.add_argument("--run-name", default="main")
    ap.add_argument("--max-epochs", type=int, default=DEFAULTS["max_epochs"])
    ap.add_argument("--max-hours", type=float, default=None)
    args = ap.parse_args(argv)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tr_frames, tr_labels = [], []
    for d in args.train:
        idx, fr = features.load(d)
        tr_frames += fr
        tr_labels += idx["label_id"].tolist()
    dv_idx, dv_frames = features.load(args.dev)
    print(f"[{args.run_name} seed {args.seed}] train {len(tr_frames)} clips, dev {len(dv_frames)}",
          flush=True)
    model, history, best = train(tr_frames, np.array(tr_labels), dv_frames,
                                 dv_idx["label_id"].to_numpy(), seed=args.seed, device=args.device,
                                 max_hours=args.max_hours, max_epochs=args.max_epochs,
                                 log=lambda m: print(m, flush=True))
    save(model, out / "sound_head.pt", {"seed": args.seed, "run": args.run_name,
                                        "window_s": args.window, "dev_wf1": best,
                                        "epochs_run": len(history)})
    (out / "history.json").write_text(json.dumps(history, indent=2))
    save_predictions(out / "pred_dev.npz", dv_idx["id"], dv_idx["label_id"],
                     predict_proba(model, dv_frames))
    if args.test:
        te_idx, te_frames = features.load(args.test)
        save_predictions(out / "pred_test.npz", te_idx["id"], te_idx["label_id"],
                         predict_proba(model, te_frames))
    print(f"[{args.run_name} seed {args.seed}] best dev wF1 {best:.2f}", flush=True)


if __name__ == "__main__":
    main()
