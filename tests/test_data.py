"""Data loaders (spec §7, AC-01). Tests that need the local MELD dev copy skip when it
is absent; the full audio check over every clip is marked slow."""

import numpy as np
import pytest
import soundfile as sf

from emotion_analyzer import config, data

MELD_DEV = config.MELD_DIR / "dev" / "dev.csv"
needs_meld_dev = pytest.mark.skipif(not MELD_DEV.exists(), reason="MELD dev not downloaded")


def _touch_wav(path, seconds=0.5, sr=16000):
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), np.zeros(int(seconds * sr), dtype=np.float32), sr)
    return path


@needs_meld_dev
def test_meld_dev_join_count():
    df, dropped = data.meld_manifest("dev", check_audio=False)
    assert len(df) == data.MELD_EXPECTED_PAIRS["dev"] == 1108
    keys = set(zip(df["dialogue_id"], df["utterance_id"]))
    assert (110, 7) not in keys
    assert {"path": "dev/dia110_utt7.flac", "reason": "audio absent (known defect)"} in dropped
    assert set(df["label"]) <= set(config.LABELS)
    assert (df["label_id"] == df["label"].map(config.LABEL_TO_ID)).all()


@needs_meld_dev
def test_meld_dev_class_counts_match_paper_minus_missing_clip():
    df, _ = data.meld_manifest("dev", check_audio=False)
    paper = {"anger": 153, "disgust": 22, "fear": 40, "joy": 163, "neutral": 470,
             "sadness": 111, "surprise": 150}
    table = data.class_table(df)
    missing_label = data.read_meld_csv(MELD_DEV).query(
        "Dialogue_ID == 110 and Utterance_ID == 7")["Emotion"].item()
    paper[missing_label] -= 1
    assert table.to_dict() == paper


@needs_meld_dev
@pytest.mark.slow
def test_meld_dev_audio_readable():
    df, dropped = data.meld_manifest("dev", check_audio=True)
    assert (df["duration_s"] >= data.MIN_CLIP_S).all()
    assert len(df) + len([d for d in dropped if "absent" not in d["reason"]]) == 1108


def test_meld_count_assertion(tmp_path):
    split = tmp_path / "dev"
    split.mkdir()
    header = ("Sr No.,Utterance,Speaker,Emotion,Sentiment,Dialogue_ID,Utterance_ID,"
              "Season,Episode,StartTime,EndTime\n")
    (split / "dev.csv").write_text(
        header + "1,Hi.,Joey,joy,positive,0,0,1,1,00:00:01,00:00:02\n", encoding="utf-8")
    _touch_wav(split / "dia0_utt0.flac")
    with pytest.raises(AssertionError, match="expected 1108"):
        data.meld_manifest("dev", root=tmp_path)
    df, _ = data.meld_manifest("dev", root=tmp_path, check_counts=False)
    assert len(df) == 1 and df.loc[0, "label"] == "joy"


def test_text_repair_leaves_labels_alone(tmp_path):
    split = tmp_path / "dev"
    split.mkdir()
    header = ("Sr No.,Utterance,Speaker,Emotion,Sentiment,Dialogue_ID,Utterance_ID,"
              "Season,Episode,StartTime,EndTime\n")
    (split / "dev.csv").write_text(
        header + "1,  I donâ€™t know.  ,Ross,sadness,negative,3,4,1,1,00:00:01,00:00:02\n",
        encoding="utf-8")
    _touch_wav(split / "dia3_utt4.flac")
    df, _ = data.meld_manifest("dev", root=tmp_path, check_counts=False)
    assert df.loc[0, "text"] in ("I don't know.", "I don’t know.")
    assert df.loc[0, "label"] == "sadness"


def test_short_and_unreadable_clips_are_dropped(tmp_path):
    split = tmp_path / "dev"
    split.mkdir()
    header = ("Sr No.,Utterance,Speaker,Emotion,Sentiment,Dialogue_ID,Utterance_ID,"
              "Season,Episode,StartTime,EndTime\n")
    rows = "".join(f"{i},x,A,neutral,neutral,{i},0,1,1,0,1\n" for i in range(3))
    (split / "dev.csv").write_text(header + rows, encoding="utf-8")
    _touch_wav(split / "dia0_utt0.flac", seconds=1.0)
    _touch_wav(split / "dia1_utt0.flac", seconds=0.05)
    (split / "dia2_utt0.flac").write_bytes(b"not audio")
    df, dropped = data.meld_manifest("dev", root=tmp_path, check_counts=False)
    assert list(df["dialogue_id"]) == [0]
    assert sorted(d["reason"] for d in dropped) == ["shorter than 0.1 s", "unreadable"]


def test_cremad_label_map(tmp_path):
    for emo in ["ANG", "DIS", "FEA", "HAP", "NEU", "SAD"]:
        _touch_wav(tmp_path / "AudioWAV" / f"1001_DFA_{emo}_XX.wav")
    _touch_wav(tmp_path / "AudioWAV" / "readme.wav")
    df, _ = data.cremad_manifest(tmp_path)
    assert sorted(df["label"]) == ["anger", "disgust", "fear", "joy", "neutral", "sadness"]
    assert (df["speaker"] == "cremad_1001").all()


def test_ravdess_label_map_and_dedup(tmp_path):
    expected = {"01": "neutral", "02": "neutral", "03": "joy", "04": "sadness",
                "05": "anger", "06": "fear", "07": "disgust", "08": "surprise"}
    for tree in ["Actor_01", "audio_speech_actors_01-24/Actor_01"]:
        for ee in expected:
            _touch_wav(tmp_path / tree / f"03-01-{ee}-01-01-01-01.wav")
    _touch_wav(tmp_path / "Actor_01" / "03-02-01-01-01-01-01.wav")  # song, not speech
    df, _ = data.ravdess_manifest(tmp_path)
    assert len(df) == 8
    got = {p.name.split("-")[2]: label for p, label in zip(df["path"], df["label"])}
    assert got == expected


def test_own_recordings_and_demo_list(tmp_path):
    for name in ["anger_01.wav", "joy_02.m4a", "Surprise_03.webm", "notes.txt", "calm_01.wav"]:
        (tmp_path / name).write_bytes(b"x")
    df, skipped = data.own_manifest(tmp_path)
    assert sorted(df["label"]) == ["anger", "joy", "surprise"]
    assert sorted(skipped) == ["calm_01.wav", "notes.txt"]

    demo = tmp_path / "demo_ok.txt"
    demo.write_text("anger_01.wav\n# friend said no\n\njoy_02.m4a  # mine\n", encoding="utf-8")
    assert data.read_demo_ok(demo) == ["anger_01.wav", "joy_02.m4a"]
    demo.write_text("missing_09.wav\n", encoding="utf-8")
    with pytest.raises(ValueError):
        data.read_demo_ok(demo)


def test_class_weights():
    labels = np.array([0] * 80 + [1] * 20)
    w = data.class_weights(labels, num_labels=2)
    assert w.mean() == pytest.approx(1.0)
    assert w[1] / w[0] == pytest.approx(2.0)
