"""Poster enrichment from public metadata APIs (stdlib only, runs in a thread).

- TV shows: TVMaze (https://api.tvmaze.com) — free, NO API key needed.
- Movies: TMDB (https://api.themoviedb.org/3) — needs a free API key in the
  TMDB_API_KEY env var. Get one at https://www.themoviedb.org/settings/api.
  Without a key, movies keep locally extracted frame thumbnails.
"""

from __future__ import annotations

import http.cookiejar
import json
import logging
import os
import re
import subprocess
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import database

log = logging.getLogger("enrich")

TMDB_KEY = os.environ.get("TMDB_API_KEY", "").strip()
OS_KEY = os.environ.get("OPENSUBTITLES_API_KEY", "").strip()
OS_USER = os.environ.get("OPENSUBTITLES_USER", "").strip()
OS_PASS = os.environ.get("OPENSUBTITLES_PASS", "").strip()
TVMAZE_SEARCH = "https://api.tvmaze.com/search/shows?q="
TMDB_SEARCH = "https://api.themoviedb.org/3/search/movie"
TMDB_TV_SEARCH = "https://api.themoviedb.org/3/search/tv"
TMDB_GENRES = "https://api.themoviedb.org/3/genre/movie/list"
TMDB_IMG = "https://image.tmdb.org/t/p/w342"
TMDB_BACKDROP = "https://image.tmdb.org/t/p/w1280"
OS_API = "https://api.opensubtitles.com/api/v1"

_genre_map: dict[int, str] | None = None


def _tmdb_genres() -> dict[int, str]:
    global _genre_map
    if _genre_map is None:
        _genre_map = {}
        if TMDB_KEY:
            data = _get_json(TMDB_GENRES + f"?api_key={TMDB_KEY}")
            if isinstance(data, dict):
                _genre_map = {g["id"]: g["name"] for g in data.get("genres", [])}
    return _genre_map

_running = False


def _get_json(url: str, timeout: int = 15) -> object | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "MovieStream/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception as exc:
        log.warning("request failed %s: %s", url.split("?")[0], exc)
        return None


def _tvmaze_poster(show_name: str) -> str:
    data = _get_json(TVMAZE_SEARCH + urllib.parse.quote(show_name))
    if not data:
        return ""
    try:
        show = data[0]["show"]
        img = show.get("image") or {}
        return img.get("original") or img.get("medium") or ""
    except (KeyError, IndexError, TypeError):
        return ""


def _tvmaze_details(show_name: str) -> dict:
    """Poster + summary + genres from TVMaze. Returns {} on no match."""
    data = _get_json(TVMAZE_SEARCH + urllib.parse.quote(show_name))
    if not data:
        return {}
    try:
        show = data[0]["show"]
        img = show.get("image") or {}
        summary = re.sub(r"<[^>]+>", "", show.get("summary") or "").strip()
        return {
            "poster": img.get("original") or img.get("medium") or "",
            "overview": summary,
            "genres": ", ".join(show.get("genres") or []),
        }
    except (KeyError, IndexError, TypeError):
        return {}


def _tmdb_search(title: str, year: int | None) -> list:
    params = {"api_key": TMDB_KEY, "query": title, "include_adult": "false"}
    if year:
        params["year"] = str(year)
    data = _get_json(TMDB_SEARCH + "?" + urllib.parse.urlencode(params))
    if isinstance(data, dict):
        return data.get("results", [])
    return []


def _tmdb_tv_poster(show_name: str, year: int | None) -> str:
    """TMDB TV search — fallback when TVMaze has no entry. Needs TMDB key."""
    if not TMDB_KEY:
        return ""
    params = {"api_key": TMDB_KEY, "query": show_name}
    if year:
        params["first_air_date_year"] = str(year)
    data = _get_json(TMDB_TV_SEARCH + "?" + urllib.parse.urlencode(params))
    try:
        results = data.get("results", []) if isinstance(data, dict) else []
        if not results:
            return ""
        path = results[0].get("poster_path") or ""
        return TMDB_IMG + path if path else ""
    except (KeyError, IndexError, TypeError):
        return ""


