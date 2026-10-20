"""FastAPI app (spec §5.3, §12): loads the deployed models and assembles the Results tab's
report once at start-up, serves the web UI from app/static/ and the analysis API. It serves
no audio and nothing from data/: /static/ returns only the page's HTML, CSS and JavaScript.

    uvicorn app.main:app --host 0.0.0.0 --port 8443 --ssl-keyfile certs/key.pem \
        --ssl-certfile certs/cert.pem --workers 1

One worker, and one analysis at a time: the work is CPU-bound and memory is limited (§4.1).
Every request gets one line in the git-ignored logs/server.log (§12).
"""

import io
import json
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from emotion_analyzer import config, fusion, speech

from app.report import build_report

STATIC_DIR = Path(__file__).resolve().parent / "static"
PAGE_SUFFIXES = {".html", ".js", ".css"}


def error(status, err, detail):
    """The §5.3 error shape."""
    return JSONResponse({"error": err, "detail": detail}, status_code=status)


class PageFiles(StaticFiles):
    """app/static/ limited to the page's own HTML, CSS and JavaScript (§5.3, v1.6), so an
    audio file, or anything else that lands in the folder, can't be fetched."""

    async def get_response(self, path, scope):
        if Path(path).suffix.lower() not in PAGE_SUFFIXES:
            raise HTTPException(status_code=404)
        return await super().get_response(path, scope)


class AccessLog:
    """One JSON line per request (§12): time, client IP, user agent, endpoint, status and
    processing time, plus Cloudflare's CF-Connecting-IP when the request came through the
    tunnel. (For tunnel requests uvicorn already takes the client IP from cloudflared's
    X-Forwarded-For, which it trusts from localhost.) The deployment check reads it."""

    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def write(self, request, status, ms):
        line = {"time": datetime.now().astimezone().isoformat(timespec="seconds"),
                "ip": request.client.host if request.client else None,
                "endpoint": f"{request.method} {request.url.path}", "status": status, "ms": round(ms),
                "ua": request.headers.get("user-agent", "")}
        if cf := request.headers.get("cf-connecting-ip"):
            line["cf_ip"] = cf
        with self.lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")


def create_app(load_analyzer=fusion.load_analyzer, load_report=build_report,
               access_log=config.LOGS_DIR / "server.log"):
    """`load_analyzer` builds the object that turns audio into the §5.3 response, and
    `load_report` the Results tab's aggregates; the tests pass stand-ins so the HTTP
    layer can be checked without model weights, and their own `access_log` path."""

    @asynccontextmanager
    async def lifespan(app):
        app.state.report = load_report()
        app.state.analyzer = load_analyzer()
        yield

    app = FastAPI(title="Emotion Analyzer", version=config.VERSION, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    lock = threading.Lock()
    log = AccessLog(access_log)

    @app.middleware("http")
    async def access(request, call_next):
        t0 = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            log.write(request, status, 1000 * (time.perf_counter() - t0))

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

    app.mount("/static", PageFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()
