"""Repository rules. The full AC-13 scan is added in Phase 10."""

from emotion_analyzer import config

REQUIRED_IGNORES = [
    "data/", "models/", "certs/", ".env", ".venv/", "kaggle/code/", "__pycache__/", "logs/",
]


def test_label_order_is_fixed_and_alphabetical():
    assert config.LABELS == ["anger", "disgust", "fear", "joy", "neutral", "sadness", "surprise"]
    assert config.LABELS == sorted(config.LABELS)
    assert config.LABEL_TO_ID["neutral"] == 4


def test_gitignore_has_required_entries():
    lines = (config.ROOT / ".gitignore").read_text(encoding="utf-8").split()
    for entry in REQUIRED_IGNORES:
        assert entry in lines, entry


def test_fusion_grid_and_thresholds():
    assert config.FUSION_WEIGHT_GRID[0] == 0.0 and config.FUSION_WEIGHT_GRID[-1] == 1.0
    assert len(config.FUSION_WEIGHT_GRID) == 21
    assert config.DISAGREEMENT_MIN_CONF == 0.40
    assert config.SEEDS == (0, 1, 2)