def _show_poster(name: str, year: int | None) -> str:
    url = _tvmaze_poster(name)
    if url:
        return url
    return _tmdb_tv_poster(name, year)


def _tmdb_details(title: str, year: int | None) -> dict:
    """Full movie metadata: poster, backdrop, overview, genres."""
    if not TMDB_KEY:
        return {}
    results = _tmdb_search(title, year)
    if not results and year:
        results = _tmdb_search(title, None)
    if not results:
        return {}
    try:
        best = results[0]
        gmap = _tmdb_genres()
        genres = ", ".join(gmap.get(g, "") for g in best.get("genre_ids", []) if g in gmap)
        poster = best.get("poster_path") or ""
        backdrop = best.get("backdrop_path") or ""
        return {
            "poster": TMDB_IMG + poster if poster else "",
            "backdrop": TMDB_BACKDROP + backdrop if backdrop else "",
            "overview": best.get("overview") or "",
            "genres": genres,
            "original_language": best.get("original_language") or "",
        }
    except (KeyError, IndexError, TypeError):
        return {}


def _tmdb_poster(title: str, year: int | None) -> str:
    return _tmdb_details(title, year).get("poster", "")


def enrich(limit: int = 500) -> dict:
    """Fill missing posters/metadata for shows and movies."""
    done = {"shows": 0, "movies": 0}
    with database.get_db() as conn:
        shows = conn.execute(
            "SELECT id, name, year, poster_url, overview FROM shows LIMIT ?",
            (limit,),
        ).fetchall()
        for row in shows:
            updates: dict[str, str] = {}
            details: dict = {}
            if not row["poster_url"]:
                details = _tvmaze_details(row["name"])
                if details.get("poster"):
                    updates["poster_url"] = details["poster"]
            if not row["overview"]:
                details = details or _tvmaze_details(row["name"])
                if details.get("overview"):
                    updates["overview"] = details["overview"]
                if details.get("genres"):
                    updates["genres"] = details["genres"]
            if not row["poster_url"] and not updates.get("poster_url"):
                tv = _tmdb_tv_poster(row["name"], row["year"])
                if tv:
                    updates["poster_url"] = tv
            for col, val in updates.items():
                conn.execute(f"UPDATE shows SET {col} = ? WHERE id = ?", (val, row["id"]))
            if updates:
                done["shows"] += 1
        movies = conn.execute(
            """SELECT id, title, year, poster_url, description, genre, language FROM movies
               WHERE media_type = 'movie' LIMIT ?""",
            (limit,),
        ).fetchall()
        for row in movies:
            updates = {}
            if not row["poster_url"] or not row["description"] or not row["genre"] or not row["language"]:
                details = _tmdb_details(row["title"], row["year"])
                if details.get("poster") and not row["poster_url"]:
                    updates["poster_url"] = details["poster"]
                if details.get("backdrop"):
                    updates["backdrop_url"] = details["backdrop"]
                if details.get("overview") and not row["description"]:
                    updates["description"] = details["overview"]
                if details.get("genres") and not row["genre"]:
                    updates["genre"] = details["genres"]
                if details.get("original_language") and not row["language"]:
                    lang = database.ISO_LANG.get(details["original_language"], "")
                    if lang:
                        updates["language"] = lang
            for col, val in updates.items():
                conn.execute(f"UPDATE movies SET {col} = ? WHERE id = ?", (val, row["id"]))
            if updates:
                done["movies"] += 1
    return done


_os_token: str | None = None


