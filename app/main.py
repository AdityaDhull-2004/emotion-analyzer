"""FastAPI app (spec §5.3, §12): loads the deployed models and assembles the Results tab's
report once at start-up, serves the web UI from app/static/ and the analysis API.

    uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile certs/key.pem \
        --ssl-certfile certs/cert.pem --workers 1

One worker, and one analysis at a time: the work is CPU-bound and memory is limited (§4.1).
"""

import io
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from emotion_analyzer import config, fusion, speech

from app.report import build_report

STATIC_DIR = Path(__file__).resolve().parent / "static"


def error(status, err, detail):
    """The §5.3 error shape."""
    return JSONResponse({"error": err, "detail": detail}, status_code=status)


def create_app(load_analyzer=fusion.load_analyzer, load_report=build_report):
    """`load_analyzer` builds the object that turns audio into the §5.3 response, and
    `load_report` the Results tab's aggregates; the tests pass stand-ins so the HTTP
    layer can be checked without model weights."""

    @asynccontextmanager
    async def lifespan(app):
        app.state.report = load_report()
        app.state.analyzer = load_analyzer()
        yield

    app = FastAPI(title="Emotion Analyzer", version=config.VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()

    @app.exception_handler(RequestValidationError)
    async def bad_request(request, exc):
        return error(400, "Bad request", "Send one audio file in the multipart form field 'audio'.")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "models_loaded": getattr(app.state, "analyzer", None) is not None,
                "version": config.VERSION}

    @app.get("/api/report")
    def report():
        """Read-only: the aggregates from results/ assembled at start-up (§5.3, §5.4)."""
        return app.state.report

    @app.post("/api/analyze")
    def analyze(request: Request, audio: UploadFile = File(...)):
        limit = config.MAX_UPLOAD_BYTES
        too_large = error(413, "File too large", f"The limit is {limit // 2**20} MB.")
        if int(request.headers.get("content-length") or 0) > limit + 2**20:  # multipart overhead
            return too_large
        suffix = Path(audio.filename or "").suffix.lower()
        if suffix and suffix not in config.AUDIO_EXTENSIONS:
            return error(400, "Unsupported format",
                         f"'{suffix}' isn't supported. Use WAV, FLAC, MP3, M4A/AAC, OGG/Opus or WebM.")
        data = audio.file.read(limit + 1)
        if len(data) > limit:
            return too_large
        if not data:
            return error(400, "Unsupported or undecodable audio", "The file is empty.")
        try:
            with lock:  # one analysis at a time on the CPU
                return app.state.analyzer.analyze(io.BytesIO(data))
        except speech.AudioError as e:
            return error(e.status, e.error, e.detail)

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
