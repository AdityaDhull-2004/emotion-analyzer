"""Labels, paths, the window, thresholds and seeds, all in one place (spec §6.2).

Paths default to the repository layout (§13). On Kaggle the code is read-only under
/kaggle/input, so EA_ROOT points the writable paths somewhere else.
"""

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
OWN_DIR = DATA_DIR / "own"
KAGGLE_OUT_DIR = DATA_DIR / "kaggle"
MODELS_DIR = ROOT / "models"
RESULTS_DIR = ROOT / "results"
LOGS_DIR = ROOT / "logs"
SAMPLES_DIR = ROOT / "app" / "static" / "samples"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
DEMO_OK_FILE = OWN_DIR / "demo_ok.txt"

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
# The window rule (§8.1) has three cases, settled in Phase 3 and recorded in
# models/decision.json; WINDOW_S is the value used until that file exists.
WINDOW_S = 10
WINDOW_CASE = None
WER_RULE_MAX_GAP = 2.0
LATENCY_TARGET_S = 2.0  # AC-08
MEMORY_TARGET_GB = 2.5  # AC-09

# Fusion and output rules (§5.3, §8.4, §17)
DISAGREEMENT_MIN_CONF = 0.40
OVERALL_RULE = "duration_weighted"
FUSION_WEIGHT_GRID = [round(0.05 * i, 2) for i in range(21)]
ENSEMBLE_MIN_GAIN = 1.0  # text-only weighted-F1 points on dev Whisper transcripts (§8.3)

# Training and evaluation
SEEDS = (0, 1, 2)
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 0
ECE_BINS = 15