def _os_request(
    path: str,
    data: dict | None = None,
    query: str = "",
    token: str = "",
    timeout: int = 20,
) -> object | None:
    if not OS_KEY:
        return None
    url = OS_API + path + query
    headers = {"Api-Key": OS_KEY, "Content-Type": "application/json",
               "User-Agent": "MovieStream/1.0"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        body = json.dumps(data).encode() if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers,
                                     method="POST" if data is not None else "GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)
    except Exception as exc:
        log.warning("opensubtitles %s failed: %s", path, exc)
        return None


def _os_login() -> str:
    global _os_token
    if _os_token:
        return _os_token
    if not (OS_KEY and OS_USER and OS_PASS):
        return ""
    data = _os_request("/login", {"username": OS_USER, "password": OS_PASS})
    if isinstance(data, dict):
        _os_token = data.get("token") or ""
    return _os_token or ""


def _os_find_file(title: str, year: int | None, lang: str) -> int:
    params = {"query": title, "languages": lang}
    if year:
        params["year"] = str(year)
    data = _os_request("/subtitles", query="?" + urllib.parse.urlencode(params))
    if not isinstance(data, dict):
        return 0
    for sub in data.get("data", []):
        files = (sub.get("attributes") or {}).get("files") or []
        if files and files[0].get("file_id"):
            return int(files[0]["file_id"])
    return 0


def _os_download_text(file_id: int, token: str) -> str:
    data = _os_request("/download", {"file_id": file_id}, token=token)
    link = data.get("link", "") if isinstance(data, dict) else ""
    if not link:
        return ""
    try:
        req = urllib.request.Request(link, headers={"User-Agent": "MovieStream/1.0"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("subtitle download failed: %s", exc)
        return ""


def fetch_missing_subs(limit: int = 5) -> dict:
    """Download EN/HI subtitles for videos that have none.

    Free OpenSubtitles tier allows ~5 downloads/day; needs
    OPENSUBTITLES_API_KEY/USER/PASS in .env. Files land next to the
    video as <stem>.en.srt so the scanner picks them up.
    """
    done = {"fetched": 0, "skipped": 0}
    token = _os_login()
    if not token:
        return done
    with database.get_db() as conn:
        rows = conn.execute(
            """SELECT id, title, year, file_path FROM movies
               WHERE subtitles = '[]' OR subtitles IS NULL LIMIT ?""",
            (limit * 4,),
        ).fetchall()
    for row in rows:
        if done["fetched"] >= limit:
            break
        src = Path(row["file_path"])
        if not src.is_file():
            continue
        file_id, lang = 0, ""
        for candidate in ("en", "hi"):
            file_id = _os_find_file(row["title"], row["year"], candidate)
            if file_id:
                lang = candidate
                break
        if not file_id:
            done["skipped"] += 1
            continue
        text = _os_download_text(file_id, token)
        if not text:
            done["skipped"] += 1
            continue
        dest = src.parent / f"{src.stem}.{lang}.srt"
        try:
            dest.write_text(text, encoding="utf-8")
        except OSError as exc:
            log.warning("cannot save sub: %s", exc)
            continue
        with database.get_db() as conn:
            conn.execute(
                "UPDATE movies SET subtitles = ? WHERE id = ?",
                (json.dumps(database._find_subtitles(src)), row["id"]),
            )
        done["fetched"] += 1
    return done


def _ffmpeg_streams(src: str) -> list[dict]:
    """List subtitle streams: [{s_index, lang}]. Empty on failure/none."""
    try:
        import imageio_ffmpeg

        proc = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", src],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
            text=True,
        )
        tracks = []
        for line in proc.stderr.splitlines():
            m = re.search(r"Stream #\d+:\d+(?:\((\w+)\))?: Subtitle:", line)
            if m:
                code = (m.group(1) or "").lower()
                tracks.append({"s_index": len(tracks),
                               "lang": database.ISO_LANG.get(code, code or "und")})
        return tracks
    except Exception as exc:
        log.warning("probe failed for %s: %s", src.split("/")[-1], exc)
        return []


def _extract_embedded(src: str, s_index: int, dest: Path) -> bool:
    """Extract a subtitle track to WebVTT. False for bitmap/no track."""
    try:
        import imageio_ffmpeg

        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".tmp.vtt")
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-i", src,
             "-map", f"0:s:{s_index}", str(tmp)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
            check=True,
        )
        if tmp.stat().st_size < 50:
            tmp.unlink(missing_ok=True)
            return False
        tmp.rename(dest)
        return True
    except Exception:
        return False


