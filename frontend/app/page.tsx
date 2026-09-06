'use client';

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IBack, IChevL, IChevR, ICheck, IClose, IFull, IFwd10, IInfo, ILogout, IMute, IPause, IPlay, IPlus, IRefresh, IRew10, IVol } from "./icons";

interface Sub {
  index: number;
  lang: string;
}

interface Movie {
  id: number;
  title: string;
  description: string;
  year: number | null;
  genre: string;
  file_path: string;
  poster_url: string;
  language: string;
  quality: string;
  backdrop_url: string;
  subtitles: { lang: string; file: string }[];
}

interface Show {
  id: number;
  name: string;
  year: number | null;
  poster_url: string;
  seasons: number;
  episode_count: number;
  overview: string;
  genres: string;
  has_subs: boolean;
}

interface Episode {
  id: number;
  title: string;
  year: number | null;
  season: number | null;
  episode: number | null;
  file_path: string;
  poster_url: string;
  language: string;
  quality: string;
  subtitles: { lang: string; file: string }[];
}

interface ShowDetail extends Show {
  episodes: Episode[];
}

interface Playing {
  id: number;
  title: string;
  description: string;
  year: number | null;
  genre: string;
  language: string;
  quality: string;
  container?: string;
  queue?: { id: number; title: string }[];
  resumeFrom?: number;
}

interface ListItem {
  kind: "movie" | "show";
  id: number;
}

interface Progress {
  id: number;
  title: string;
  kind: "movie" | "episode";
  showId?: number;
  showName?: string;
  time: number;
  duration: number;
  updatedAt: number;
  hasSubs?: boolean;
}

interface Session {
  id: string;
  created_at: number;
  last_seen: number;
  user_agent: string;
  ip: string;
  current: boolean;
}

type View = "home" | "movies" | "tv" | "mylist" | "sessions";

async function api<T>(path: string): Promise<T> {
  const res = await fetch(path);
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
    throw new Error("Login required");
  }
  if (!res.ok) throw new Error(`API returned ${res.status}`);
  return res.json();
}

async function apiMut<T>(path: string, method: string): Promise<T> {
  const res = await fetch(path, { method });
  if (res.status === 401 && typeof window !== "undefined") {
    window.location.href = "/login?next=" + encodeURIComponent(window.location.pathname);
    throw new Error("Login required");
  }
  if (!res.ok) throw new Error(`API returned ${res.status}`);
  return res.json();
}

function splitList(v: string): string[] {
  return v.split(",").map((s) => s.trim()).filter(Boolean);
}

function extOf(p: string): string {
  const i = p.lastIndexOf(".");
  return i >= 0 ? p.slice(i).toLowerCase() : "";
}

