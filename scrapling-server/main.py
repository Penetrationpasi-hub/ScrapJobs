"""Single-instance, bounded worker. No live scraping unless explicitly source-approved."""
import hashlib
import hmac
import json
import os
import multiprocessing
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from crawler import crawl
from safe_http import RUN_SECONDS
from sources import registry, ISOLATED_SOURCES, approved_sources

app = FastAPI(title="Scrapling worker", docs_url=None, redoc_url=None, openapi_url=None)
lock = threading.Lock()
pool = ThreadPoolExecutor(max_workers=1)
searches = {}
TTL = 3600


@app.middleware("http")
async def boundary(request: Request, call_next):
    if request.url.path != "/health":
        try:
            auth(request.headers.get("authorization", ""))
        except HTTPException as error:
            return JSONResponse({"detail": error.detail}, status_code=error.status_code)
        if request.method == "POST":
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 4096:
                    return JSONResponse({"detail": "Anfrage zu groß."}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
    return await call_next(request)


def auth(authorization: str = Header(default="")):
    expected = os.environ.get("SCRAPLING_API_TOKEN", "")
    if not expected or os.environ.get("SCRAPLING_ENABLED") != "1":
        raise HTTPException(503, "Scrapling ist abgeschaltet oder nicht eingerichtet.")
    if not hmac.compare_digest(authorization.encode(), ("Bearer " + expected).encode()):
        raise HTTPException(401, "Ungültige Dienstanmeldung.")


class Search(BaseModel):
    model_config = ConfigDict(extra="forbid")
    q: str = Field(min_length=3, max_length=80)
    location: str = Field(default="", max_length=80)
    radius_km: int = Field(default=25, ge=1, le=200)
    sources: list[str] = Field(min_length=1, max_length=4)
    id: str = Field(pattern=r"^[a-f0-9]{64}$")

    @field_validator("sources")
    @classmethod
    def validate_sources(cls, values):
        if any(value in ISOLATED_SOURCES for value in values) and len(values) != 1:
            raise ValueError("Boards with a 10 s crawl delay require their own group")
        if len(set(values)) != len(values) or any(value not in registry() for value in values):
            raise ValueError("Unsupported source")
        return values


@app.get("/health")
def health():
    return {"ok": True, "browser": False, "service": "naechster-schritt-scrapling", "protocol": 1}


@app.get("/sources", dependencies=[Depends(auth)])
def sources():
    configured = registry()
    approved = approved_sources(configured)
    return {"sources": [{"key": row.key, "label": row.label, "approved": row.key in approved,
                         "available": row.available, "note": row.note,
                         "url": row.reference or row.start("", "")}
                        for row in configured.values()], "maxSourcesPerRun": 4}


def execute(payload, output):
    try:
        output.put(crawl(Search(**payload)))
    except Exception:
        output.put({"status": "error", "error": "worker_error"})


def finish(req):
    # A process boundary enforces the deadline even when DNS or a system call hangs.
    context = multiprocessing.get_context("spawn")
    output = context.Queue()
    process = context.Process(target=execute, args=(req.model_dump(), output), daemon=True)
    process.start()
    try:
        result = output.get(timeout=RUN_SECONDS)
    except queue.Empty:
        result = {"status": "error", "error": "timeout"}
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        output.close()
    with lock:
        if req.id in searches:
            searches[req.id].update(result)


@app.post("/search", dependencies=[Depends(auth)])
def start(req: Search):
    fingerprint = hashlib.sha256(json.dumps(req.model_dump(), sort_keys=True).encode()).hexdigest()
    with lock:
        now = time.time()
        for key in list(searches):
            if now - searches[key]["started"] > TTL and searches[key]["status"] != "running":
                del searches[key]
        if req.id in searches:
            if searches[req.id]["fingerprint"] != fingerprint:
                raise HTTPException(409, "Anfrage-ID mit anderen Suchparametern.")
            return {"id": req.id}
        if len(searches) >= 200 or any(row["status"] == "running" for row in searches.values()):
            raise HTTPException(429, "Es läuft bereits eine Scrapling-Suche.")
        searches[req.id] = {"status": "running", "started": now, "fingerprint": fingerprint}
        pool.submit(finish, req)
    return {"id": req.id}


@app.get("/search/{search_id}", dependencies=[Depends(auth)])
def status(search_id: str):
    with lock:
        row = searches.get(search_id)
        if not row or time.time() - row["started"] > TTL:
            raise HTTPException(404, "Suche verloren oder abgelaufen; kein automatischer Neustart.")
        if row["status"] == "running" and time.time() - row["started"] > RUN_SECONDS + 5:
            return {"status": "error", "error": "timeout"}
        return {k: v for k, v in row.items() if k not in ("started", "fingerprint")}