def extract_embedded_subs(limit: int = 40) -> dict:
    """Pull embedded subtitle tracks out of videos lacking sidecars.

    Fully offline, no accounts, no quotas. Probes each file once
    (subs_probed flag) and caches the first English (else first) track
    as WebVTT in the video's Subs/ folder.
    """
    done = {"extracted": 0, "none_found": 0}
    with database.get_db() as conn:
        rows = conn.execute(
            """SELECT id, file_path FROM movies
               WHERE (subs_probed IS NULL OR subs_probed = 0)
               AND (subtitles = '[]' OR subtitles IS NULL) LIMIT ?""",
            (limit * 4,),
        ).fetchall()
    for row in rows:
        if done["extracted"] + done["none_found"] >= limit:
            break
        src = Path(row["file_path"])
        if not src.is_file():
            continue
        tracks = _ffmpeg_streams(str(src))
        picked = next((t for t in tracks if t["lang"] == "English"), tracks[0] if tracks else None)
        ok = False
        if picked:
            safe = re.sub(r"[^\w\-]+", "_", picked["lang"]) or "sub"
            dest = src.parent / "Subs" / f"{src.stem}.embedded.{safe}.vtt"
            ok = _extract_embedded(str(src), picked["s_index"], dest)
        with database.get_db() as conn:
            conn.execute("UPDATE movies SET subs_probed = 1 WHERE id = ?", (row["id"],))
            if ok:
                conn.execute(
                    "UPDATE movies SET subtitles = ? WHERE id = ?",
                    (json.dumps(database._find_subtitles(src)), row["id"]),
                )
                done["extracted"] += 1
            else:
                done["none_found"] += 1
    return done


YIFY_UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
           "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")


def _yify_session():
    cj = http.cookiejar.CookieJar()
    return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))


def _yify_get(opener, url: str, referer: str = "https://yifysubtitles.ch/",
              timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={
        "User-Agent": YIFY_UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": referer,
    })
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def _tmdb_imdb_id(title: str, year: int | None) -> str:
    if not TMDB_KEY:
        return ""
    results = _tmdb_search(title, year) or _tmdb_search(title, None)
    if not results:
        return ""
    tmdb_id = results[0].get("id")
    if not tmdb_id:
        return ""
    data = _get_json(f"https://api.themoviedb.org/3/movie/{tmdb_id}?api_key={TMDB_KEY}")
    if isinstance(data, dict):
        return data.get("imdb_id") or ""
    return ""


def _yify_best_english(imdb: str) -> str:
    """Return the subtitle-page slug of the highest-rated English sub."""
    slugs = _yify_english_slugs(imdb, top=1)
    return slugs[0] if slugs else ""


def _yify_english_slugs(imdb: str, top: int = 10) -> list[str]:
    """Subtitle-page slugs of the top-rated English subs, best first."""
    try:
        html = _yify_get(_yify_session(),
                         f"https://yifysubtitles.ch/movie-imdb/{imdb}").decode("utf-8", errors="replace")
    except Exception as exc:
        log.warning("yify page failed %s: %s", imdb, exc)
        return []
    scored = []
    for block in re.findall(r"<tr data-id=\"\d+\">.*?</tr>", html, re.DOTALL):
        lang = re.search(r'<span class="sub-lang">([^<]+)</span>', block)
        href = re.search(r'href="(/subtitles/[^"]+)"', block)
        score = re.search(r'<span class="label[^"]*">(-?\d+)</span>', block)
        if not lang or not href:
            continue
        if lang.group(1).strip().lower() != "english":
            continue
        scored.append((int(score.group(1)) if score else 0, href.group(1)))
    scored.sort(reverse=True)
    return [s for _, s in scored[:top]]


def _yify_download_srt(slug: str) -> bytes:
    """Download + extract the .srt from a /subtitles/<slug> entry."""
    import io
    import zipfile

    op = _yify_session()
    page_url = f"https://yifysubtitles.ch{slug}"
    _yify_get(op, f"https://yifysubtitles.ch/movie-imdb/tt0000000",
              timeout=20) if False else None
    zip_url = f"https://yifysubtitles.ch/subtitle/{slug.rsplit('/', 1)[-1]}.zip"
    req = urllib.request.Request(zip_url, headers={
        "User-Agent": YIFY_UA, "Referer": page_url,
        "Accept": "*/*", "Accept-Language": "en-US,en;q=0.9",
    })
    with op.open(req, timeout=60) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".srt", ".sub"))]
        if not names:
            return b""
        return z.read(names[0])