function fmtTime(s: number): string {
  if (!isFinite(s) || s < 0) return "0:00";
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}` : `${m}:${String(sec).padStart(2, "0")}`;
}

/* ---------- localStorage stores ---------- */

function useMyList() {
  const [list, setList] = useState<ListItem[]>([]);
  useEffect(() => {
    try {
      setList(JSON.parse(localStorage.getItem("mylist") || "[]"));
    } catch {
      setList([]);
    }
  }, []);
  const toggle = (item: ListItem) => {
    setList((prev) => {
      const has = prev.some((x) => x.kind === item.kind && x.id === item.id);
      const next = has
        ? prev.filter((x) => !(x.kind === item.kind && x.id === item.id))
        : [...prev, item];
      localStorage.setItem("mylist", JSON.stringify(next));
      return next;
    });
  };
  const has = (kind: string, id: number) =>
    list.some((x) => x.kind === kind && x.id === id);
  return { list, toggle, has };
}

function readProgress(): Progress[] {
  try {
    return JSON.parse(localStorage.getItem("progress") || "[]");
  } catch {
    return [];
  }
}

function saveProgress(p: Progress) {
  try {
    const all = readProgress().filter((x) => x.id !== p.id);
    if (p.duration > 0 && p.time > 10 && p.time < p.duration - 20) {
      all.unshift({ ...p, updatedAt: Date.now() });
    }
    localStorage.setItem("progress", JSON.stringify(all.slice(0, 30)));
  } catch {
    /* ignore */
  }
}

function clearProgress(id: number) {
  try {
    localStorage.setItem(
      "progress",
      JSON.stringify(readProgress().filter((x) => x.id !== id))
    );
  } catch {
    /* ignore */
  }
}

/* ---------- app ---------- */

export default function Home() {
  const [view, setView] = useState<View>("home");
  const [movies, setMovies] = useState<Movie[]>([]);
  const [shows, setShows] = useState<Show[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [genre, setGenre] = useState("all");
  const [language, setLanguage] = useState("all");
  const [quality, setQuality] = useState("all");
  const [playing, setPlaying] = useState<Playing | null>(null);
  const [detailMovie, setDetailMovie] = useState<Movie | null>(null);
  const [openShow, setOpenShow] = useState<ShowDetail | null>(null);
  const [scrolled, setScrolled] = useState(false);
  const [progressTick, setProgressTick] = useState(0);
  const mylist = useMyList();

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 40);
    window.addEventListener("scroll", onScroll);
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    Promise.all([api<Movie[]>("/api/movies"), api<Show[]>("/api/shows")])
      .then(([m, s]) => {
        if (!cancelled) {
          setMovies(m);
          setShows(s);
          setLoading(false);
        }
      })
      .catch((err: Error) => {
        if (!cancelled) {
          setError(err.message);
          setLoading(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const refreshProgress = useCallback(() => setProgressTick((t) => t + 1), []);

  // Lock background scroll whenever any modal/player is open.
  useEffect(() => {
    const lock = detailMovie || openShow || playing;
    if (!lock) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => { document.body.style.overflow = prev; };
  }, [detailMovie, openShow, playing]);

  const openShowDetail = (show: Show) => {
    api<ShowDetail>(`/api/shows/${show.id}`)
      .then(setOpenShow)
      .catch((err: Error) => setError(err.message));
  };

  const genreOptions = useMemo(() => {
    const set = new Set<string>();
    movies.forEach((m) => splitList(m.genre).forEach((g) => set.add(g)));
    shows.forEach((s) => splitList(s.genres).forEach((g) => set.add(g)));
    return ["all", ...Array.from(set).sort()];
  }, [movies, shows]);

  const languageOptions = useMemo(() => {
    const set = new Set<string>();
    movies.forEach((m) => splitList(m.language).forEach((l) => set.add(l)));
    return ["all", ...Array.from(set).sort()];
  }, [movies]);

  const qualityOptions = useMemo(() => {
    const set = new Set<string>();
    movies.forEach((m) => {
      if (m.quality) set.add(m.quality);
    });
    const order = ["4K", "1080p", "720p", "480p", "SD"];
    const rank = (x: string) => {
      const i = order.indexOf(x);
      return i === -1 ? 99 : i;
    };
    return ["all", ...Array.from(set).sort((a, b) => rank(a) - rank(b))];
  }, [movies]);

  const q = query.trim().toLowerCase();
  const filteredMovies = useMemo(
    () =>
      movies.filter((m) => {
        if (genre !== "all" && !splitList(m.genre).map((g) => g.toLowerCase()).includes(genre.toLowerCase())) return false;
        if (language !== "all" && !splitList(m.language).map((l) => l.toLowerCase()).includes(language.toLowerCase())) return false;
        if (quality !== "all" && m.quality !== quality) return false;
        return !q || m.title.toLowerCase().includes(q);
      }),
    [movies, q, genre, language, quality]
  );
  const filteredShows = useMemo(
    () =>
      shows.filter(
        (s) =>
          (genre === "all" || splitList(s.genres).map((g) => g.toLowerCase()).includes(genre.toLowerCase())) &&
          (!q || s.name.toLowerCase().includes(q))
      ),
    [shows, q, genre]
  );

  const hero: Movie | null = useMemo(() => {
    const pool = movies.filter((m) => m.backdrop_url);
    if (!pool.length) return null;
    return pool[Math.floor(Math.random() * pool.length)];
  }, [movies]);

  const genreRails = useMemo(() => {
    const map = new Map<string, Movie[]>();
    filteredMovies.forEach((m) => {
      const g = splitList(m.genre)[0] || "Other";
      if (!map.has(g)) map.set(g, []);
      map.get(g)!.push(m);
    });
    return Array.from(map.entries())
      .filter(([, v]) => v.length >= 3)
      .sort((a, b) => b[1].length - a[1].length)
      .slice(0, 6);
  }, [filteredMovies]);

  const continueWatching = useMemo(() => readProgress(), [progressTick]);

  const myMovies = useMemo(
    () => movies.filter((m) => mylist.has("movie", m.id)),
    [movies, mylist]
  );
  const myShows = useMemo(
    () => shows.filter((s) => mylist.has("show", s.id)),
    [shows, mylist]
  );

  const playMovie = (m: Movie, resumeFrom?: number) =>
    setPlaying({
      id: m.id,
      title: m.title,
      description: m.description,
      year: m.year,
      genre: m.genre,
      language: m.language,
      quality: m.quality,
      container: extOf(m.file_path),
      resumeFrom,
    });

  const playEpisodeList = (show: ShowDetail, startEp: Episode) => {
    const idx = show.episodes.findIndex((e) => e.id === startEp.id);
    const queue = show.episodes.slice(idx + 1).map((e) => ({ id: e.id, title: e.title }));
    const saved = readProgress().find((p) => p.id === startEp.id);
    setPlaying({
      id: startEp.id,
      title: startEp.title,
      description: show.overview,
      year: startEp.year,
      genre: show.genres,
      language: startEp.language,
      quality: startEp.quality,
      container: extOf(startEp.file_path),
      queue,
      resumeFrom: saved ? saved.time : undefined,
    });
  };

  const movieCard = (movie: Movie) => (
    <article key={movie.id} className="card" onClick={() => setDetailMovie(movie)}>
      <div className="poster">
        <PosterImage
          src={movie.poster_url}
          fallbackSrc={`/api/poster/${movie.id}`}
          alt={movie.title}
          letter={movie.title}
        />
        <div className="card-hover">
          <button
            className="circle-btn"
            title="Play"
            onClick={(e) => {
              e.stopPropagation();
              playMovie(movie);
            }}
          >
            <IPlay />
          </button>
          <button
            className="circle-btn"
            title={mylist.has("movie", movie.id) ? "Remove from My List" : "Add to My List"}
            onClick={(e) => {
              e.stopPropagation();
              mylist.toggle({ kind: "movie", id: movie.id });
            }}
          >
            {mylist.has("movie", movie.id) ? <ICheck /> : <IPlus />}
          </button>
        </div>
                    {movie.quality && <span className="quality-tag">{movie.quality}</span>}
                    {movie.subtitles.length > 0 && (
                      <span className="cc-tag" title={movie.subtitles.map((s) => s.lang).join(", ")}>CC</span>
                    )}
      </div>
      <div className="card-body">
        <h3 title={movie.title}>{movie.title}</h3>
        <div className="meta">
          {movie.year && <span>{movie.year}</span>}
          {movie.language && <span>{movie.language}</span>}
        </div>
      </div>
    </article>
  );

  const showCard = (show: Show) => (
    <article key={show.id} className="card" onClick={() => openShowDetail(show)}>
      <div className="poster">
        <PosterImage
          src={show.poster_url}
          fallbackSrc=""
          alt={show.name}
          letter={show.name}
        />
        {show.has_subs && (
          <span className="cc-tag" title="Subtitles available">CC</span>
        )}
        <div className="card-hover">
          <button
            className="circle-btn"
            title={mylist.has("show", show.id) ? "Remove from My List" : "Add to My List"}
            onClick={(e) => {
              e.stopPropagation();
              mylist.toggle({ kind: "show", id: show.id });
            }}
          >
            {mylist.has("show", show.id) ? <ICheck /> : <IPlus />}
          </button>
        </div>
      </div>
      <div className="card-body">
        <h3 title={show.name}>{show.name}</h3>
        <div className="meta">
          {show.year && <span>{show.year}</span>}
          <span>
            {show.seasons}S · {show.episode_count}E
          </span>
        </div>
      </div>
    </article>
  );

  return (
    <div className="nf">
      <nav className={scrolled ? "topbar solid" : "topbar"}>
        <span className="logo">
          Movie<span>Stream</span>
        </span>
        <div className="nav-links">
          {(
            [
              ["home", "Home"],
              ["movies", "Movies"],
              ["tv", "TV Shows"],
              ["mylist", "My List"],
              ["sessions", "Sessions"],
            ] as [View, string][]
          ).map(([v, label]) => (
            <button
              key={v}
              className={view === v ? "nav-link active" : "nav-link"}
              onClick={() => setView(v)}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          className="nav-search"
          type="search"
          placeholder="Titles…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <button
          className="btn"
          title="Log out"
          onClick={() => {
            fetch("/api/logout", { method: "POST" }).finally(() => {
              window.location.href = "/login";
            });
          }}
        >
          <ILogout />
        </button>
        <button className="btn" title="Rescan library" onClick={() => setAttempt((a) => a + 1)}>
          <IRefresh />
        </button>
      </nav>

      {view === "home" && hero && (
        <header
          className="billboard"
          style={{ backgroundImage: `url(${hero.backdrop_url})` }}
        >
          <div className="billboard-gradient" />
          <div className="billboard-content">
            <div className="billboard-kicker">M O V I E</div>
            <h1>{hero.title}</h1>
            <div className="hero-meta">
              {hero.year && <span>{hero.year}</span>}
              {hero.quality && <span className="badge-outline">{hero.quality}</span>}
              {hero.language && <span>{hero.language}</span>}
              {splitList(hero.genre).slice(0, 3).join(" · ")}
            </div>
            {hero.description && <p className="hero-desc">{hero.description}</p>}
            <div className="hero-actions">
              <button className="btn-play" onClick={() => playMovie(hero)}>
                <IPlay /> Play
              </button>
              <button className="btn-info" onClick={() => setDetailMovie(hero)}>
                <IInfo /> More Info
              </button>
              <button
                className="circle-btn big"
                title="My List"
                onClick={() => mylist.toggle({ kind: "movie", id: hero.id })}
              >
                {mylist.has("movie", hero.id) ? <ICheck /> : <IPlus />}
              </button>
            </div>
          </div>
          <div className="maturity">
            <span />
            {hero.quality || "HD"}
          </div>
        </header>
      )}

      <div className="app">
        {error && (
          <div className="error">
            <span>Failed to load: {error}</span>
            <button className="btn primary" onClick={() => setAttempt((a) => a + 1)}>
              Retry
            </button>
          </div>
        )}

        {(view === "movies" || view === "tv" || view === "home") && (
          <div className="controls slim">
            <select value={genre} onChange={(e) => setGenre(e.target.value)}>
              {genreOptions.map((g) => (
                <option key={g} value={g}>
                  {g === "all" ? "All genres" : g}
                </option>
              ))}
            </select>
            {(view === "movies" || view === "home") && (
              <>
                <select value={language} onChange={(e) => setLanguage(e.target.value)}>
                  {languageOptions.map((l) => (
                    <option key={l} value={l}>
                      {l === "all" ? "All languages" : l}
                    </option>
                  ))}
                </select>
                <select value={quality} onChange={(e) => setQuality(e.target.value)}>
                  {qualityOptions.map((x) => (
                    <option key={x} value={x}>
                      {x === "all" ? "All qualities" : x}
                    </option>
                  ))}
                </select>
              </>
            )}
            {(genre !== "all" || language !== "all" || quality !== "all" || q) && (
              <button
                className="btn"
                onClick={() => {
                  setGenre("all");
                  setLanguage("all");
                  setQuality("all");
                  setQuery("");
                }}
              >
                <IClose /> Clear
              </button>
            )}
          </div>
        )}

        {loading ? (
          <div className="status">Loading your library…</div>
        ) : view === "home" ? (
          <>
            {continueWatching.length > 0 && (
              <Rail title="Continue Watching">
                {continueWatching.map((p) => (
                  <ContinueCard
                    key={p.id}
                    item={p}
                    onPlay={() => {
                      if (p.kind === "movie") {
                        const m = movies.find((x) => x.id === p.id);
                        if (m) playMovie(m, p.time);
                      } else if (p.showId) {
                        openShowDetail({
                          id: p.showId,
                          name: p.showName ?? p.title,
                          year: null,
                          poster_url: "",
                          seasons: 0,
                          episode_count: 0,
                          overview: "",
                          genres: "",
                          has_subs: false,
                        });
                      }
                    }}
                    onDone={refreshProgress}
                  />
                ))}
              </Rail>
            )}
            <Rail title="Movies">{filteredMovies.map(movieCard)}</Rail>
            <Rail title="TV Shows">{filteredShows.map(showCard)}</Rail>
            {genreRails.map(([g, list]) => (
              <Rail key={g} title={`${g} Movies`}>
                {list.map(movieCard)}
              </Rail>
            ))}
          </>
        ) : view === "movies" ? (
          filteredMovies.length === 0 ? (
            <div className="status">No movies match your filters.</div>
          ) : (
            <div className="grid-page">{filteredMovies.map(movieCard)}</div>
          )
        ) : view === "tv" ? (
          filteredShows.length === 0 ? (
            <div className="status">No shows found.</div>
          ) : (
            <div className="grid-page">{filteredShows.map(showCard)}</div>
          )
        ) : view === "sessions" ? (
          <SessionsView />
        ) : myMovies.length === 0 && myShows.length === 0 ? (
          <div className="status">
            Your list is empty. Hover a title and hit + to save it here.
          </div>
        ) : (
          <>
            {myMovies.length > 0 && (
              <Rail title="My Movies">{myMovies.map(movieCard)}</Rail>
            )}
            {myShows.length > 0 && <Rail title="My Shows">{myShows.map(showCard)}</Rail>}
          </>
        )}
      </div>

      {detailMovie && (
        <DetailMovieModal
          movie={detailMovie}
          movies={movies}
          mylist={mylist}
          onClose={() => setDetailMovie(null)}
          onPlay={(m) => {
            playMovie(m);
            setDetailMovie(null);
          }}
          onSelect={setDetailMovie}
        />
      )}

      {openShow && (
        <DetailShowModal
          show={openShow}
          movies={movies}
          mylist={mylist}
          onClose={() => setOpenShow(null)}
          onPlayEpisode={(e) => playEpisodeList(openShow, e)}
          onSelectMovie={setDetailMovie}
        />
      )}

      {playing && (
        <PlayerModal
          playing={playing}
          onClose={() => {
            setPlaying(null);
            refreshProgress();
          }}
          onNext={(n) =>
            setPlaying({
              id: n.id,
              title: n.title,
              description: playing.description,
              year: playing.year,
              genre: playing.genre,
              language: playing.language,
              quality: playing.quality,
              container: playing.container,
              queue: playing.queue?.slice(1),
            })
          }
        />
      )}
    </div>
  );
}

/* ---------- detail modals ---------- */

function DetailMovieModal({
  movie,
  movies,
  mylist,
  onClose,
  onPlay,
  onSelect,
}: {
  movie: Movie;
  movies: Movie[];
  mylist: ReturnType<typeof useMyList>;
  onClose: () => void;
  onPlay: (m: Movie) => void;
  onSelect: (m: Movie) => void;
}) {
  const similar = useMemo(() => {
    const tags = new Set(splitList(movie.genre));
    if (!tags.size) return [];
    return movies
      .filter((m) => m.id !== movie.id && splitList(m.genre).some((g) => tags.has(g)))
      .slice(0, 6);
  }, [movie, movies]);
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal detail" onClick={(e) => e.stopPropagation()}>
        {(movie.backdrop_url || movie.poster_url) && (
          <div
            className="detail-hero"
            style={{
              backgroundImage: `url(${movie.backdrop_url || movie.poster_url})`,
            }}
          >
            <div className="detail-hero-gradient" />
            <h2>{movie.title}</h2>
          </div>
        )}
        <div className="detail-body">
          <div className="hero-actions">
            <button className="btn-play" onClick={() => onPlay(movie)}>
              <IPlay /> Play
            </button>
            <button
              className="circle-btn big"
              onClick={() => mylist.toggle({ kind: "movie", id: movie.id })}
            >
              {mylist.has("movie", movie.id) ? <ICheck /> : <IPlus />}
            </button>
          </div>
          <div className="detail-cols">
            <div>
              <div className="detail-meta">
                {movie.year && <span>{movie.year}</span>}
                {movie.quality && (
                  <span className="maturity-box">{movie.quality}</span>
                )}
                {movie.language && <span>{movie.language}</span>}
              </div>
              {movie.description && <p className="overview">{movie.description}</p>}
            </div>
            <div className="detail-side">
              {movie.genre && (
                <p>
                  <span className="dim">Genres:</span> {movie.genre}
                </p>
              )}
              {movie.language && (
                <p>
                  <span className="dim">Audio:</span> {movie.language}
                </p>
              )}
              <p>
                <span className="dim">Subtitles:</span>{" "}
                {movie.subtitles.length > 0
                  ? movie.subtitles.map((s) => s.lang).join(", ")
                  : "None found"}
              </p>
            </div>
          </div>
          {similar.length > 0 && (
            <>
              <h3 className="section-h">More Like This</h3>
              <div className="similar-grid">
                {similar.map((m) => (
                  <article key={m.id} className="card" onClick={() => onSelect(m)}>
                    <div className="poster">
                      <PosterImage
                        src={m.poster_url}
                        fallbackSrc={`/api/poster/${m.id}`}
                        alt={m.title}
                        letter={m.title}
                      />
                    </div>
                    <div className="card-body">
                      <h3 title={m.title}>{m.title}</h3>
                      <div className="meta">
                        {m.year && <span>{m.year}</span>}
                        {m.quality && <span>{m.quality}</span>}
                      </div>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function DetailShowModal({
  show,
  movies,
  mylist,
  onClose,
  onPlayEpisode,
  onSelectMovie,
}: {
  show: ShowDetail;
  movies: Movie[];
  mylist: ReturnType<typeof useMyList>;
  onClose: () => void;
  onPlayEpisode: (e: Episode) => void;
  onSelectMovie: (m: Movie) => void;
}) {
  const [season, setSeason] = useState<number | "all">("all");
  const seasons = useMemo(() => {
    const set = new Set<number>();
    show.episodes.forEach((e) => {
      if (e.season != null) set.add(e.season);
    });
    return Array.from(set).sort((a, b) => a - b);
  }, [show]);
  const eps = show.episodes.filter((e) => season === "all" || e.season === season);
  const tags = useMemo(() => new Set(splitList(show.genres)), [show]);
  const similar = useMemo(
    () =>
      movies
        .filter((m) => splitList(m.genre).some((g) => tags.has(g)))
        .slice(0, 6),
    [movies, tags]
  );
  return (
    <div className="overlay" onClick={onClose}>
      <div className="modal detail" onClick={(e) => e.stopPropagation()}>
        {show.poster_url && (
          <div
            className="detail-hero"
            style={{ backgroundImage: `url(${show.poster_url})` }}
          >
            <div className="detail-hero-gradient" />
            <h2>{show.name}</h2>
          </div>
        )}
        <div className="detail-body">
          <div className="hero-actions">
            {eps[0] && (
              <button className="btn-play" onClick={() => onPlayEpisode(eps[0])}>
                <IPlay /> Play S{String(eps[0].season ?? 1).padStart(2, "0")}E
                {String(eps[0].episode ?? 1).padStart(2, "0")}
              </button>
            )}
            <button
              className="circle-btn big"
              onClick={() => mylist.toggle({ kind: "show", id: show.id })}
            >
              {mylist.has("show", show.id) ? <ICheck /> : <IPlus />}
            </button>
          </div>
          <div className="detail-cols">
            <div>
              <div className="detail-meta">
                {show.year && <span>{show.year}</span>}
                <span>
                  {show.seasons} Season{show.seasons === 1 ? "" : "s"}
                </span>
              </div>
              {show.overview && <p className="overview">{show.overview}</p>}
            </div>
            <div className="detail-side">
              {show.genres && (
                <p>
                  <span className="dim">Genres:</span> {show.genres}
                </p>
              )}
            </div>
          </div>
          <div className="ep-head">
            <h3 className="section-h">Episodes</h3>
            {seasons.length > 1 && (
              <select value={season} onChange={(e) => setSeason(e.target.value === "all" ? "all" : Number(e.target.value))}>
                <option value="all">All seasons</option>
                {seasons.map((s) => (
                  <option key={s} value={s}>
                    Season {s}
                  </option>
                ))}
              </select>
            )}
          </div>
          <div className="episode-list rich">
            {eps.map((ep, i) => (
              <div key={ep.id} className="episode rich" onClick={() => onPlayEpisode(ep)}>
                <span className="ep-num">{ep.episode ?? i + 1}</span>
                <div className="ep-thumb">
                  <PosterImage
                    src=""
                    fallbackSrc={`/api/poster/${ep.id}`}
                    alt={ep.title}
                    letter={ep.title}
                  />
                  <span className="ep-play"><IPlay /></span>
                </div>
                <div className="ep-info">
                <div className="ep-title-row">
                  <span className="ep-title">{ep.title}</span>
                  {ep.subtitles.length > 0 && (
                    <span
                      className="badge"
                      title={ep.subtitles.map((s) => s.lang).join(", ")}
                    >
                      CC
                    </span>
                  )}
                  {ep.quality && <span className="badge">{ep.quality}</span>}
                </div>
                  <span className="ep-sub">
                    S{String(ep.season ?? 1).padStart(2, "0")}E
                    {String(ep.episode ?? i + 1).padStart(2, "0")}
                    {ep.language ? ` · ${ep.language}` : ""}
                  </span>
                </div>
              </div>
            ))}
          </div>
          {similar.length > 0 && (
            <>
              <h3 className="section-h">More Like This</h3>
              <div className="similar-grid">
                {similar.map((m) => (
                  <article
                    key={m.id}
                    className="card"
                    onClick={() => {
                      onClose();
                      onSelectMovie(m);
                    }}
                  >
                    <div className="poster">
                      <PosterImage
                        src={m.poster_url}
                        fallbackSrc={`/api/poster/${m.id}`}
                        alt={m.title}
                        letter={m.title}
                      />
                    </div>
                    <div className="card-body">
                      <h3 title={m.title}>{m.title}</h3>
                      <div className="meta">{m.year && <span>{m.year}</span>}</div>
                    </div>
                  </article>
                ))}
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/* ---------- sessions ---------- */

function relTime(ts: number): string {
  const s = Math.max(0, Math.floor(Date.now() / 1000) - ts);
  if (s < 60) return "just now";
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  const d = Math.floor(h / 24);
  if (d < 30) return `${d}d ago`;
  return new Date(ts * 1000).toLocaleDateString();
}

function SessionsView() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    api<Session[]>("/api/sessions")
      .then((s) => {
        setSessions(s);
        setLoading(false);
      })
      .catch((err: Error) => {
        setError(err.message);
        setLoading(false);
      });
  }, []);

  useEffect(load, [load]);

  const revoke = (id: string, current: boolean) => {
    fetch(`/api/sessions/${encodeURIComponent(id)}`, { method: "DELETE" })
      .then(() => {
        if (current) window.location.href = "/login";
        else load();
      })
      .catch((err: Error) => setError(err.message));
  };

  const logoutOthers = () => {
    apiMut<{ revoked: number }>("/api/sessions/logout-others", "POST")
      .then(load)
      .catch((err: Error) => setError(err.message));
  };

  const others = sessions.filter((s) => !s.current);

  return (
    <section className="sessions">
      <div className="sessions-head">
        <div>
          <h2 className="rail-title" style={{ margin: 0 }}>
            Active sessions
          </h2>
          <p className="dim" style={{ margin: "4px 0 0" }}>
            Every device signed in to your library. Sessions expire after 30 days of inactivity.
          </p>
        </div>
        {others.length > 0 && (
          <button className="btn danger" onClick={logoutOthers}>
            Sign out all other devices
          </button>
        )}
      </div>
      {error && <div className="error">Failed to load sessions: {error}</div>}
      {loading ? (
        <div className="status">Loading sessions…</div>
      ) : sessions.length === 0 ? (
        <div className="status">No active sessions.</div>
      ) : (
        <div className="session-list">
          {sessions.map((s) => (
            <div key={s.id} className={s.current ? "session-card current" : "session-card"}>
              <div className="session-main">
                <div className="session-title-row">
                  <span className="session-device" title={s.user_agent || "Unknown device"}>
                    {s.user_agent || "Unknown device"}
                  </span>
                  {s.current && <span className="badge-current">This device</span>}
                </div>
                <div className="session-meta">
                  {s.ip && <span>{s.ip}</span>}
                  <span>Last active {relTime(s.last_seen)}</span>
                  <span>Signed in {new Date(s.created_at * 1000).toLocaleString()}</span>
                </div>
              </div>
              <button
                className={s.current ? "btn" : "btn danger"}
                onClick={() => revoke(s.id, s.current)}
              >
                {s.current ? "Sign out" : "Revoke"}
              </button>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

/* ---------- continue watching ---------- */

function ContinueCard({
  item,
  onPlay,
  onDone,
}: {
  item: Progress;
  onPlay: () => void;
  onDone: () => void;
}) {
  const pct =
    item.duration > 0 ? Math.min(100, Math.round((item.time / item.duration) * 100)) : 0;
  return (
    <article className="card" onClick={onPlay}>
      <div className="poster landscape">
        <PosterImage
          src=""
          fallbackSrc={`/api/poster/${item.id}`}
          alt={item.title}
          letter={item.title}
        />
        <div className="progress-track">
          <div className="progress-fill" style={{ width: `${pct}%` }} />
        </div>
        <button
          className="remove-btn"
          title="Remove"
          onClick={(e) => {
            e.stopPropagation();
            clearProgress(item.id);
            onDone();
          }}
        >
          <IClose />
        </button>
      </div>
      <div className="card-body">
        <h3 title={item.title}>{item.title}</h3>
        <div className="meta">
          <span>{fmtTime(item.time)} left of {fmtTime(item.duration)}</span>
          {item.hasSubs && <span className="badge">CC</span>}
        </div>
      </div>
    </article>
  );
}

/* ---------- rails / cards ---------- */

function Rail({ title, children }: { title: string; children: React.ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const scroll = (dir: number) =>
    ref.current?.scrollBy({ left: dir * ref.current.clientWidth * 0.8, behavior: "smooth" });
  return (
    <section className="rail">
      <h2 className="rail-title">
        {title} <span className="rail-more"><IChevR /></span>
      </h2>
      <div className="rail-wrap">
        <button className="rail-arrow left" aria-label="Scroll left" onClick={() => scroll(-1)}>
          <IChevL />
        </button>
        <div className="rail-track" ref={ref}>
          {children}
        </div>
        <button className="rail-arrow right" aria-label="Scroll right" onClick={() => scroll(1)}>
          <IChevR />
        </button>
      </div>
    </section>
  );
}

/* ---------- custom player ---------- */

function PlayerModal({
  playing,
  onClose,
  onNext,
}: {
  playing: Playing;
  onClose: () => void;
  onNext: (n: { id: number; title: string }) => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const shellRef = useRef<HTMLDivElement>(null);
  const [subs, setSubs] = useState<Sub[]>([]);
  const [isPlaying, setIsPlaying] = useState(true);
  const [buffering, setBuffering] = useState(true);
  const [time, setTime] = useState(0);
  const [duration, setDuration] = useState(0);
  const [buffered, setBuffered] = useState(0);
  const [volume, setVolume] = useState(1);
  const [muted, setMuted] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [showControls, setShowControls] = useState(true);
  const [ccOpen, setCcOpen] = useState(false);
  const [activeSub, setActiveSub] = useState(-1);
  const [flash, setFlash] = useState<string | null>(null);
  const [introSkipped, setIntroSkipped] = useState(false);
  const [seekAnim, setSeekAnim] = useState<"-10" | "+10" | null>(null);
  const [remuxNote, setRemuxNote] = useState(false);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const clickTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    api<Sub[]>(`/api/subs/${playing.id}`)
      .then((t) => {
        setSubs(t);
        setActiveSub(t.length > 0 ? 0 : -1);
      })
      .catch(() => setSubs([]));
  }, [playing.id]);

  // Firefox can't play MKV in some builds: use the MP4 remux instead.
  const needsRemux =
    typeof navigator !== "undefined" &&
    /firefox|fxios/i.test(navigator.userAgent) &&
    (playing.container || "") === ".mkv";

  useEffect(() => {
    if (!needsRemux) return;
    api<{ cached: boolean; needed: boolean }>(`/api/remux/${playing.id}/status`)
      .then((s) => setRemuxNote(s.needed && !s.cached))
      .catch(() => {});
  }, [playing.id, needsRemux]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.muted = muted;
  }, [muted]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = speed;
  }, [speed]);

  const poke = useCallback(() => {
    setShowControls(true);
    if (hideTimer.current) clearTimeout(hideTimer.current);
    hideTimer.current = setTimeout(() => setShowControls(false), 2800);
  }, []);

  useEffect(() => {
    poke();
    return () => {
      if (hideTimer.current) clearTimeout(hideTimer.current);
      if (clickTimer.current) clearTimeout(clickTimer.current);
      if (flashTimer.current) clearTimeout(flashTimer.current);
    };
  }, [poke]);

  const showFlash = (icon: string) => {
    setFlash(icon);
    if (flashTimer.current) clearTimeout(flashTimer.current);
    flashTimer.current = setTimeout(() => setFlash(null), 500);
  };

  const toggle = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    if (v.paused) {
      v.play();
      showFlash("play");
    } else {
      v.pause();
      showFlash("pause");
    }
    poke();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [poke]);

  const seekBy = useCallback(
    (delta: number) => {
      const v = videoRef.current;
      if (!v) return;
      v.currentTime = Math.max(0, Math.min(v.duration || 0, v.currentTime + delta));
      setSeekAnim(delta < 0 ? "-10" : "+10");
      setTimeout(() => setSeekAnim(null), 500);
      poke();
    },
    [poke]
  );

  // Single click = play/pause, double click left/right = -10s/+10s.
  const onVideoClick = (e: React.MouseEvent) => {
    const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
    const x = (e.clientX - rect.left) / rect.width;
    if (clickTimer.current) {
      clearTimeout(clickTimer.current);
      clickTimer.current = null;
      if (x < 0.35) seekBy(-10);
      else if (x > 0.65) seekBy(10);
      else toggle();
      return;
    }
    clickTimer.current = setTimeout(() => {
      clickTimer.current = null;
      toggle();
    }, 260);
  };

  const skipIntro = useCallback(() => {
    const v = videoRef.current;
    if (!v) return;
    v.currentTime = Math.min(v.duration || 0, v.currentTime + 85);
    setIntroSkipped(true);
    showFlash("skip");
    poke();
  }, [poke]);

  const isEpisode = playing.queue !== undefined;
  const introVisible =
    isEpisode && !introSkipped && time < 300 && duration > 600;

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const v = videoRef.current;
      if (!v) return;
      const k = e.key.toLowerCase();
      if (e.key === " " || k === "k") {
        e.preventDefault();
        toggle();
      } else if (e.key === "ArrowRight") seekBy(10);
      else if (e.key === "ArrowLeft") seekBy(-10);
      else if (k === "f") {
        if (document.fullscreenElement) document.exitFullscreen();
        else shellRef.current?.requestFullscreen();
      } else if (k === "m") setMuted((m) => !m);
      else if (k === "s" && isEpisode && !introSkipped && time < 300) skipIntro();
      else if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle, onClose, seekBy, skipIntro, isEpisode, introSkipped, time]);

  const persist = () => {
    const v = videoRef.current;
    if (!v || !v.duration) return;
    saveProgress({
      id: playing.id,
      title: playing.title,
      kind: playing.queue ? "episode" : "movie",
      time: v.currentTime,
      duration: v.duration,
      updatedAt: Date.now(),
      hasSubs: subs.length > 0,
    });
  };

  const next = playing.queue?.[0];

  return (
    <div className={showControls ? "player-overlay" : "player-overlay hide-cursor"} onMouseMove={poke}>
      <div className="player-shell" ref={shellRef}>
        <video
          ref={videoRef}
          src={needsRemux ? `/api/remux/${playing.id}` : `/api/stream/${playing.id}`}
          autoPlay
          preload="auto"
          onClick={onVideoClick}
          onPlay={() => {
            setIsPlaying(true);
            setBuffering(false);
          }}
          onPause={() => {
            setIsPlaying(false);
            persist();
          }}
          onWaiting={() => setBuffering(true)}
          onPlaying={() => setBuffering(false)}
          onCanPlay={() => setBuffering(false)}
          onTimeUpdate={(e) => {
            const v = e.currentTarget;
            setTime(v.currentTime);
            try {
              if (v.buffered.length > 0) {
                setBuffered(v.buffered.end(v.buffered.length - 1));
              }
            } catch {
              /* ignore */
            }
          }}
          onLoadedMetadata={(e) => {
            const v = e.currentTarget;
            setDuration(v.duration);
            v.volume = volume;
            if (playing.resumeFrom && playing.resumeFrom < v.duration - 20) {
              v.currentTime = playing.resumeFrom;
            }
          }}
          onEnded={() => {
            clearProgress(playing.id);
            if (next) onNext(next);
          }}
        >
          {activeSub >= 0 && subs[activeSub] && (
            <track
              key={subs[activeSub].index}
              kind="subtitles"
              src={`/api/subs/${playing.id}/${subs[activeSub].index}`}
              srcLang={subs[activeSub].lang}
              label={subs[activeSub].lang}
              default
            />
          )}
        </video>

        {buffering && (
          <div className="buffer-spinner">
            <div className="spinner" />
          </div>
        )}
        {remuxNote && (
          <div className="remux-note">
            Preparing a Firefox-compatible copy — one-time wait, then it plays instantly every time.
          </div>
        )}
        {flash === "play" && <div className="flash"><IPlay /></div>}
        {flash === "pause" && <div className="flash"><IPause /></div>}
        {flash === "skip" && <div className="flash"><IFwd10 /></div>}
        {seekAnim && (
          <div className={seekAnim === "-10" ? "seek-anim left" : "seek-anim right"}>
            {seekAnim === "-10" ? <IRew10 /> : <IFwd10 />}
          </div>
        )}

        <div className={showControls ? "p-top show" : "p-top"}>
          <button className="p-back" aria-label="Back" onClick={onClose}>
            <IBack />
          </button>
          <span className="p-title">{playing.title}</span>
        </div>

        {introVisible && (
          <button className="skip-intro" onClick={skipIntro}>
            Skip Intro
          </button>
        )}

        <div className={showControls ? "p-bottom show" : "p-bottom"}>
          <Scrubber
            time={time}
            duration={duration}
            buffered={buffered}
            onSeek={(t) => {
              if (videoRef.current) videoRef.current.currentTime = t;
            }}
          />
          <div className="p-row">
            <button className="p-btn" aria-label={isPlaying ? "Pause" : "Play"} onClick={toggle}>
              {isPlaying ? <IPause /> : <IPlay />}
            </button>
            <button className="p-btn" aria-label="Back 10 seconds" onClick={() => seekBy(-10)}>
              <IRew10 />
            </button>
            <button className="p-btn" aria-label="Forward 10 seconds" onClick={() => seekBy(10)}>
              <IFwd10 />
            </button>
            <button className="p-btn" aria-label={muted ? "Unmute" : "Mute"} onClick={() => setMuted((m) => !m)}>
              {muted || volume === 0 ? <IMute /> : <IVol />}
            </button>
            <input
              className="vol"
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={muted ? 0 : volume}
              onChange={(e) => {
                const val = Number(e.target.value);
                setVolume(val);
                setMuted(val === 0);
                if (videoRef.current) {
                  videoRef.current.volume = val;
                  videoRef.current.muted = val === 0;
                }
              }}
            />
            <span className="p-time">
              {fmtTime(time)} / {fmtTime(duration)}
            </span>
            <span className="p-spacer" />
            <button
              className="p-text-btn"
              title="Playback speed"
              onClick={() => {
                const speeds = [1, 1.25, 1.5, 2];
                setSpeed(speeds[(speeds.indexOf(speed) + 1) % speeds.length]);
              }}
            >
              {speed}x
            </button>
            {next && (
              <button className="p-text-btn" onClick={() => onNext(next)}>
                Next Episode
              </button>
            )}
            {subs.length > 0 && (
              <div className="cc-wrap">
                <button
                  className={activeSub >= 0 ? "p-btn cc on" : "p-btn cc"}
                  onClick={() => setCcOpen((o) => !o)}
                >
                  CC
                </button>
                {ccOpen && (
                  <div className="cc-menu">
                    <button onClick={() => { setActiveSub(-1); setCcOpen(false); }}>
                      Off {activeSub === -1 && <ICheck />}
                    </button>
                    {subs.map((s) => (
                      <button
                        key={s.index}
                        onClick={() => { setActiveSub(s.index); setCcOpen(false); }}
                      >
                        {s.lang} {activeSub === s.index && <ICheck />}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
            <button
              className="p-btn"
              onClick={() => {
                if (document.fullscreenElement) document.exitFullscreen();
                else shellRef.current?.requestFullscreen();
              }}
            >
              <IFull />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function Scrubber({
  time,
  duration,
  buffered,
  onSeek,
}: {
  time: number;
  duration: number;
  buffered: number;
  onSeek: (t: number) => void;
}) {
  const trackRef = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const posToTime = (clientX: number) => {
    const el = trackRef.current;
    if (!el || !duration) return 0;
    const rect = el.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
    return ratio * duration;
  };

  const seekFromEvent = (e: React.MouseEvent) => onSeek(posToTime(e.clientX));

  const pct = duration > 0 ? (time / duration) * 100 : 0;
  const bufPct = duration > 0 ? Math.min(100, (buffered / duration) * 100) : 0;

  return (
    <div
      className="scrub-track"
      ref={trackRef}
      onMouseMove={(e) => setHover(posToTime(e.clientX))}
      onMouseLeave={() => setHover(null)}
      onMouseDown={seekFromEvent}
      onMouseUp={seekFromEvent}
    >
      <div className="scrub-buffered" style={{ width: `${bufPct}%` }} />
      <div className="scrub-played" style={{ width: `${pct}%` }} />
      <div className="scrub-knob" style={{ left: `${pct}%` }} />
      {hover !== null && (
        <div
          className="scrub-tip"
          style={{ left: `${duration > 0 ? (hover / duration) * 100 : 0}%` }}
        >
          {fmtTime(hover)}
        </div>
      )}
    </div>
  );
}


function PosterImage({
  src,
  fallbackSrc,
  alt,
  letter,
}: {
  src: string;
  fallbackSrc: string;
  alt: string;
  letter: string;
}) {
  const [stage, setStage] = useState(0);
  if (stage === 2 || (!src && !fallbackSrc)) {
    return (
      <span className="poster-fallback">{letter.charAt(0).toUpperCase() || "?"}</span>
    );
  }
  return (
    <img
      src={stage === 0 && src ? src : fallbackSrc}
      alt={alt}
      loading="lazy"
      referrerPolicy="no-referrer"
      onError={() => setStage((s) => s + 1)}
    />
  );
}
