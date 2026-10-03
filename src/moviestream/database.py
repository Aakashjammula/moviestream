"""SQLite storage for the movie library.

Media is split into two types:
- ``movie``: standalone files (e.g. ``/mnt/movies/movies/Title (2020).mp4``)
- ``tv``: shows with seasons/episodes
  (e.g. ``/mnt/movies/tv/Show Name (2009)/s1/1.mp4``)

Uses only the stdlib ``sqlite3`` module. The database file lives in a
persistent Docker volume (``MOVIE_DB`` env, default ``/app/data/movies.db``).
"""

from __future__ import annotations

import glob
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DATABASE_PATH = Path(os.environ.get("MOVIE_DB", "/app/data/movies.db"))
MOVIE_DIR = Path(os.environ.get("MOVIE_DIR", "/mnt/movies"))
POSTER_DIR = Path(os.environ.get("POSTER_DIR", "/app/data/posters"))

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS shows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    year INTEGER,
    poster_url TEXT DEFAULT '',
    overview TEXT DEFAULT '',
    genres TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    created_at INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    user_agent TEXT DEFAULT '',
    ip TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    year INTEGER,
    genre TEXT DEFAULT '',
    file_path TEXT NOT NULL UNIQUE,
    media_type TEXT DEFAULT 'movie',
    show_id INTEGER REFERENCES shows(id),
    season INTEGER,
    episode INTEGER,
    poster_url TEXT DEFAULT '',
    language TEXT DEFAULT '',
    quality TEXT DEFAULT '',
    backdrop_url TEXT DEFAULT '',
    subtitles TEXT DEFAULT '[]'
)
"""

# Columns added after the first release; filled by _migrate().
NEW_COLUMNS = [
    ("media_type", "TEXT DEFAULT 'movie'"),
    ("show_id", "INTEGER REFERENCES shows(id)"),
    ("season", "INTEGER"),
    ("episode", "INTEGER"),
    ("poster_url", "TEXT DEFAULT ''"),
    ("language", "TEXT DEFAULT ''"),
    ("quality", "TEXT DEFAULT ''"),
    ("backdrop_url", "TEXT DEFAULT ''"),
    ("subtitles", "TEXT DEFAULT '[]'"),
    ("subs_probed", "INTEGER DEFAULT 0"),
]
NEW_SHOW_COLUMNS = [
    ("overview", "TEXT DEFAULT ''"),
    ("genres", "TEXT DEFAULT ''"),
]


def _connect() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DATABASE_PATH), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


@contextmanager
def get_db() -> Iterator[sqlite3.Connection]:
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _migrate(conn: sqlite3.Connection) -> None:
    existing = {r["name"] for r in conn.execute("PRAGMA table_info(movies)").fetchall()}
    for col, ddl in NEW_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE movies ADD COLUMN {col} {ddl}")
    show_existing = {r["name"] for r in conn.execute("PRAGMA table_info(shows)").fetchall()}
    for col, ddl in NEW_SHOW_COLUMNS:
        if col not in show_existing:
            conn.execute(f"ALTER TABLE shows ADD COLUMN {col} {ddl}")


def init_db() -> None:
    with get_db() as conn:
        conn.executescript(SCHEMA)
        _migrate(conn)


def _clean_name(raw: str) -> str:
    name = raw.replace(".", " ").replace("_", " ").strip()
    name = re.sub(r"\[[^\]]*\]", "", name)  # [1080p] [WEBRip] [YTS.BZ]
    name = re.sub(r"\(\d{4}\)", "", name)
    name = re.sub(r"\b(19\d{2}|20\d{2})\b", "", name)
    return re.sub(r"\s+", " ", name).strip(" -")


# Manual search aliases for titles the cleaners can't salvage.
TITLE_OVERRIDES = {
    "Interstellar FR-EN": "Interstellar",
}


def _clean_release_name(stem: str) -> str:
    """Strip release tags from a scene filename for display/search."""
    name = re.sub(r"[._\-]+", " ", stem)
    name = TAG_PATTERN.sub(" ", name)
    name = re.sub(r"\(\d{4}\)|\b(19\d{2}|20\d{2})\b", " ", name)
    name = re.sub(r"\s+", " ", name).strip(" -")
    return name


def _movie_title(path: Path) -> str:
    """Prefer the parent folder ('Title (Year)') over the release filename."""
    parent = path.parent
    if parent != MOVIE_DIR and parent.name.strip(" ."):
        title = _clean_name(parent.name)
        if title and len(title) > 2:
            return TITLE_OVERRIDES.get(title, title)
    title = _clean_release_name(path.stem) or _clean_name(path.stem)
    return TITLE_OVERRIDES.get(title, title)


def _parse_year(parts: list[str]) -> int | None:
    for part in parts:
        m = re.search(r"\((19\d{2}|20\d{2})\)", part)
        if m:
            return int(m.group(1))
    return None


def _parse_quality(name: str) -> str:
    low = name.lower()
    if "2160p" in low or " 4k" in low or "4k " in low:
        return "4K"
    if "1080p" in low:
        return "1080p"
    if "720p" in low:
        return "720p"
    if "480p" in low:
        return "480p"
    return ""


def _probe_quality(path: Path) -> str:
    """Read real resolution via ffmpeg when the filename has no tags."""
    try:
        import subprocess

        import imageio_ffmpeg

        proc = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
            text=True,
        )
        m = re.search(r"Video:.*?, (\d{3,4})x(\d{3,4})", proc.stderr)
        if not m:
            return ""
        w, h = int(m.group(1)), int(m.group(2))
        if h >= 2000 or w >= 3500:
            return "4K"
        if h >= 1000 or w >= 1900:
            return "1080p"
        if h >= 690 or w >= 1200:
            return "720p"
        if h >= 450:
            return "480p"
        return "SD"
    except Exception:
        return ""


LANG_TOKENS = [
    ("hindi", "Hindi"), ("hin", "Hindi"),
    ("english", "English"), ("eng", "English"),
    ("tamil", "Tamil"), ("tam", "Tamil"),
    ("telugu", "Telugu"), ("tel", "Telugu"),
    ("korean", "Korean"), ("kor", "Korean"),
    ("italian", "Italian"), ("ita", "Italian"),
    ("spanish", "Spanish"), ("spa", "Spanish"),
    ("french", "French"), ("fre", "French"), ("fra", "French"),
    ("german", "German"), ("ger", "German"), ("deu", "German"),
    ("portuguese", "Portuguese"), ("por", "Portuguese"),
    ("arabic", "Arabic"), ("ara", "Arabic"),
    ("japanese", "Japanese"), ("jpn", "Japanese"),
]


def _parse_language(name: str) -> str:
    low = re.sub(r"[._\-]+", " ", name).lower()
    if "multi" in low or "dual audio" in low:
        return "Multi"
    found = []
    for token, label in LANG_TOKENS:
        if re.search(rf"\b{token}\b", low) and label not in found:
            found.append(label)
    return ", ".join(found[:3])


SUB_EXTENSIONS = {".srt", ".vtt"}

ISO_LANG = {
    "eng": "English", "en": "English", "hin": "Hindi", "hi": "Hindi",
    "tam": "Tamil", "ta": "Tamil", "tel": "Telugu", "te": "Telugu", "kor": "Korean", "ko": "Korean",
    "ita": "Italian", "it": "Italian", "spa": "Spanish", "es": "Spanish",
    "fre": "French", "fra": "French", "fr": "French", "ger": "German",
    "deu": "German", "de": "German", "por": "Portuguese", "pt": "Portuguese",
    "ara": "Arabic", "ar": "Arabic", "jpn": "Japanese", "ja": "Japanese",
    "mal": "Malayalam", "ml": "Malayalam", "kan": "Kannada", "kn": "Kannada",
    "mar": "Marathi", "mr": "Marathi", "ben": "Bengali", "bn": "Bengali",
    "pan": "Punjabi", "pa": "Punjabi", "pun": "Punjabi",
    "urd": "Urdu", "ur": "Urdu",
    "rus": "Russian", "ru": "Russian", "ukr": "Ukrainian", "uk": "Ukrainian",
    "chi": "Chinese", "zho": "Chinese", "cmn": "Chinese", "zh": "Chinese",
    "tha": "Thai", "th": "Thai", "vie": "Vietnamese", "vi": "Vietnamese",
    "ind": "Indonesian", "id": "Indonesian", "msa": "Malay", "ms": "Malay",
    "tur": "Turkish", "tr": "Turkish", "nld": "Dutch", "dut": "Dutch",
    "nl": "Dutch", "swe": "Swedish", "sv": "Swedish",
    "nor": "Norwegian", "nb": "Norwegian", "nob": "Norwegian",
    "dan": "Danish", "da": "Danish", "fin": "Finnish", "fi": "Finnish",
    "pol": "Polish", "pl": "Polish", "ces": "Czech", "cze": "Czech",
    "cs": "Czech", "hun": "Hungarian", "hu": "Hungarian",
    "ell": "Greek", "gre": "Greek", "el": "Greek",
    "heb": "Hebrew", "he": "Hebrew",
}


def _probe_audio_languages(path: Path) -> str:
    """Read real audio track languages via ffmpeg (ground truth).

    Parses lines like: Stream #0:1(hin): Audio: aac ...
    Returns '' when undetermined or on any failure.
    """
    try:
        import subprocess

        import imageio_ffmpeg

        proc = subprocess.run(
            [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=30,
            text=True,
        )
        found: list[str] = []
        for m in re.finditer(
            r"Stream #\d+:\d+(?:\((\w+)\))?: Audio", proc.stderr or ""
        ):
            code = (m.group(1) or "").lower()
            if code in ("und", ""):
                continue
            label = ISO_LANG.get(code)
            if label and label not in found:
                found.append(label)
        return ", ".join(found[:3])
    except Exception:
        return ""


def _detect_language(path: Path) -> str:
    """Filename tokens first (cheap); fall back to audio probe (accurate)."""
    lang = _parse_language(path.stem + " " + path.parent.name)
    if not lang and path.is_file():
        lang = _probe_audio_languages(path)
    return lang


def _find_subtitles(path: Path) -> list[dict]:
    """Sidecar captions: same-name .srt/.vtt plus any in a Subs/ subfolder."""
    found: list[dict] = []
    seen: set[str] = set()
    # NOTE: stems contain glob metachars like [YTS.MX] — must escape.
    candidates = list(path.parent.glob(glob.escape(path.stem) + "*"))
    subs_dir = path.parent / "Subs"
    if subs_dir.is_dir():
        candidates += [p for p in subs_dir.iterdir() if p.is_file()]
    for sub in sorted(candidates):
        if sub.suffix.lower() not in SUB_EXTENSIONS or str(sub) in seen:
            continue
        seen.add(str(sub))
        stem = sub.stem
        lang = ""
        m = re.search(r"\.([a-z]{2,3})$", stem, re.IGNORECASE)
        if m and m.group(1).lower() in ISO_LANG:
            lang = ISO_LANG[m.group(1).lower()]
        else:
            for token, label in LANG_TOKENS:
                if re.search(rf"\b{token}\b", stem, re.IGNORECASE):
                    lang = label
                    break
        try:
            rel = str(sub.relative_to(MOVIE_DIR))
        except ValueError:
            rel = sub.name
        found.append({"lang": lang or sub.stem, "file": rel})
    return found


EP_MARKER = re.compile(r"s(\d{1,2})e(\d{1,3})", re.IGNORECASE)

# Release tags stripped when deriving a show name from a release filename.
TAG_PATTERN = re.compile(
    r"\b(720p|1080p|2160p|4k|webrip|web[ -]?dl|bluray|brrip|hdrip|hdtv|x26[45]|"
    r"hevc|10bit|multi|dual.audio|hindi|eng|tam|tel|kor|ita|msubs|ddp|aac|dts|"
    r"sdr|hdr|h\s?264|xvid|yify|yts(?:\.[a-z]+)?|vxt|psa|rarbg|blu\.?ray)\b",
    re.IGNORECASE,
)


def _is_tv(path: Path, rel_parts: tuple[str, ...]) -> bool:
    # Strongest signal first: an SxxExx episode marker anywhere means TV,
    # even if the file was dumped under a movies/ folder.
    haystack = " ".join([path.stem, *rel_parts])
    if EP_MARKER.search(haystack):
        return True
    if rel_parts and rel_parts[0].lower() in ("tv", "shows", "series", "tv shows"):
        return True
    if rel_parts and rel_parts[0].lower() in ("movies", "films"):
        return False
    joined = "/".join(rel_parts).lower()
    return bool(re.search(r"(^|/)(s\d{1,2}|season \d+)(/|$)", joined))


def _parse_season(rel_parts: tuple[str, ...], stem: str = "") -> int:
    for part in rel_parts:
        m = re.fullmatch(r"s(\d{1,2})", part.lower()) or re.fullmatch(
            r"season\s*(\d{1,2})", part.lower()
        )
        if m:
            return int(m.group(1))
    m = EP_MARKER.search(stem)
    if m:
        return int(m.group(1))
    return 1


def _show_name_from_episode(stem: str) -> str:
    """Derive a clean show name from a release filename.

    'Can.This.Love.Be.Translated.S01E01.Episode.1.720p...' ->
    'Can This Love Be Translated'

    Returns '' when there is no SxxExx marker — without it the show
    name cannot be told apart from the episode title, so callers must
    fall back to the folder name.
    """
    if not EP_MARKER.search(stem):
        return ""
    left = EP_MARKER.split(stem, maxsplit=1)[0]
    left = re.sub(r"[._\-]+", " ", left)
    left = TAG_PATTERN.sub(" ", left)
    left = re.sub(
        r"\b(episode|ep|part|vol|volume)\s*\d*\b", " ", left, flags=re.IGNORECASE
    )
    left = re.sub(r"\b(19\d{2}|20\d{2})\b", " ", left)
    return re.sub(r"\s+", " ", left).strip(" -")


def _parse_episode(stem: str) -> int | None:
    m = re.search(r"s\d{1,2}e(\d{1,3})", stem.lower())
    if m:
        return int(m.group(1))
    m = re.search(r"\be(?:p(?:isode)?)?\s?(\d{1,3})\b", stem.lower())
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"(\d{1,3})", stem.strip())
    if m:
        return int(m.group(1))
    return None


def _get_show_id(conn: sqlite3.Connection, name: str, year: int | None) -> int:
    row = conn.execute("SELECT id FROM shows WHERE name = ?", (name,)).fetchone()
    if row:
        if year:
            conn.execute("UPDATE shows SET year = ? WHERE id = ?", (year, row["id"]))
        return row["id"]
    cur = conn.execute(
        "INSERT INTO shows (name, year) VALUES (?, ?)", (name, year)
    )
    return cur.lastrowid


def media_available() -> bool:
    """True when the media folder is reachable and not empty.

    An unplugged drive shows up as a missing folder or an empty placeholder
    directory, so "exists but empty" counts as not connected.
    """
    try:
        with os.scandir(MOVIE_DIR) as entries:
            return next(entries, None) is not None
    except OSError:
        return False


def scan_movies() -> int:
    """Walk MOVIE_DIR and upsert every video file. Returns files indexed."""
    init_db()
    if not MOVIE_DIR.is_dir():
        return 0
    count = 0
    with get_db() as conn:
        for root, _dirs, files in os.walk(MOVIE_DIR):
            for name in sorted(files):
                path = Path(root) / name
                if path.suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                try:
                    rel_parts = path.relative_to(MOVIE_DIR).parts
                except ValueError:
                    rel_parts = (path.name,)
                year = _parse_year([path.stem, *map(str, path.parents)])
                quality = _parse_quality(path.stem) or _parse_quality(str(path.parent))
                if not quality and path.is_file():
                    quality = _probe_quality(path)
                language = _detect_language(path)
                subtitles = json.dumps(_find_subtitles(path))
                if _is_tv(path, rel_parts):
                    season = _parse_season(rel_parts, path.stem)
                    episode = _parse_episode(path.stem)
                    if episode is not None:
                        show_name = _show_name_from_episode(path.stem)
                        if not show_name:
                            show_raw = rel_parts[1] if len(rel_parts) > 2 else rel_parts[0]
                            show_name = _clean_name(show_raw)
                        title = f"{show_name} S{season:02d}E{episode:02d}"
                    else:
                        show_raw = rel_parts[1] if len(rel_parts) > 2 else rel_parts[0]
                        show_name = _clean_name(show_raw)
                        title = _clean_name(path.stem)
                    show_id = _get_show_id(conn, show_name, year)
                    conn.execute(
                        """INSERT INTO movies
                           (title, year, genre, file_path, media_type, show_id, season, episode,
                            language, quality, subtitles)
                           VALUES (?, ?, 'tv', ?, 'tv', ?, ?, ?, ?, ?, ?)
                           ON CONFLICT(file_path) DO UPDATE SET
                               title = excluded.title, year = excluded.year,
                               media_type = 'tv', show_id = excluded.show_id,
                               season = excluded.season, episode = excluded.episode,
                               language = excluded.language, quality = excluded.quality,
                               subtitles = excluded.subtitles""",
                        (title, year, str(path), show_id, season, episode,
                         language, quality, subtitles),
                    )
                else:
                    conn.execute(
                        """INSERT INTO movies (title, year, genre, file_path, media_type,
                                            language, quality, subtitles)
                           VALUES (?, ?, '', ?, 'movie', ?, ?, ?)
                           ON CONFLICT(file_path) DO UPDATE SET
                               title = excluded.title, year = excluded.year,
                               genre = '', media_type = 'movie',
                               language = excluded.language, quality = excluded.quality,
                               subtitles = excluded.subtitles""",
                        (_movie_title(path), year, str(path), language, quality, subtitles),
                    )
                count += 1
        # Drop shows left with no episodes ( regrouped or deleted files).
        conn.execute(
            "DELETE FROM shows WHERE id NOT IN (SELECT DISTINCT show_id FROM movies WHERE show_id IS NOT NULL)"
        )
    return count


if __name__ == "__main__":
    init_db()
    n = scan_movies()
    print(f"Database initialized at {DATABASE_PATH}, {n} files indexed.")


SESSION_TTL = 30 * 24 * 3600  # 30 days


def create_session(user_agent: str = "", ip: str = "") -> str:
    sid = secrets.token_urlsafe(32)
    now = int(time.time())
    with get_db() as conn:
        conn.execute(
            "INSERT INTO sessions (id, created_at, last_seen, user_agent, ip)"
            " VALUES (?, ?, ?, ?, ?)",
            (sid, now, now, user_agent[:200], ip[:64]),
        )
    return sid


def valid_session(sid: str) -> bool:
    if not sid:
        return False
    now = int(time.time())
    with get_db() as conn:
        row = conn.execute(
            "SELECT last_seen FROM sessions WHERE id = ?", (sid,)
        ).fetchone()
        if row is None or now - row["last_seen"] > SESSION_TTL:
            if row is not None:
                conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))
            return False
        conn.execute("UPDATE sessions SET last_seen = ? WHERE id = ?", (now, sid))
    return True


def delete_session(sid: str) -> None:
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE id = ?", (sid,))


def delete_other_sessions(keep_sid: str) -> int:
    """Revoke every session except keep_sid. Returns revoked count."""
    with get_db() as conn:
        cur = conn.execute("DELETE FROM sessions WHERE id != ?", (keep_sid,))
        return cur.rowcount


def list_sessions() -> list[dict]:
    """All sessions, newest activity first; expired ones pruned."""
    now = int(time.time())
    with get_db() as conn:
        conn.execute("DELETE FROM sessions WHERE ? - last_seen > ?", (now, SESSION_TTL))
        rows = conn.execute(
            "SELECT id, created_at, last_seen, user_agent, ip FROM sessions"
            " ORDER BY last_seen DESC"
        ).fetchall()
        return [dict(r) for r in rows]