def fetch_yify_subs(limit: int = 100) -> dict:
    """Bulk-download English subs for movies missing them. No keys needed."""
    import time

    done = {"fetched": 0, "not_found": 0}
    with database.get_db() as conn:
        rows = conn.execute(
            """SELECT id, title, year, file_path FROM movies
               WHERE media_type = 'movie'
               AND (subtitles = '[]' OR subtitles IS NULL) LIMIT ?""",
            (limit,),
        ).fetchall()
    for row in rows:
        src = Path(row["file_path"])
        if not src.is_file():
            continue
        try:
            imdb = _tmdb_imdb_id(row["title"], row["year"])
            time.sleep(1)
            if not imdb:
                done["not_found"] += 1
                continue
            slugs = _yify_english_slugs(imdb)
            time.sleep(1)
            if not slugs:
                done["not_found"] += 1
                continue
            srt = b""
            for slug in slugs:
                try:
                    srt = _yify_download_srt(slug)
                    if len(srt) >= 200:
                        break
                except Exception:
                    srt = b""
                time.sleep(2)
            if len(srt) < 200:
                done["not_found"] += 1
                continue
            dest = src.parent / f"{src.stem}.en.srt"
            dest.write_bytes(srt)
            subs_json = json.dumps(database._find_subtitles(src))
            for attempt in range(5):
                try:
                    with database.get_db() as conn:
                        conn.execute(
                            "UPDATE movies SET subtitles = ? WHERE id = ?",
                            (subs_json, row["id"]),
                        )
                    break
                except Exception:
                    if attempt == 4:
                        raise
                    time.sleep(2)
            done["fetched"] += 1
            log.info("sub fetched: %s", row["title"])
        except Exception as exc:
            log.warning("yify failed for %s: %s", row["title"], exc)
            done["not_found"] += 1
            time.sleep(2)
    return done


def enrich_background() -> None:
    global _running
    if _running:
        return
    _running = True

    def _work() -> None:
        global _running
        try:
            done = enrich()
            log.info("enrichment done: %s", done)
            subs = fetch_missing_subs()
            log.info("subtitle fetch done: %s", subs)
            emb = extract_embedded_subs()
            log.info("embedded subs done: %s", emb)
        finally:
            _running = False

    threading.Thread(target=_work, daemon=True).start()


_thumb_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumb")
_thumb_queued: set[int] = set()
_thumb_lock = threading.Lock()


def _extract_frame(movie_id: int, src: str) -> None:
    """Blocking ffmpeg call — runs in the thumb pool, never in a request."""
    try:
        import imageio_ffmpeg

        out = database.POSTER_DIR / f"{movie_id}.jpg"
        if out.is_file():
            return
        database.POSTER_DIR.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.jpg")
        subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-ss", "10", "-i", src,
             "-frames:v", "1", "-vf", "scale=342:-1", "-q:v", "5", str(tmp)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=60,
            check=True,
        )
        tmp.rename(out)
    except Exception as exc:
        log.warning("thumb failed for %s: %s", movie_id, exc)
    finally:
        with _thumb_lock:
            _thumb_queued.discard(movie_id)


def queue_thumb(movie_id: int, src: str) -> None:
    with _thumb_lock:
        if movie_id in _thumb_queued:
            return
        _thumb_queued.add(movie_id)
    _thumb_pool.submit(_extract_frame, movie_id, src)


def pregen_thumbs_background() -> None:
    """Queue frame extraction for every video missing a cached poster."""

    def _work() -> None:
        with database.get_db() as conn:
            rows = conn.execute("SELECT id, file_path FROM movies").fetchall()
        for row in rows:
            out = database.POSTER_DIR / f"{row['id']}.jpg"
            if not out.is_file() and Path(row["file_path"]).is_file():
                queue_thumb(row["id"], row["file_path"])

    threading.Thread(target=_work, daemon=True).start()
