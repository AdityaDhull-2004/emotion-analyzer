"""SpeechPipeline (spec §5.1, §5.2, §6.1): decoding, VAD segmentation, the shared Whisper
encode, the transcript from the encoder output, valid frames and per-stage timing.

One faster-whisper pass serves both branches: the encoder output feeds the greedy
decoder (the transcript) and, trimmed to its valid frames, the sound model.
"""

import math
import time
from contextlib import contextmanager

import numpy as np

from . import config


class AudioError(ValueError):
    """An input the API rejects. `status` is the HTTP code from §5.3."""

    def __init__(self, status, error, detail):
        super().__init__(f"{error}: {detail}")
        self.status = status
        self.error = error
        self.detail = detail


class Timer:
    """Accumulates wall-clock milliseconds per stage."""

    def __init__(self):
        self.ms = {}

    @contextmanager
    def stage(self, name):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] = self.ms.get(name, 0.0) + 1000.0 * (time.perf_counter() - t0)


def decode(source):
    """Decode a path or file object to mono float32 at 16 kHz (§5.1). 400 if undecodable."""
    from faster_whisper import decode_audio

    try:
        audio = decode_audio(source, sampling_rate=config.SAMPLE_RATE)
    except Exception as e:
        raise AudioError(400, "Unsupported or undecodable audio", f"{type(e).__name__}: {e}") from e
    if audio.size == 0:
        raise AudioError(400, "Unsupported or undecodable audio", "the file contains no audio")
    return audio


def check_duration(audio):
    """Enforce 0.5–120 s (§5.1). 422 otherwise. Returns the duration in seconds."""
    duration = len(audio) / config.SAMPLE_RATE
    if duration < config.MIN_DURATION_S:
        raise AudioError(422, "Recording too short",
                         f"{duration:.2f} s; the minimum is {config.MIN_DURATION_S} s")
    if duration > config.MAX_DURATION_S:
        raise AudioError(422, "Recording too long",
                         f"{duration:.1f} s; the maximum is {config.MAX_DURATION_S:.0f} s")
    return duration


# --- Voice activity detection and segmentation (§5.2) ---------------------------------

def _vad_options():
    from faster_whisper.vad import VadOptions

    return VadOptions(threshold=0.5, min_speech_duration_ms=250, min_silence_duration_ms=300,
                      speech_pad_ms=200, max_speech_duration_s=config.SEGMENT_MAX_S)


def speech_spans(audio):
    """Silero VAD speech regions as (start_s, end_s) pairs; empty when there is no speech."""
    from faster_whisper.vad import get_speech_timestamps

    sr = config.SAMPLE_RATE
    return [(t["start"] / sr, t["end"] / sr)
            for t in get_speech_timestamps(audio, _vad_options(), sampling_rate=sr)]


def merge_spans(spans, total_s, min_s=config.SEGMENT_MIN_S, max_s=config.SEGMENT_MAX_S,
                max_gap_s=2.0):
    """Turn VAD speech regions into segments of min_s–max_s seconds.

    Regions longer than max_s are split into equal parts; neighbours closer than
    max_gap_s are merged while the result stays within max_s; a segment still
    shorter than min_s joins its nearer neighbour if that fits, otherwise it is
    widened to min_s with the surrounding audio.
    """
    pieces = []
    for s, e in spans:
        s, e = max(0.0, s), min(total_s, e)
        if e <= s:
            continue
        n = max(1, math.ceil((e - s) / max_s - 1e-9))
        step = (e - s) / n
        pieces += [(s + i * step, s + (i + 1) * step) for i in range(n)]

    merged = []
    for s, e in pieces:
        if merged and s - merged[-1][1] <= max_gap_s and e - merged[-1][0] <= max_s:
            merged[-1] = (merged[-1][0], e)
        else:
            merged.append((s, e))

    i = 0
    while i < len(merged):
        s, e = merged[i]
        if e - s >= min_s:
            i += 1
            continue
        candidates = []
        if i > 0 and e - merged[i - 1][0] <= max_s:
            candidates.append((s - merged[i - 1][1], i - 1))
        if i + 1 < len(merged) and merged[i + 1][1] - s <= max_s:
            candidates.append((merged[i + 1][0] - e, i + 1))
        if candidates:
            _, j = min(candidates)
            lo, hi = min(i, j), max(i, j)
            merged[lo:hi + 1] = [(merged[lo][0], merged[hi][1])]
            i = lo
            continue
        pad = (min_s - (e - s)) / 2
        s2, e2 = max(0.0, s - pad), min(total_s, e + pad)
        if e2 - s2 < min_s:
            s2, e2 = (0.0, min(total_s, min_s)) if s2 == 0.0 else (max(0.0, total_s - min_s), total_s)
        merged[i] = (s2, e2)
        i += 1
    return merged


def segment(audio):
    """Segments for one recording (§5.2) as (start_s, end_s) pairs.

    VAD runs on every clip. No speech gives an empty list. A clip of 10 s or less
    with speech is one segment, the whole clip; longer audio is split into the
    VAD's speech regions, merged or split to 1–10 s.
    """
    total_s = len(audio) / config.SAMPLE_RATE
    spans = speech_spans(audio)
    if not spans:
        return []
    if total_s <= config.SEGMENT_MAX_S:
        return [(0.0, total_s)]
    return merge_spans(spans, total_s)


