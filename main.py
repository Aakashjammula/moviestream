"""Movie streaming API.

Endpoints (all under the ``/api`` prefix when behind nginx):
    GET /health               liveness probe
    GET /api/movies           list indexed movies (media_type=movie)
    GET /api/movies/{id}      movie metadata
    GET /api/shows            list TV shows with poster + counts
    GET /api/shows/{id}       show detail with seasons and episodes
    GET /api/stream/{id}      stream the video file (Range requests supported)
    GET /api/poster/{id}      thumbnail (cached frame extraction)
    POST /api/rescan          re-scan files + enrich posters in background
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path

import bcrypt
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, Response
from pydantic import BaseModel

import database
import enrich

APP_PASSWORD_HASH = os.environ.get("APP_PASSWORD_HASH", "").strip()

SESSION_COOKIE = "msid"
SESSION_MAX_AGE = 30 * 24 * 3600

# Public paths (no session needed).
OPEN_PATHS = {"/", "/health", "/api/login", "/api/logout"}

# Login rate limit: max attempts per IP per window.
LOGIN_LIMIT = 10
LOGIN_WINDOW = 60
_login_attempts: dict[str, list[float]] = {}


class Movie(BaseModel):
    id: int
    title: str
    description: str = ""
    year: int | None = None
    genre: str = ""
    file_path: str
    media_type: str = "movie"
    season: int | None = None
    episode: int | None = None
    poster_url: str = ""
    language: str = ""
    quality: str = ""
    backdrop_url: str = ""
    subtitles: list[dict] = []


class Show(BaseModel):
    id: int
    name: str
    year: int | None = None
    poster_url: str = ""
    seasons: int = 0
    episode_count: int = 0
    overview: str = ""
    genres: str = ""
    has_subs: bool = False


class Episode(BaseModel):
    id: int
    title: str
    year: int | None = None
    season: int | None = None
    episode: int | None = None
    file_path: str
    poster_url: str = ""
    language: str = ""
    quality: str = ""
    subtitles: list[dict] = []


class ShowDetail(Show):
    episodes: list[Episode] = []


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db()
    # Drop orphaned remux temp files from interrupted builds.
    try:
        for tmp in REMUX_DIR.glob("*.tmp.mp4"):
                            tmp.unlink()
    except OSError:
        pass
    # With multiple workers, only one performs startup indexing —
    # the rest just serve. (fcntl lock, non-blocking.)
    try:
        import fcntl

        lock = open(database.DATABASE_PATH.parent / "startup.lock", "w")
        leader = True
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            leader = False
        if leader:
            database.scan_movies()
            enrich.enrich_background()
            enrich.pregen_thumbs_background()
    except ImportError:
        database.scan_movies()
        enrich.enrich_background()
        enrich.pregen_thumbs_background()
    yield


app = FastAPI(title="Movie API", lifespan=lifespan)



def _is_https(request: Request) -> bool:
    if request.url.scheme == "https":
        return True
    return request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if request.url.path in OPEN_PATHS:
        return await call_next(request)
    sid = request.cookies.get(SESSION_COOKIE, "")
    if not database.valid_session(sid):
        return Response(
            status_code=401,
            media_type="application/json",
            content='{"detail":"Login required"}',
        )
    return await call_next(request)


# The UI is served from another origin (Vercel), so allow exactly those origins, with
# credentials for the login cookie. Added after auth_gate so it is the OUTERMOST middleware:
# 401 responses and preflight OPTIONS requests must carry CORS headers too.
FRONTEND_ORIGINS = [
    o.strip().rstrip("/")
    for o in os.environ.get("FRONTEND_ORIGINS", "http://localhost:3000").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=FRONTEND_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
    max_age=600,
)


class LoginBody(BaseModel):
    password: str = ""


class SessionInfo(BaseModel):
    id: str
    created_at: int
    last_seen: int
    user_agent: str = ""
    ip: str = ""
    current: bool = False


@app.get("/api/sessions", response_model=list[SessionInfo])
async def list_sessions(request: Request) -> list[SessionInfo]:
    current = request.cookies.get(SESSION_COOKIE, "")
    return [
        SessionInfo(**s, current=(s["id"] == current))
        for s in database.list_sessions()
    ]


@app.delete("/api/sessions/{sid}")
async def revoke_session(sid: str) -> dict:
    database.delete_session(sid)
    return {"status": "ok"}


@app.post("/api/sessions/logout-others")
async def logout_others(request: Request) -> dict:
    current = request.cookies.get(SESSION_COOKIE, "")
    revoked = database.delete_other_sessions(current)
    return {"status": "ok", "revoked": revoked}


def _client_ip(request: Request) -> str:
    # Behind Cloudflare Tunnel the real visitor IP is in CF-Connecting-IP (set by Cloudflare,
    # can't be spoofed by the client). X-Forwarded-For's first entry is client-controlled.
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf
    return request.client.host if request.client else "?"


@app.post("/api/login")
async def login(body: LoginBody, request: Request):
    if not APP_PASSWORD_HASH:
        raise HTTPException(status_code=503, detail="Server login not configured")
    ip = _client_ip(request)
    now = time.time()
    hits = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_WINDOW]
    if len(hits) >= LOGIN_LIMIT:
        raise HTTPException(status_code=429, detail="Too many attempts, try later")
    hits.append(now)
    _login_attempts[ip] = hits
    try:
        ok = bcrypt.checkpw(body.password.encode(), APP_PASSWORD_HASH.encode())
    except Exception:
        ok = False
    if not ok:
        raise HTTPException(status_code=401, detail="Wrong password")
    _login_attempts.pop(ip, None)
    sid = database.create_session(
        user_agent=request.headers.get("user-agent", ""), ip=ip
    )
    resp = Response(
        status_code=200,
        media_type="application/json",
        content='{"status":"ok"}',
    )
    resp.set_cookie(
        SESSION_COOKIE,
        sid,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=_is_https(request),
        samesite="lax",
        path="/",
    )
    return resp


@app.post("/api/logout")
async def logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE, "")
    if sid:
        database.delete_session(sid)
    resp = Response(
        status_code=200, media_type="application/json", content='{"status":"ok"}'
    )
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.get("/api/me")
async def me() -> dict:
    return {"user": "me"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "tmdb": bool(enrich.TMDB_KEY)}


@app.get("/")
async def read_root() -> dict:
    return {"message": "MovieStream API. The UI is at the frontend address."}


MOVIE_COLS = (
    "id, title, description, year, genre, file_path, media_type, season, episode,"
    " poster_url, language, quality, backdrop_url, subtitles"
)


def _row_to_movie(r) -> Movie:
    d = dict(r)
    try:
        d["subtitles"] = json.loads(d.get("subtitles") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["subtitles"] = []
    return Movie(**d)


@app.get("/api/movies", response_model=list[Movie])
async def get_movies() -> list[Movie]:
    with database.get_db() as conn:
        rows = conn.execute(
            f"SELECT {MOVIE_COLS} FROM movies WHERE media_type = 'movie' ORDER BY title"
        ).fetchall()
    return [_row_to_movie(r) for r in rows]


@app.get("/api/movies/{movie_id}", response_model=Movie)
async def get_movie(movie_id: int) -> Movie:
    with database.get_db() as conn:
        row = conn.execute(
            f"SELECT {MOVIE_COLS} FROM movies WHERE id = ?", (movie_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    return _row_to_movie(row)


@app.get("/api/shows", response_model=list[Show])
async def get_shows() -> list[Show]:
    with database.get_db() as conn:
        rows = conn.execute(
            """SELECT s.id, s.name, s.year, s.poster_url, s.overview, s.genres,
                      COUNT(DISTINCT m.season) AS seasons,
                      COUNT(DISTINCT CASE WHEN m.episode IS NOT NULL THEN m.season || 'x' || m.episode END)
                        + COUNT(CASE WHEN m.episode IS NULL THEN 1 END) AS episode_count,
                      MAX(CASE WHEN m.subtitles IS NOT NULL AND m.subtitles <> '[]' THEN 1 ELSE 0 END) AS has_subs
               FROM shows s LEFT JOIN movies m ON m.show_id = s.id
               GROUP BY s.id ORDER BY s.name"""
        ).fetchall()
    return [Show(**dict(r)) for r in rows]


@app.get("/api/shows/{show_id}", response_model=ShowDetail)
async def get_show(show_id: int) -> ShowDetail:
    with database.get_db() as conn:
        show = conn.execute("SELECT * FROM shows WHERE id = ?", (show_id,)).fetchone()
        if show is None:
            raise HTTPException(status_code=404, detail="Show not found")
        eps = conn.execute(
            """SELECT id, title, year, season, episode, file_path, poster_url,
                      language, quality, subtitles
               FROM movies WHERE show_id = ?
               ORDER BY season, episode, title""",
            (show_id,),
        ).fetchall()
        seasons = {e["season"] for e in eps if e["season"] is not None}
    data = dict(show)
    data["seasons"] = len(seasons)
    # Dedupe: same (season, episode) from multiple rips -> keep best quality only,
    # so episode numbers display 1..N instead of repeating. Rows with no parsed
    # episode number are kept as-is.
    quality_rank = {"4K": 4, "1080p": 3, "720p": 2, "480p": 1, "SD": 0}
    best: dict = {}
    for e in eps:
        ep = e["episode"]
        if ep is None:
            best[("row", e["id"])] = e
        else:
            key = (e["season"], ep)
            cur = best.get(key)
            if cur is None or quality_rank.get(e["quality"] or "", -1) > quality_rank.get(cur["quality"] or "", -1):
                best[key] = e
    deduped = sorted(
        best.values(),
        key=lambda e: (
            e["season"] or 0,
            e["episode"] if e["episode"] is not None else 9999,
            e["title"],
        ),
    )
    data["episodes"] = [_row_to_episode(e) for e in deduped]
    data["episode_count"] = len(deduped)
    return ShowDetail(**data)


def _row_to_episode(e) -> Episode:
    d = dict(e)
    try:
        d["subtitles"] = json.loads(d.get("subtitles") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["subtitles"] = []
    return Episode(**d)


VIDEO_TYPES = {
    ".mp4": "video/mp4",
    ".m4v": "video/x-m4v",
    ".webm": "video/webm",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
}


def _media_type(path: Path) -> str:
    return VIDEO_TYPES.get(path.suffix.lower(), "video/mp4")


REMUX_DIR = Path(os.environ.get("REMUX_DIR", "/app/data/remux"))
REMUX_DIR.mkdir(parents=True, exist_ok=True)

# Containers Firefox (pre-145 / pref-off builds) can't play in <video>.
NEEDS_REMUX = {".mkv"}


def _remux_paths(movie_id: int) -> tuple[Path, Path]:
    return REMUX_DIR / f"{movie_id}.mp4", REMUX_DIR / f"{movie_id}.json"


def _remux_fresh(src: Path, dst: Path, meta: Path) -> bool:
    """True when the cached mp4 matches the current source file."""
    if not dst.is_file() or not meta.is_file():
        return False
    try:
        st = src.stat()
        info = json.loads(meta.read_text())
        return (
            info.get("size") == st.st_size
            and info.get("mtime") == st.st_mtime
            and dst.stat().st_size > 0
        )
    except (OSError, ValueError):
        return False


def _build_remux(src: Path, dst: Path, meta: Path) -> None:
    """Copy video+audio streams into an MP4 (faststart). No re-encode."""
    import subprocess

    import imageio_ffmpeg

    tmp = dst.with_suffix(".tmp.mp4")
    proc = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-hide_banner", "-y",
            "-i", str(src),
            "-map", "0:v:0", "-map", "0:a",
            "-c", "copy", "-sn",
            "-movflags", "+faststart",
            str(tmp),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=600,
        text=True,
    )
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise RuntimeError((proc.stderr or "")[-500:] or "ffmpeg remux failed")
    st = src.stat()
    meta.write_text(json.dumps({"size": st.st_size, "mtime": st.st_mtime}))
    os.replace(tmp, dst)


def _lookup_media(movie_id: int) -> Path:
    with database.get_db() as conn:
        row = conn.execute(
            "SELECT title, file_path FROM movies WHERE id = ?", (movie_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    path = Path(row["file_path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="File no longer on disk")
    return path


def _ensure_remux(path: Path, movie_id: int) -> None:
    """Build the cached MP4 if stale, serialized across workers via file lock."""
    import fcntl

    dst, meta = _remux_paths(movie_id)
    with open(REMUX_DIR / f"{movie_id}.lock", "w") as lf:
        fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
        try:
            # Re-check inside the lock: a concurrent request may have built it.
            if _remux_fresh(path, dst, meta):
                return
            log = logging.getLogger("uvicorn.error")
            log.info("remuxing %s for Firefox-compatible playback", path.name)
            _build_remux(path, dst, meta)
        finally:
            fcntl.flock(lf.fileno(), fcntl.LOCK_UN)


@app.get("/api/remux/{movie_id}/status")
async def remux_status(movie_id: int) -> dict:
    path = _lookup_media(movie_id)
    if path.suffix.lower() not in NEEDS_REMUX:
        return {"cached": True, "needed": False}
    dst, meta = _remux_paths(movie_id)
    return {"cached": _remux_fresh(path, dst, meta), "needed": True}


@app.get("/api/remux/{movie_id}")
async def remux_movie(movie_id: int, request: Request):
    """Firefox-compatible MP4 version of a file, remuxed once then cached."""
    import asyncio

    path = _lookup_media(movie_id)
    if path.suffix.lower() not in NEEDS_REMUX:
        raise HTTPException(status_code=400, detail="Remux not needed for this file")
    dst, meta = _remux_paths(movie_id)
    try:
        await asyncio.to_thread(_ensure_remux, path, movie_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Remux failed: {exc}")
    if request.headers.get("x-via-nginx") == "1":
        return Response(
            status_code=200,
            media_type="video/mp4",
            headers={
                "X-Accel-Redirect": f"/_cache/{movie_id}.mp4",
                "Content-Type": "video/mp4",
                "Accept-Ranges": "bytes",
            },
        )
    return FileResponse(str(dst), media_type="video/mp4", filename=dst.name)


@app.get("/api/stream/{movie_id}")
async def stream_movie(movie_id: int, request: Request):
    with database.get_db() as conn:
        row = conn.execute(
            "SELECT title, file_path FROM movies WHERE id = ?", (movie_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    path = Path(row["file_path"])
    if not path.is_file():
        raise HTTPException(status_code=410, detail="File no longer on disk")
    media_type = _media_type(path)
    if request.headers.get("x-via-nginx") == "1":
        # Hand off to nginx: zero-copy sendfile + native Range seeks.
        # The /_media/ location is internal-only (see nginx conf).
        try:
            rel = path.relative_to(database.MOVIE_DIR)
        except ValueError:
            raise HTTPException(status_code=404, detail="File outside library")
        return Response(
            status_code=200,
            media_type=media_type,
            headers={
                "X-Accel-Redirect": "/_media/" + urllib.parse.quote(str(rel)),
                "Content-Type": media_type,
                "Accept-Ranges": "bytes",
            },
        )
    # Direct backend access (dev / container-IP): serve from Python.
    # Starlette's FileResponse handles Range requests.
    return FileResponse(str(path), media_type=media_type, filename=path.name)


def _srt_to_vtt(text: str) -> str:
    """Minimal SRT -> WebVTT conversion."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", text.strip())
    out = ["WEBVTT", ""]
    for block in blocks:
        lines = block.split("\n")
        # drop numeric counter /ssa headers
        lines = [ln for ln in lines if not re.fullmatch(r"\d+", ln.strip())]
        if not lines:
            continue
        lines[0] = lines[0].replace(",", ".")
        out.extend(lines + [""])
    return "\n".join(out)


