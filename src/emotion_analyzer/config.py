"""Labels, paths, the window, thresholds and seeds, all in one place (spec §6.2).

Paths default to the repository layout (§13). On Kaggle the code is read-only under
/kaggle/input, so EA_ROOT points the writable paths somewhere else.
"""

import json
import os
from pathlib import Path

VERSION = "1.0.0"

# MELD's label strings in alphabetical order; this order is used everywhere (§5.3).
LABELS = ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]
LABEL_TO_ID = {label: i for i, label in enumerate(LABELS)}
NUM_LABELS = len(LABELS)

# Paths (§13)
ROOT = Path(os.environ.get("EA_ROOT", Path(__file__).resolve().parents[2]))
DATA_DIR = ROOT / "data"
MELD_DIR = DATA_DIR / "meld"
MELD_META_DIR = MELD_DIR / "meta"  # MELD's train/dev/test CSVs, no audio (§7.4)
MELD_MIRROR = "ajyy/MELD_audio"
OWN_DIR = DATA_DIR / "own"
KAGGLE_OUT_DIR = DATA_DIR / "kaggle"
MODELS_DIR = ROOT / "models"
RESULTS_DIR = ROOT / "results"
LOGS_DIR = ROOT / "logs"
FIXTURES_DIR = ROOT / "tests" / "fixtures"

# Audio input limits (§5.1) and segmentation (§5.2)
SAMPLE_RATE = 16000
MIN_DURATION_S = 0.5
MAX_DURATION_S = 120.0
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
SEGMENT_MIN_S = 1.0
SEGMENT_MAX_S = 10.0
AUDIO_EXTENSIONS = (".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".webm")

# Speech-to-text and the shared Whisper pass (§6.1, §8.1)
ASR_MODEL = "small.en"
ASR_DEVICE = "cpu"
ASR_COMPUTE_TYPE = "int8"
MEL_FRAMES_PER_S = 100
ENCODER_FRAME_S = 0.02
WINDOWS_S = (10, 30)
# The window rule (§8.1). Phase 3 timed small.en end to end on mains power: median
# 0.56 s (10 s window) and 1.71 s (30 s window), both within AC-08, so this is case
# "a": S4 chooses the window by WER on MELD dev. The preliminary 300-clip WER gap
# (10 s minus 30 s) was +2.87 points, so the preliminary choice is 30 s. S4's
# decision in models/decision.json overrides WINDOW_S once it exists.
WINDOW_CASE = "a"


def _decided_window(default=30):
    try:
        return int(json.loads((MODELS_DIR / "decision.json").read_text())["window_s"])
    except (OSError, ValueError, KeyError):
        return default


WINDOW_S = _decided_window()
WER_RULE_MAX_GAP = 2.0
LATENCY_TARGET_S = 2.0  # AC-08
MEMORY_TARGET_GB = 2.5  # AC-09

# Fusion and output rules (§5.3, §8.4, §17)
DISAGREEMENT_MIN_CONF = 0.40
OVERALL_RULE = "duration_weighted"
FUSION_WEIGHT_GRID = [round(0.05 * i, 2) for i in range(21)]
ENSEMBLE_MIN_GAIN = 1.0  # text-only weighted-F1 points on dev Whisper transcripts (§8.3)
# The fusion weight is chosen on the dev clips of speakers outside the main cast, MELD's
# closest stand-in for new voices; the temperatures use all of dev (§8.4, v1.4).
MAIN_CAST = ("Chandler", "Joey", "Monica", "Phoebe", "Rachel", "Ross")

# Deployed models (§8.2-§8.4), copied into models/ from the Kaggle outputs in Phase 6.
SOUND_HEAD_PATH = MODELS_DIR / "sound_head.pt"
FUSION_PATH = MODELS_DIR / "fusion.json"
# The text-ensemble rule (§8.3), applied at the start of Phase 6 on the Kaggle dev
# Whisper-transcript predictions: the 3-seed ensemble scored 51.03 weighted-F1 against
# 50.30 for the best single seed (seed 0), a gain of +0.73, short of ENSEMBLE_MIN_GAIN.
# So the deployed text model is seed 0 alone, and the ensemble latency check is not run.
TEXT_SEEDS_DEPLOYED = (0,)
# The text model runs on the CPU in int8 (dynamic quantisation) or fp32 (§8.3). Phase 6
# chose fp32: int8 cost 1.3 points of dev weighted-F1, flattened the probabilities and
# made each sentence's output depend on the batch it was scored in, while fp32 matched
# Kaggle on 99.9% of dev labels and still met AC-08 and AC-09 on mains power (median
# 1.71 s per 5 s clip and 1.40 GB peak, against 1.57 s and 1.90 GB in int8).
TEXT_PRECISION = "fp32"


def text_model_dirs(seeds=None):
    return [MODELS_DIR / f"text_model_seed{s}"
            for s in (TEXT_SEEDS_DEPLOYED if seeds is None else seeds)]

# Training and evaluation
SEEDS = (0, 1, 2)
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 0
ECE_BINS = 15
