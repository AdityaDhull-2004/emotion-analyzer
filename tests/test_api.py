"""API tests (spec §5.3, AC-11): normal clip, silence, long recording (segmented),
unsupported format, too large, too short; and the read-only report behind the Results tab
(aggregates only, missing files), the offline page (§5.4), and that no audio can be fetched
(AC-13, v1.6).

Speech comes from the committed text-to-speech fixtures; silence, too-short, too-large and
unsupported inputs are built here. The fast tests run the real HTTP layer, decoding, limits,
VAD and segmentation with stand-in models; the slow ones load the deployed models from
models/ (skipped when they aren't there, as in a fresh clone)."""

import io
import json
import re

import numpy as np
import pytest
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import report
from app.main import STATIC_DIR, PageFiles, create_app
from emotion_analyzer import config, fusion

SHORT = config.FIXTURES_DIR / "speech_short.wav"
LONG = config.FIXTURES_DIR / "speech_long.wav"
ERROR_KEYS = {"error", "detail"}


class _FakeSpeech:
    name, window_s = "fake-asr", 30

    def analyze_segment(self, audio, timer, window_s=None):
        with timer.stage("encode"):
            frames = np.zeros((max(1, len(audio) // 320), 768), dtype=np.float32)
        with timer.stage("transcribe"):
            text = "I can't believe you did that!"
        return frames, text, timer


class _Fixed:
    def __init__(self, label, conf):
        self.p = np.full(config.NUM_LABELS, (1 - conf) / (config.NUM_LABELS - 1))
        self.p[config.LABEL_TO_ID[label]] = conf
        self.name = "fixed"

    def predict_proba(self, items):
        return np.stack([self.p] * len(items))


def _fake_analyzer():
    return fusion.Analyzer(_FakeSpeech(), _Fixed("anger", 0.6), _Fixed("surprise", 0.55),
                           {"t_sound": 1.0, "t_text": 1.0, "w_sound": 0.6})


@pytest.fixture(scope="module")
def access_log(tmp_path_factory):
    return tmp_path_factory.mktemp("logs") / "server.log"


@pytest.fixture(scope="module")
def client(access_log):
    with TestClient(create_app(_fake_analyzer, access_log=access_log)) as c:
        yield c


def _wav(seconds, value=0.0):
    buf = io.BytesIO()
    sf.write(buf, np.full(int(seconds * config.SAMPLE_RATE), value, dtype=np.float32),
             config.SAMPLE_RATE, format="WAV")
    return buf.getvalue()


def _post(client, name, data):
    return client.post("/api/analyze", files={"audio": (name, data)})


def _check_response(body, n_segments):
    assert body["speech_detected"] is True
    assert len(body["segments"]) == n_segments
    for seg in body["segments"]:
        assert set(seg) == {"start_s", "end_s", "transcript", "sound", "text", "fused", "disagreement"}
        for key in ("sound", "text", "fused"):
            assert list(seg[key]["probs"]) == config.LABELS
            assert abs(sum(seg[key]["probs"].values()) - 1) < 0.01
        assert 1.0 - 1e-6 <= seg["end_s"] - seg["start_s"] <= config.SEGMENT_MAX_S + 1e-6
    assert list(body["overall"]["probs"]) == config.LABELS
    assert set(body["timing_ms"]) == {"decode", "encode", "transcribe", "sound", "text", "fusion", "total"}
    assert set(body["models"]) == {"asr", "window_s", "sound", "text", "fusion_w_sound"}


def test_health_and_ui(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "models_loaded": True, "version": config.VERSION}
    page = client.get("/")
    assert page.status_code == 200 and "Emotion Analyzer" in page.text
    assert client.get("/static/app.js").status_code == 200


def test_normal_clip(client):
    r = _post(client, "speech_short.wav", SHORT.read_bytes())
    assert r.status_code == 200
    body = r.json()
    _check_response(body, 1)
    seg = body["segments"][0]
    assert seg["start_s"] == 0.0 and seg["end_s"] == pytest.approx(body["duration_s"], abs=0.01)
    assert seg["disagreement"] is True  # anger 0.6 against surprise 0.55, both >= 0.40


def test_silence(client):
    r = _post(client, "silence.wav", _wav(3.0))
    assert r.status_code == 200
    body = r.json()
    assert body["speech_detected"] is False and body["segments"] == [] and body["overall"] is None


def test_long_recording_is_segmented(client):
    r = _post(client, "speech_long.wav", LONG.read_bytes())
    assert r.status_code == 200
    body = r.json()
    assert body["duration_s"] > 20
    _check_response(body, 3)
    starts = [s["start_s"] for s in body["segments"]]
    assert starts == sorted(starts)


def test_unsupported_format(client):
    r = _post(client, "notes.txt", b"this is not audio at all")
    assert r.status_code == 400 and set(r.json()) == ERROR_KEYS
    r = _post(client, "broken.wav", b"RIFF\x00\x00\x00\x00WAVEgarbage")
    assert r.status_code == 400 and set(r.json()) == ERROR_KEYS
    r = client.post("/api/analyze", files={"wrong_field": ("a.wav", SHORT.read_bytes())})
    assert r.status_code == 400 and set(r.json()) == ERROR_KEYS


def test_too_large(client):
    r = _post(client, "big.wav", b"\x00" * (config.MAX_UPLOAD_BYTES + 1))
    assert r.status_code == 413 and set(r.json()) == ERROR_KEYS


def test_too_short_and_too_long(client):
    r = _post(client, "short.wav", _wav(0.3, 0.1))
    assert r.status_code == 422 and set(r.json()) == ERROR_KEYS
    r = _post(client, "long.wav", _wav(121.0))
    assert r.status_code == 422 and "long" in r.json()["error"].lower()


# --- The Results tab's report (§5.3 GET /api/report, §5.4) ----------------------------------

PER_UTTERANCE = re.compile(r"dia\d+_utt\d+|\b(?:anger|disgust|fear|joy|neutral|sadness|surprise)_\d+\b|"
                           r"\.(?:wav|m4a|mp3|flac|webm|ogg|opus|aac|mp4)\b", re.IGNORECASE)
PER_UTTERANCE_KEYS = {"id", "ids", "file", "files", "transcript", "transcripts", "text_whisper", "utterance"}


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _aggregates_only(report):
    assert not PER_UTTERANCE.search(json.dumps(report, ensure_ascii=False))
    assert not PER_UTTERANCE_KEYS & set(_keys(report))


def test_report_endpoint(client):
    r = client.get("/api/report")
    assert r.status_code == 200
    rep = r.json()
    assert rep["labels"] == config.LABELS and rep["version"] == config.VERSION
    assert set(rep["sections"]) == set(report.SECTIONS)
    for name, section in rep["sections"].items():
        assert section["available"], f"{name}: {section.get('reason')}"
    rows = [row["row"] for row in rep["sections"]["results_table"]["rows"]]
    assert rows == [f"R{i}" for i in range(10)]
    pc = rep["sections"]["per_class"]
    assert set(pc["branches"]) == {"sound", "text", "fused"}
    for b in pc["branches"].values():
        assert list(b["per_class"]) == config.LABELS
        assert np.array(b["confusion"]).shape == (config.NUM_LABELS, config.NUM_LABELS)
        assert np.array(b["confusion"]).sum() == pc["n"]
    assert {r["window_s"] for r in rep["sections"]["wer"]["rows"]} == set(config.WINDOWS_S)
    assert rep["sections"]["latency"]["stages_ms"]["total"]["median"] > 0
    chat = rep["sections"]["chatbot"]
    assert chat["partial"] == (chat["n_answered"] < chat["n_total"])
    assert rep["deployed"]["available"] and 0 <= rep["deployed"]["w_sound"] <= 1
    _aggregates_only(rep)
    assert client.post("/api/report").status_code == 405  # read-only


def test_report_missing_and_broken_files(tmp_path):
    rep = report.build_report(tmp_path, tmp_path / "fusion.json")
    assert not rep["deployed"]["available"]
    assert all(not s["available"] and "missing" in s["reason"] for s in rep["sections"].values())
    (tmp_path / "wer.json").write_text("{not json", encoding="utf-8")
    (tmp_path / "chatbot.json").write_text('{"model": "x"}', encoding="utf-8")  # well-formed, but no aggregates
    rep = report.build_report(tmp_path, tmp_path / "fusion.json")
    assert not rep["sections"]["wer"]["available"] and not rep["sections"]["chatbot"]["available"]
    with TestClient(create_app(_fake_analyzer, lambda: report.build_report(tmp_path, tmp_path / "f.json"),
                               access_log=tmp_path / "server.log")) as c:
        r = c.get("/api/report")
        assert r.status_code == 200 and not r.json()["sections"]["results_table"]["available"]


def test_report_drops_per_utterance_fields(tmp_path):
    """Only whitelisted aggregate fields reach the page, whatever else a results file holds."""
    src = json.loads((config.RESULTS_DIR / "results_table.json").read_text(encoding="utf-8"))
    src["ids"] = ["test_dia0_utt0"]
    src["rows"][0]["transcripts"] = ["oh my god"]
    (tmp_path / "results_table.json").write_text(json.dumps(src), encoding="utf-8")
    own = json.loads((config.RESULTS_DIR / "own_recordings.json").read_text(encoding="utf-8"))
    own["files"] = ["anger_01.m4a"]
    (tmp_path / "own_recordings.json").write_text(json.dumps(own), encoding="utf-8")
    rep = report.build_report(tmp_path)
    assert rep["sections"]["results_table"]["available"] and rep["sections"]["own_recordings"]["available"]
    _aggregates_only(rep)


def test_page_is_offline(client):
    """No CDNs or other external resources (§5.4): only the SVG namespace may look like a URL."""
    for name in ("index.html", "app.js", "style.css"):
        text = (STATIC_DIR / name).read_text(encoding="utf-8")
        assert set(re.findall(r"https?://[^\s\"'`)]+", text)) <= {"http://www.w3.org/2000/svg"}, name
        assert "@import" not in text and "//cdn" not in text
    page = client.get("/").text
    local = [u for u in re.findall(r'(?:src|href)="([^"]+)"', page) if not u.startswith("data:")]  # inline icon
    assert local == ["/static/style.css", "/static/app.js"]
    for tab in ("tab-try", "tab-how", "tab-results"):
        assert f'id="{tab}"' in page
    assert 'id="pipeline"' in page
    for name in ("app.js", "style.css"):
        assert client.get(f"/static/{name}").status_code == 200


# --- No audio served (§5.3, AC-13, v1.6) ----------------------------------------------------

def test_no_audio_can_be_fetched(client):
    """The page's three files are all app/static/ holds, the routes are the §5.3 ones, and the
    old demo-clip paths, data/own/ and path tricks into it all give 404, never audio."""
    assert sorted(p.name for p in STATIC_DIR.rglob("*") if p.is_file()) == ["app.js", "index.html", "style.css"]
    assert sorted(getattr(r, "path", "") for r in client.app.routes) == [
        "/", "/api/analyze", "/api/health", "/api/report", "/static"]
    for path in ["/static/samples/index.json", "/static/samples/anger_01.m4a", "/samples/anger_01.m4a",
                 "/data/own/anger_01.m4a", "/static/../data/own/anger_01.m4a",
                 "/static/%2e%2e/%2e%2e/data/own/anger_01.m4a", "/static/..%2f..%2fdata%2fown%2fanger_01.m4a",
                 "/static/../../tests/fixtures/speech_short.wav"]:
        r = client.get(path)
        assert r.status_code == 404, path
        assert not r.headers.get("content-type", "").startswith("audio/"), path


def test_static_serves_only_page_files(tmp_path):
    """Even if an audio file landed in app/static/, /static/ wouldn't serve it."""
    (tmp_path / "style.css").write_text("body {}", encoding="utf-8")
    (tmp_path / "clip.wav").write_bytes(SHORT.read_bytes())
    (tmp_path / "clip.m4a").write_bytes(b"m4a")
    (tmp_path / "index.json").write_text("[]", encoding="utf-8")
    app = FastAPI()
    app.mount("/static", PageFiles(directory=tmp_path), name="static")
    c = TestClient(app)
    assert c.get("/static/style.css").status_code == 200
    for name in ("clip.wav", "clip.m4a", "CLIP.WAV", "index.json", ""):
        assert c.get(f"/static/{name}").status_code == 404, name


# --- The access log (§12) ------------------------------------------------------------------

def test_access_log(client, access_log):
    """One JSON line per request, with Cloudflare's client address when the tunnel sends one."""
    client.get("/api/health", headers={"user-agent": "PhoneBrowser/1.0"})
    _post(client, "notes.txt", b"not audio")
    client.get("/api/health", headers={"user-agent": "TunnelPhone/2.0", "cf-connecting-ip": "203.0.113.7"})
    lines = [json.loads(line) for line in access_log.read_text(encoding="utf-8").splitlines()][-3:]
    for line in lines:
        assert set(line) >= {"time", "ip", "endpoint", "status", "ms", "ua"}
        assert line["ms"] >= 0 and line["time"][:4].isdigit()
    assert lines[0]["endpoint"] == "GET /api/health" and lines[0]["status"] == 200
    assert lines[0]["ua"] == "PhoneBrowser/1.0" and "cf_ip" not in lines[0]
    assert lines[1]["endpoint"] == "POST /api/analyze" and lines[1]["status"] == 400
    assert lines[2]["cf_ip"] == "203.0.113.7"


# --- The deployed models ------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_client(tmp_path_factory):
    if fusion.missing_models():
        pytest.skip("the deployed models aren't in models/ (Phase 6 copies them from the Kaggle outputs)")
    with TestClient(create_app(access_log=tmp_path_factory.mktemp("logs") / "server.log")) as c:
        yield c


@pytest.mark.slow
def test_real_models_normal_and_long(real_client):
    r = _post(real_client, "speech_short.wav", SHORT.read_bytes())
    assert r.status_code == 200
    body = r.json()
    _check_response(body, 1)
    assert "believe" in body["segments"][0]["transcript"].lower()
    assert body["models"]["asr"] == "faster-whisper small.en int8"
    assert body["models"]["window_s"] == config.WINDOW_S
    r = _post(real_client, "speech_long.wav", LONG.read_bytes())
    assert r.status_code == 200
    _check_response(r.json(), 3)
    r = _post(real_client, "silence.wav", _wav(3.0))
    assert r.json()["speech_detected"] is False