@app.get("/api/subs/{movie_id}")
async def list_subs(movie_id: int) -> list[dict]:
    with database.get_db() as conn:
        row = conn.execute(
            "SELECT subtitles FROM movies WHERE id = ?", (movie_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    try:
        subs = json.loads(row["subtitles"] or "[]")
    except (json.JSONDecodeError, TypeError):
        subs = []
    return [{"index": i, "lang": s.get("lang", f"Track {i + 1}")} for i, s in enumerate(subs)]


@app.get("/api/subs/{movie_id}/{index}")
async def get_sub(movie_id: int, index: int):
    with database.get_db() as conn:
        row = conn.execute(
            "SELECT subtitles FROM movies WHERE id = ?", (movie_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    try:
        subs = json.loads(row["subtitles"] or "[]")
        entry = subs[index]
    except (json.JSONDecodeError, TypeError, IndexError, KeyError):
        raise HTTPException(status_code=404, detail="Subtitle not found")
    sub_path = database.MOVIE_DIR / entry["file"]
    if not sub_path.is_file():
        raise HTTPException(status_code=410, detail="Subtitle file missing")
    text = sub_path.read_text(encoding="utf-8", errors="replace")
    if sub_path.suffix.lower() == ".srt":
        text = _srt_to_vtt(text)
    return PlainTextResponse(text, media_type="text/vtt; charset=utf-8")


@app.post("/api/rescan")
async def rescan() -> dict:
    count = database.scan_movies()
    enrich.enrich_background()
    enrich.pregen_thumbs_background()
    return {"status": "ok", "indexed": count}


@app.post("/api/subs/fetch")
async def fetch_subs() -> dict:
    return {"status": "ok", **enrich.fetch_missing_subs(),
            **enrich.extract_embedded_subs(limit=10)}


def _poster_path(movie_id: int) -> Path:
    database.POSTER_DIR.mkdir(parents=True, exist_ok=True)
    return database.POSTER_DIR / f"{movie_id}.jpg"


@app.get("/api/poster/{movie_id}")
async def get_poster(movie_id: int):
    """Serve a cached thumbnail. Never blocks: missing thumbs are queued
    for background generation and this returns 404 (UI shows a letter tile
    and the next rescan/page load picks the finished poster up)."""
    cached = _poster_path(movie_id)
    if cached.is_file():
        return FileResponse(
            str(cached),
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=86400"},
        )
    with database.get_db() as conn:
        row = conn.execute(
            "SELECT file_path FROM movies WHERE id = ?", (movie_id,)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Movie not found")
    if Path(row["file_path"]).is_file():
        enrich.queue_thumb(movie_id, row["file_path"])
    raise HTTPException(status_code=404, detail="Poster not ready yet")
