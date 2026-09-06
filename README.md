# MovieStream

A private, Netflix-style streaming app for your own movie + TV show collection.
Single-user login, fast scrub/seek video player with subtitles, and poster/genre
enrichment — all self-hosted with Docker Compose.

## Architecture

```
browser ──> nginx:80 ─┬─ / ─────> frontend (Next.js)
                        ├─ /api/ ─> backend (FastAPI + uvicorn, 4 workers)
                        └─ /_media/ (internal, X-Accel-Redirect video bytes, sendfile)
cloudflared ──> nginx (optional: exposes the app on your domain)
```

| Service    | Role                                                                 |
|------------|----------------------------------------------------------------------|
| `backend`  | SQLite index of media, auth sessions, TMDB/TVMaze enrichment, subtitle fetching, X-Accel-Redirect stream authorization |
| `frontend` | Next.js UI: browse rails, detail modals, custom player, My List, Continue Watching, Sessions |
| `nginx`    | Reverse proxy + zero-copy video delivery with Range/seek support      |
| `cloudflared` | Optional Cloudflare Tunnel for access outside your LAN            |

Media files are mounted **read-only**; the app never modifies your library.
My List and Continue Watching are stored in the browser's localStorage.

## Prerequisites

- Docker + Docker Compose
- A folder of video files (`.mp4`, `.mkv`, …), movies and/or TV shows in any nesting
- (Optional) A free [TMDB API key](https://www.themoviedb.org/settings/api) for posters/overviews/genres
- (Optional) A Cloudflare account + domain for remote access

## Setup

1. **Configure environment:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   - `MEDIA_DIR` — absolute path to your media folder (required).
   - `APP_PASSWORD_HASH` — bcrypt hash of your login password. Generate it:
     ```bash
     docker compose run --rm backend python3 -c \
       "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"
     ```
   - `TMDB_API_KEY` — for posters/descriptions (recommended; without it you get generated thumbnails).
   - `TUNNEL_TOKEN` — Cloudflare Tunnel token (only needed for remote access; see below).
   - `OPENSUBTITLES_*` — optional, improves subtitle matching.

2. **Start the stack:**
   ```bash
   docker compose up -d --build
   ```
   First start scans your media (posters/subtitles enrich in the background).

3. **Open it:** http://localhost (nginx) — sign in with your password.

## Remote access (Cloudflare Tunnel)

1. Cloudflare dashboard → Networks → Tunnels → create a tunnel, copy its token into `TUNNEL_TOKEN` in `.env`.
2. Add a public hostname in the tunnel pointing at `http://nginx:80`.
3. `docker compose up -d cloudflared`
4. (Recommended) Protect it with Cloudflare Access (e.g. email PIN) as a second factor in front of the app login.

## Everyday use

| Action | How |
|---|---|
| Rescan library | ⟳ button in the top bar (or restart `backend`) |
| Manage devices | **Sessions** nav page — see every signed-in device (IP, last active), revoke one, or sign out all others |
| My List / Continue Watching | Stored per-browser in localStorage |
| Player shortcuts | `Space`/`K` play-pause, `←`/`→` ∓10s, `S` skip intro, `F` fullscreen, `M` mute, `Esc` back |

## Notes

- Filenames like `Show.Name.S01E02.1080p...` are parsed for title/year/quality/language; audio tracks are probed with ffmpeg and TMDB fills gaps.
- Subtitles: sidecar `.srt/.vtt` files are used first, then auto-downloaded (YIFY/OpenSubtitles) into the Docker volume.
- Sessions expire after 30 days of inactivity.
- `backend` exposes port 8000 for direct API/dev access; production traffic goes through nginx.

## Development

```bash
docker compose up -d --build backend frontend   # rebuild after code changes
docker compose logs -f backend                  # watch the API / scan logs
```