def chunk_audio(audio, max_s, search_s=1.5):
    """Split audio into consecutive chunks of at most max_s seconds.

    Each cut aims at an equal share of what is left and moves to the quietest
    20 ms frame within search_s of that point, so cuts fall between words.
    """
    sr = config.SAMPLE_RATE
    max_n = int(max_s * sr)
    if len(audio) <= max_n:
        return [audio]
    hop = int(config.ENCODER_FRAME_S * sr)
    n_frames = len(audio) // hop
    energy = np.square(audio[:n_frames * hop].reshape(n_frames, hop)).mean(axis=1)
    chunks, start = [], 0
    while len(audio) - start > max_n:
        left = len(audio) - start
        target = start + left / math.ceil(left / max_n)
        lo = max(start + sr // 2, int(target - search_s * sr))
        hi = min(start + max_n, int(target + search_s * sr))
        f_lo, f_hi = lo // hop, max(lo // hop + 1, hi // hop)
        cut = min((int(np.argmin(energy[f_lo:f_hi])) + f_lo) * hop, start + max_n)
        if cut <= start:
            cut = start + max_n
        chunks.append(audio[start:cut])
        start = cut
    chunks.append(audio[start:])
    return chunks


def valid_frame_count(duration_s, window_s):
    """Encoder frames covering the audio: 1 frame = 20 ms, capped at the window (§6.1)."""
    return min(math.ceil(duration_s / config.ENCODER_FRAME_S - 1e-6),
               int(window_s / config.ENCODER_FRAME_S))


# --- The shared Whisper pass (§6.1) ----------------------------------------------------

class SpeechPipeline:
    """faster-whisper model plus the shared-encode helpers.

    `window_s` is 10 or 30. Sound features always come from chunks of at most 10 s
    (§8.2); transcripts come from chunks of at most the window (§8.1). For audio of
    10 s or less both are the same chunk, so one encode serves both.
    """

    def __init__(self, model_size=config.ASR_MODEL, device=config.ASR_DEVICE,
                 compute_type=config.ASR_COMPUTE_TYPE, window_s=config.WINDOW_S,
                 device_index=0, cpu_threads=0, batch_size=16):
        from faster_whisper import WhisperModel
        from faster_whisper.tokenizer import Tokenizer

        if window_s not in config.WINDOWS_S:
            raise ValueError(f"window_s must be one of {config.WINDOWS_S}")
        self.model_size = model_size
        self.device = device
        self.compute_type = compute_type
        self.window_s = window_s
        self.batch_size = batch_size
        self.model = WhisperModel(model_size, device=device, device_index=device_index,
                                  compute_type=compute_type, cpu_threads=cpu_threads)
        self.tokenizer = Tokenizer(self.model.hf_tokenizer, False, task="transcribe",
                                   language="en")
        self.prompt = list(self.tokenizer.sot_sequence) + [self.tokenizer.no_timestamps]

    @property
    def name(self):
        return f"faster-whisper {self.model_size} {self.compute_type}"

    def features(self, audio, window_s):
        from faster_whisper.audio import pad_or_trim

        feats = self.model.feature_extractor(audio)
        return np.ascontiguousarray(pad_or_trim(feats, window_s * config.MEL_FRAMES_PER_S))

    def encode(self, chunks, window_s):
        """Encode a batch of chunks (each at most window_s long). Returns the encoder
        output as a CPU StorageView of shape (B, window_s * 50, d_model)."""
        from faster_whisper.transcribe import get_ctranslate2_storage

        x = np.stack([self.features(c, window_s) for c in chunks])
        return self.model.model.encode(get_ctranslate2_storage(x), to_cpu=True)

    def decode_text(self, enc):
        """Greedy transcripts, without timestamps, from an encoder output batch."""
        n = enc.shape[0]
        results = self.model.model.generate(enc, [self.prompt] * n, beam_size=1,
                                            max_length=224)
        eot = self.tokenizer.eot
        return [self.tokenizer.decode([t for t in r.sequences_ids[0] if t < eot]).strip()
                for r in results]

    @staticmethod
    def to_numpy(enc):
        return np.asarray(enc)

    @staticmethod
    def frames_from(enc_np, durations_s, window_s):
        return [enc_np[i, :valid_frame_count(d, window_s)] for i, d in enumerate(durations_s)]

    def analyze_segment(self, audio, timer=None, window_s=None):
        """Frames (T x d_model, float32) and transcript for one segment, timing the
        stages 'encode' and 'transcribe'."""
        window_s = window_s or self.window_s
        timer = timer or Timer()
        sr = config.SAMPLE_RATE
        frame_chunks = chunk_audio(audio, config.SEGMENT_MAX_S)
        with timer.stage("encode"):
            enc = self.encode(frame_chunks, window_s)
            enc_np = self.to_numpy(enc).astype(np.float32)
            frames = np.concatenate(
                self.frames_from(enc_np, [len(c) / sr for c in frame_chunks], window_s))
        text_chunks = chunk_audio(audio, window_s)
        with timer.stage("transcribe"):
            if len(text_chunks) == len(frame_chunks):
                texts = self.decode_text(enc)
            else:
                texts = self.decode_text(self.encode(text_chunks, window_s))
        return frames, " ".join(t for t in texts if t), timer

    def transcribe_clips(self, audios, window_s=None):
        """Transcripts for many clips, batched; clips longer than the window are
        transcribed in chunks and the text joined (§8.1)."""
        window_s = window_s or self.window_s
        chunks, owner = [], []
        for i, a in enumerate(audios):
            for c in chunk_audio(a, window_s):
                chunks.append(c)
                owner.append(i)
        texts = [[] for _ in audios]
        for b in range(0, len(chunks), self.batch_size):
            batch = chunks[b:b + self.batch_size]
            for i, t in zip(owner[b:b + self.batch_size], self.decode_text(self.encode(batch, window_s))):
                if t:
                    texts[i].append(t)
        return [" ".join(t) for t in texts]

    def frames_clips(self, audios, window_s=None, dtype=np.float16):
        """Valid encoder frames for many clips, batched; clips over 10 s are encoded in
        chunks of at most 10 s and their frames concatenated (§8.2)."""
        window_s = window_s or self.window_s
        sr = config.SAMPLE_RATE
        chunks, owner = [], []
        for i, a in enumerate(audios):
            for c in chunk_audio(a, config.SEGMENT_MAX_S):
                chunks.append(c)
                owner.append(i)
        parts = [[] for _ in audios]
        for b in range(0, len(chunks), self.batch_size):
            batch = chunks[b:b + self.batch_size]
            enc_np = self.to_numpy(self.encode(batch, window_s))
            for i, f in zip(owner[b:b + self.batch_size],
                            self.frames_from(enc_np, [len(c) / sr for c in batch], window_s)):
                parts[i].append(f.astype(dtype))
        return [np.concatenate(p) for p in parts]


class HFWhisperPipeline(SpeechPipeline):
    """Fallback for Kaggle when CTranslate2 can't use the GPU (§9.2): the same weights
    through Hugging Face transformers (`openai/whisper-<size>`). Features come from
    faster-whisper's extractor, so the inputs match; the encoder is run layer by layer
    so that the 10 s window (500 positions) works too."""

    def __init__(self, model_size=config.ASR_MODEL, device="cuda", compute_type="float16",
                 window_s=config.WINDOW_S, batch_size=16, **_):
        import torch
        from faster_whisper.feature_extractor import FeatureExtractor
        from transformers import WhisperForConditionalGeneration, WhisperProcessor

        if window_s not in config.WINDOWS_S:
            raise ValueError(f"window_s must be one of {config.WINDOWS_S}")
        self.torch = torch
        self.model_size, self.device, self.window_s = model_size, device, window_s
        self.batch_size = batch_size
        self.dtype = torch.float16 if compute_type == "float16" and device.startswith("cuda") else torch.float32
        self.compute_type = "float16" if self.dtype == torch.float16 else "float32"
        name = f"openai/whisper-{model_size}"
        self.processor = WhisperProcessor.from_pretrained(name)
        self.hf = WhisperForConditionalGeneration.from_pretrained(name, dtype=self.dtype).to(device).eval()
        self.extractor = FeatureExtractor()

    @property
    def name(self):
        return f"transformers whisper-{self.model_size} {self.compute_type}"

    def features(self, audio, window_s):
        from faster_whisper.audio import pad_or_trim

        return np.ascontiguousarray(pad_or_trim(self.extractor(audio), window_s * config.MEL_FRAMES_PER_S))

    def encode(self, chunks, window_s):
        torch = self.torch
        enc = self.hf.model.encoder
        x = torch.from_numpy(np.stack([self.features(c, window_s) for c in chunks]))
        with torch.inference_mode():
            h = torch.nn.functional.gelu(enc.conv1(x.to(self.device, self.dtype)))
            h = torch.nn.functional.gelu(enc.conv2(h)).permute(0, 2, 1)
            h = h + enc.embed_positions.weight[:h.shape[1]]
            for layer in enc.layers:
                out = layer(h, attention_mask=None)
                h = out[0] if isinstance(out, tuple) else out
            return enc.layer_norm(h)

    @staticmethod
    def to_numpy(enc):
        return enc.float().cpu().numpy()

    def decode_text(self, enc):
        from transformers.modeling_outputs import BaseModelOutput

        with self.torch.inference_mode():
            ids = self.hf.generate(encoder_outputs=BaseModelOutput(last_hidden_state=enc),
                                   num_beams=1, do_sample=False, max_new_tokens=220)
        return [t.strip() for t in self.processor.batch_decode(ids, skip_special_tokens=True)]


def make_pipeline(backend="ct2", **kwargs):
    """`ct2` (faster-whisper, the default) or `hf` (the transformers fallback)."""
    return HFWhisperPipeline(**kwargs) if backend == "hf" else SpeechPipeline(**kwargs)
