# MovieStream

A private, Netflix-style streaming app for your own movie and TV collection.
Single-user login, a fast scrub/seek video player with subtitles, and poster/genre enrichment.

This repo is the **backend**, and it runs on your own computer. The UI is a separate repo,
[moviestream-frontend](https://github.com/Aakashjammula/moviestream-frontend), hosted on Vercel.

## Architecture

```
movies.aakashjammula.com      ──> Vercel: static UI (always on)
movies-api.aakashjammula.com  ──> Cloudflare Tunnel ──> backend:8000 (this repo, only while your PC is on)
```

| Service | Role |
|---|---|
| `backend` | FastAPI: media index (SQLite), login sessions, TMDB/TVMaze enrichment, subtitles, **and the video files themselves** (Range requests for seeking) |
| `cloudflared` | Cloudflare Tunnel: publishes `backend:8000` as `movies-api.aakashjammula.com` |

When your PC is off, the UI shows "Server is offline" and reconnects automatically once you start the stack.

How the two sites work together:
- **Both addresses are on the same site,** so the `SameSite=Lax` login cookie works.
- **CORS allows only the origins in `FRONTEND_ORIGINS`,** with credentials.
- **Video, posters and subtitles go browser ↔ tunnel directly,** never through Vercel.

## Prerequisites

- Docker + Docker Compose
- A folder of video files (`.mp4`, `.mkv`, …), movies and/or TV shows in any nesting
- (Optional) A free [TMDB API key](https://www.themoviedb.org/settings/api) for posters, overviews and genres
- A Cloudflare account with your domain, for the tunnel

## Setup

1. **Configure the environment:**
   ```bash
   cp .env.example .env
   ```
   Edit `.env`:
   - `MEDIA_DIR`: absolute path to your media folder (required).
   - `APP_PASSWORD_HASH`: bcrypt hash of your login password. Generate it with:
     ```bash
     docker compose run --rm backend python3 -c \
       "import bcrypt,getpass; print(bcrypt.hashpw(getpass.getpass().encode(), bcrypt.gensalt()).decode())"
     ```
   - `FRONTEND_ORIGINS`: where the UI is served from, e.g. `https://movies.aakashjammula.com,http://localhost:3000`.
   - `TUNNEL_TOKEN`: the Cloudflare Tunnel token (see below).
   - `TMDB_API_KEY`: for posters and descriptions. Recommended; without it you get generated thumbnails.
   - `OPENSUBTITLES_*`: optional; improves subtitle matching.

2. **Cloudflare Tunnel:** Cloudflare dashboard → Networks → Tunnels. Create a tunnel and copy its token into `TUNNEL_TOKEN`. Then add the public hostname **`movies-api.aakashjammula.com` → `http://backend:8000`**.

3. **Start it** (whenever you want MovieStream online):
   ```bash
   docker compose up -d --build
   ```
   The first start scans your media; posters and subtitles are filled in in the background.

4. **Stop it:** `docker compose down`. The UI then shows "Server is offline".

## Everyday use

| Action | How |
|---|---|
| Rescan library | ⟳ button in the top bar (or restart `backend`) |
| Manage devices | **Sessions** page: see every signed-in device (IP, last active), revoke one, or sign out all others |
| My List / Continue Watching | Stored per browser in localStorage |
| Player shortcuts | `Space`/`K` play/pause, `←`/`→` ∓10s, `S` skip intro, `F` fullscreen, `M` mute, `Esc` back |

## Notes

- Filenames like `Show.Name.S01E02.1080p...` are parsed for title, year, quality and language. Audio tracks are probed with ffmpeg, and TMDB fills the gaps.
- Subtitles: sidecar `.srt`/`.vtt` files are used first. Missing ones are auto-downloaded (YIFY/OpenSubtitles) and saved **next to the video**, so the media folder is mounted writable.
- Sessions expire after 30 days of inactivity. Login attempts are rate-limited per visitor IP (`CF-Connecting-IP`).
- `backend` also listens on port 8000 locally, for frontend development on `localhost:3000`.
- Code layout: `main.py` (API), `database.py` (media index, sessions), `enrich.py` (TMDB/TVMaze, subtitles). Docker builds from the repo root; `.dockerignore` keeps `.env` out of the image.
- The backend still supports nginx `X-Accel-Redirect` delivery (requests with `X-Via-Nginx: 1`), in case you ever put nginx back for heavier use.

## Development

```bash
docker compose up -d --build backend   # rebuild after code changes
docker compose logs -f backend         # watch the API / scan logs
```
