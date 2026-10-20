"""Speech pipeline (spec §5.1, §5.2, §6.1). VAD uses the Silero model bundled with
faster-whisper, so those tests stay fast; tests that load Whisper are marked slow."""

import io

import numpy as np
import pytest

from emotion_analyzer import config, speech

SR = config.SAMPLE_RATE
SHORT = config.FIXTURES_DIR / "speech_short.wav"
LONG = config.FIXTURES_DIR / "speech_long.wav"


@pytest.fixture(scope="module")
def short_audio():
    return speech.decode(str(SHORT))


@pytest.fixture(scope="module")
def long_audio():
    return speech.decode(str(LONG))


@pytest.fixture(scope="module")
def pipeline():
    return speech.SpeechPipeline(window_s=10)


def test_fixtures_are_small():
    assert SHORT.stat().st_size + LONG.stat().st_size < 1_000_000


def test_decode_fixture(short_audio):
    assert short_audio.dtype == np.float32
    assert 4.0 < len(short_audio) / SR < 6.0


def test_decode_rejects_garbage():
    with pytest.raises(speech.AudioError) as e:
        speech.decode(io.BytesIO(b"this is not audio at all" * 50))
    assert e.value.status == 400


def test_duration_limits():
    with pytest.raises(speech.AudioError) as e:
        speech.check_duration(np.zeros(int(0.3 * SR), dtype=np.float32))
    assert e.value.status == 422
    with pytest.raises(speech.AudioError) as e:
        speech.check_duration(np.zeros(121 * SR, dtype=np.float32))
    assert e.value.status == 422
    assert speech.check_duration(np.zeros(5 * SR, dtype=np.float32)) == pytest.approx(5.0)


def _within_limits(segs):
    return all(config.SEGMENT_MIN_S - 1e-9 <= e - s <= config.SEGMENT_MAX_S + 1e-9 for s, e in segs)


def test_merge_spans_splits_long_regions():
    segs = speech.merge_spans([(0.0, 25.0)], total_s=30.0)
    assert len(segs) == 3 and _within_limits(segs)
    assert segs[0][0] == 0.0 and segs[-1][1] == 25.0


def test_merge_spans_merges_close_neighbours_up_to_10_s():
    segs = speech.merge_spans([(0, 3), (3.5, 6), (6.5, 9), (9.5, 12)], total_s=12.0)
    assert segs == [(0, 9), (9.5, 12)]


def test_merge_spans_fixes_short_segments():
    # A short region next to a neighbour joins it.
    assert speech.merge_spans([(0, 4), (6, 6.4)], total_s=20) == [(0, 6.4)]
    # An isolated short region far from others, with no room to join, is widened to 1 s.
    segs = speech.merge_spans([(0, 9.8), (15, 15.3), (25, 34)], total_s=40)
    assert _within_limits(segs) and len(segs) == 3
    assert segs[1][0] <= 15 and segs[1][1] >= 15.3


def test_segment_rules(short_audio, long_audio):
    assert speech.segment(np.zeros(3 * SR, dtype=np.float32)) == []
    assert speech.segment(short_audio) == [(0.0, len(short_audio) / SR)]
    segs = speech.segment(long_audio)
    assert len(segs) >= 2 and _within_limits(segs)
    assert all(a[1] <= b[0] for a, b in zip(segs, segs[1:]))


def test_chunk_audio(long_audio):
    chunks = speech.chunk_audio(long_audio, 10)
    assert len(chunks) == 3
    assert all(len(c) <= 10 * SR for c in chunks)
    assert np.array_equal(np.concatenate(chunks), long_audio)
    assert len(speech.chunk_audio(long_audio, 30)) == 1


def test_valid_frame_count():
    assert speech.valid_frame_count(10.0, 10) == 500
    assert speech.valid_frame_count(4.965, 10) == 249
    assert speech.valid_frame_count(4.82, 30) == 241
    assert speech.valid_frame_count(35.0, 30) == 1500


@pytest.mark.slow
def test_encoder_shape_10s_window(pipeline):
    enc = np.asarray(pipeline.encode([np.zeros(10 * SR, dtype=np.float32)], 10))
    assert enc.shape == (1, 500, 768)


@pytest.mark.slow
@pytest.mark.parametrize("window_s", [10, 30])
def test_analyze_segment(pipeline, short_audio, window_s):
    frames, text, timer = pipeline.analyze_segment(short_audio, window_s=window_s)
    assert frames.shape == (249, 768)
    assert "believe" in text.lower() and "surprise" in text.lower()
    assert set(timer.ms) == {"encode", "transcribe"}


@pytest.mark.slow
def test_long_clip_chunked_transcript_and_frames(pipeline, long_audio):
    text = pipeline.transcribe_clips([long_audio], 10)[0].lower()
    assert "because you are all here" in text
    frames = pipeline.frames_clips([long_audio], 10)[0]
    expected = sum(speech.valid_frame_count(len(c) / SR, 10)
                   for c in speech.chunk_audio(long_audio, 10))
    assert frames.shape == (expected, 768) and frames.dtype == np.float16
