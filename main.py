from io import BytesIO
from typing import Optional
from pathlib import Path
from urllib.parse import quote
import platform
import shutil
import socket
import sys
import difflib
import html
import re
import sqlite3
import unicodedata
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import colorgram
import requests
import uvicorn
import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from app_meta import APP_BRAND_NAME, APP_VERSION, BACKEND_HOST, BACKEND_PORT, UPDATE_CHANNEL
from app_paths import (
    DATA_DIR,
    FRONTEND_DIST,
    FRONTEND_INDEX,
    IS_FROZEN,
    LIBRARY_DB,
    LOCAL_FFMPEG_BINARY,
    ensure_runtime_directories,
)

app = FastAPI(title=APP_BRAND_NAME, description=f"{APP_BRAND_NAME} local music visualize and stream API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SearchRequest(BaseModel):
    query: str
    limit: int = 8


class SearchItem(BaseModel):
    title: str
    artist: str
    cover: str
    videoId: str
    query: str
    duration: Optional[int] = None
    durationText: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[SearchItem]


class VisualizeRequest(BaseModel):
    query: Optional[str] = None
    videoId: Optional[str] = None


class VisualizeResponse(BaseModel):
    title: str
    artist: str
    cover: str
    audioSrc: str
    audioExt: Optional[str] = None
    colors: list[str]
    theme: str
    videoId: Optional[str] = None
    query: Optional[str] = None


class LibraryTrack(BaseModel):
    key: str
    title: str
    artist: str
    cover: str = ""
    query: str = ""
    videoId: Optional[str] = None
    savedAt: Optional[str] = None
    playedAt: Optional[str] = None


class SearchHistoryEntry(BaseModel):
    query: str
    searchedAt: Optional[str] = None


class DownloadHistoryEntry(BaseModel):
    key: Optional[str] = None
    title: str
    artist: str
    filename: str = ""
    sourceUrl: str = ""
    downloadedAt: Optional[str] = None


class LibraryResponse(BaseModel):
    favorites: list[LibraryTrack]
    history: list[LibraryTrack]
    recentSearches: list[SearchHistoryEntry]
    recentDownloads: list[DownloadHistoryEntry]


class LyricsOffsetEntry(BaseModel):
    trackKey: str
    videoId: Optional[str] = None
    title: str = ""
    artist: str = ""
    offsetSeconds: float = 0
    updatedAt: Optional[str] = None


class SilentYtdlpLogger:
    def debug(self, _: str) -> None:
        pass

    def warning(self, _: str) -> None:
        pass

    def error(self, _: str) -> None:
        pass


def frontend_is_built() -> bool:
    return FRONTEND_INDEX.is_file()


def resolve_ffmpeg_binary() -> str | None:
    if LOCAL_FFMPEG_BINARY.is_file():
        return str(LOCAL_FFMPEG_BINARY)
    return shutil.which("ffmpeg")


def port_is_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_connection() -> sqlite3.Connection:
    ensure_runtime_directories()
    connection = sqlite3.connect(LIBRARY_DB)
    connection.row_factory = sqlite3.Row
    return connection


def init_library_db() -> None:
    with get_db_connection() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                track_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                cover TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                saved_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS play_history (
                track_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                cover TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                played_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS search_history (
                query TEXT PRIMARY KEY,
                searched_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS download_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_key TEXT,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                filename TEXT NOT NULL DEFAULT '',
                source_url TEXT NOT NULL DEFAULT '',
                downloaded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lyrics_offsets (
                track_key TEXT PRIMARY KEY,
                video_id TEXT,
                title TEXT NOT NULL DEFAULT '',
                artist TEXT NOT NULL DEFAULT '',
                offset_seconds REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_play_history_played_at
            ON play_history(played_at DESC);

            CREATE INDEX IF NOT EXISTS idx_search_history_searched_at
            ON search_history(searched_at DESC);

            CREATE INDEX IF NOT EXISTS idx_download_history_downloaded_at
            ON download_history(downloaded_at DESC);

            CREATE INDEX IF NOT EXISTS idx_lyrics_offsets_video_id
            ON lyrics_offsets(video_id);
            """
        )


def library_track_from_row(row: sqlite3.Row, timestamp_field: str) -> dict:
    return {
        "key": row["track_key"],
        "title": row["title"],
        "artist": row["artist"],
        "cover": row["cover"],
        "query": row["query"],
        "videoId": row["video_id"],
        "savedAt": row["saved_at"] if timestamp_field == "saved_at" else None,
        "playedAt": row["played_at"] if timestamp_field == "played_at" else None,
    }


def fetch_library_tracks(table_name: str, timestamp_field: str, limit: int) -> list[dict]:
    with get_db_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT track_key, title, artist, cover, query, video_id, {timestamp_field}
            FROM {table_name}
            ORDER BY {timestamp_field} DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [library_track_from_row(row, timestamp_field) for row in rows]


def fetch_recent_searches(limit: int = 12) -> list[dict]:
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT query, searched_at
            FROM search_history
            ORDER BY searched_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [{"query": row["query"], "searchedAt": row["searched_at"]} for row in rows]


def fetch_recent_downloads(limit: int = 12) -> list[dict]:
    with get_db_connection() as connection:
        rows = connection.execute(
            """
            SELECT track_key, title, artist, filename, source_url, downloaded_at
            FROM download_history
            ORDER BY downloaded_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "key": row["track_key"],
            "title": row["title"],
            "artist": row["artist"],
            "filename": row["filename"],
            "sourceUrl": row["source_url"],
            "downloadedAt": row["downloaded_at"],
        }
        for row in rows
    ]


def fetch_saved_lyrics_offset(track_key: str = "", video_id: str = "") -> float:
    query = None
    params: tuple[str, ...] = ()

    if track_key:
        query = """
            SELECT offset_seconds
            FROM lyrics_offsets
            WHERE track_key = ?
        """
        params = (track_key,)
    elif video_id:
        query = """
            SELECT offset_seconds
            FROM lyrics_offsets
            WHERE video_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """
        params = (video_id,)

    if not query:
        return 0.0

    with get_db_connection() as connection:
        row = connection.execute(query, params).fetchone()
    return float(row["offset_seconds"]) if row else 0.0


def upsert_lyrics_offset(entry: LyricsOffsetEntry) -> dict:
    track_key = (entry.trackKey or "").strip()
    if not track_key:
        raise HTTPException(status_code=422, detail="trackKey is required")

    updated_at = entry.updatedAt or utc_now_iso()

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO lyrics_offsets (track_key, video_id, title, artist, offset_seconds, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_key) DO UPDATE SET
                video_id = excluded.video_id,
                title = excluded.title,
                artist = excluded.artist,
                offset_seconds = excluded.offset_seconds,
                updated_at = excluded.updated_at
            """,
            (
                track_key,
                entry.videoId,
                entry.title,
                entry.artist,
                float(entry.offsetSeconds),
                updated_at,
            ),
        )

    return {
        "trackKey": track_key,
        "videoId": entry.videoId,
        "title": entry.title,
        "artist": entry.artist,
        "offsetSeconds": float(entry.offsetSeconds),
        "updatedAt": updated_at,
    }


def get_library_stats() -> dict:
    try:
        with get_db_connection() as connection:
            favorites_count = connection.execute("SELECT COUNT(*) FROM favorites").fetchone()[0]
            history_count = connection.execute("SELECT COUNT(*) FROM play_history").fetchone()[0]
            search_count = connection.execute("SELECT COUNT(*) FROM search_history").fetchone()[0]
            download_count = connection.execute("SELECT COUNT(*) FROM download_history").fetchone()[0]
            lyrics_offsets_count = connection.execute("SELECT COUNT(*) FROM lyrics_offsets").fetchone()[0]
        return {
            "favorites": favorites_count,
            "history": history_count,
            "searches": search_count,
            "downloads": download_count,
            "lyricsOffsets": lyrics_offsets_count,
        }
    except Exception:
        return {
            "favorites": 0,
            "history": 0,
            "searches": 0,
            "downloads": 0,
            "lyricsOffsets": 0,
        }


def get_system_check() -> dict:
    init_library_db()
    ffmpeg_binary = resolve_ffmpeg_binary()
    ffmpeg_available = ffmpeg_binary is not None
    node_available = shutil.which("node") is not None
    npm_available = shutil.which("npm") is not None
    frontend_built = frontend_is_built()
    dev_frontend_running = port_is_open(5173)
    library_stats = get_library_stats()

    issues = []
    if not ffmpeg_available:
        issues.append("未检测到 ffmpeg，部分音源可能无法正常解码。")
    if not frontend_built:
        issues.append("前端未构建，请运行 start-desktop.bat 或执行 npm run build。")
    if not node_available and not frontend_built:
        issues.append("未检测到 Node.js，当前无法构建前端页面。")

    return {
        "appVersion": APP_VERSION,
        "runtimeMode": "packaged" if IS_FROZEN else "source",
        "packaged": IS_FROZEN,
        "updateChannel": UPDATE_CHANNEL,
        "pythonVersion": sys.version.split()[0],
        "platform": platform.platform(),
        "ytDlpVersion": yt_dlp.version.__version__,
        "ffmpegAvailable": ffmpeg_available,
        "ffmpegBinary": ffmpeg_binary,
        "nodeAvailable": node_available,
        "npmAvailable": npm_available,
        "frontendBuilt": frontend_built,
        "frontendDist": str(FRONTEND_DIST),
        "devFrontendRunning": dev_frontend_running,
        "dataDir": str(DATA_DIR),
        "libraryDb": str(LIBRARY_DB),
        "libraryDbAvailable": LIBRARY_DB.is_file(),
        "libraryStats": library_stats,
        "recommendedEntry": "http://localhost:8010",
        "issues": issues,
    }


def get_dominant_colors(image_url: str, num_colors: int = 4) -> list[str]:
    try:
        if not image_url:
            return ["#333333", "#000000"]

        resp = requests.get(image_url, timeout=8)
        if resp.status_code != 200:
            return ["#333333", "#000000"]

        image = BytesIO(resp.content)
        colors = colorgram.extract(image, num_colors)
        hex_colors = [f"#{c.rgb.r:02x}{c.rgb.g:02x}{c.rgb.b:02x}" for c in colors]
        while len(hex_colors) < 2:
            hex_colors.append("#333333")
        return hex_colors
    except Exception as exc:
        print(f"Color extraction failed: {exc}")
        return ["#555555", "#1a1a1a", "#000000"]


def analyze_theme(title: str, _: list[str]) -> str:
    title_lower = (title or "").lower()
    if any(k in title_lower for k in ["night", "moon", "dark", "cyber", "neon"]):
        return "Neon Cyberpunk"
    if any(k in title_lower for k in ["sun", "summer", "beach", "happy", "day"]):
        return "Summer Nostalgia"
    if any(k in title_lower for k in ["rain", "blue", "sad", "tear", "ocean"]):
        return "Melancholic Blue"
    if any(k in title_lower for k in ["love", "heart", "kiss", "pink"]):
        return "Romantic Haze"
    return "AI Resonating..."


def format_duration(seconds: Optional[int]) -> Optional[str]:
    if seconds is None:
        return None
    try:
        total = int(seconds)
    except (TypeError, ValueError):
        return None
    return f"{total // 60:02d}:{total % 60:02d}"


def safe_download_filename(filename: str) -> str:
    cleaned = (filename or "music.m4a").replace('"', "").replace("/", "").replace("\\", "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned or "music.m4a"


def ascii_download_filename(filename: str) -> str:
    normalized = unicodedata.normalize("NFKD", filename or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_only = re.sub(r"[^A-Za-z0-9._ -]+", "", ascii_only).strip(" .")
    return ascii_only or "music"


def guess_download_media_type(filename: str, upstream_type: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix == ".m4a":
        return "audio/mp4"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".webm":
        return "audio/webm"
    if suffix == ".ogg":
        return "audio/ogg"
    if suffix == ".wav":
        return "audio/wav"
    return upstream_type or "application/octet-stream"


def get_ydl_opts(*, prefer_audio_only: bool = True, relaxed_clients: bool = False) -> dict:
    opts = {
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    if prefer_audio_only:
        opts["format"] = "bestaudio[ext=m4a]/bestaudio[ext=webm]/bestaudio/best"
    if not relaxed_clients:
        opts["extractor_args"] = {"youtube": {"player_client": ["android", "web"]}}
    ffmpeg_binary = resolve_ffmpeg_binary()
    if ffmpeg_binary:
        opts["ffmpeg_location"] = ffmpeg_binary
    return opts


def get_search_ydl_opts() -> dict:
    return get_ydl_opts(prefer_audio_only=False)


def get_media_ydl_opts() -> dict:
    return get_ydl_opts(prefer_audio_only=False, relaxed_clients=True)


def audio_format_score(fmt: dict) -> int:
    if not isinstance(fmt, dict) or not fmt.get("url"):
        return -10000

    acodec = fmt.get("acodec")
    vcodec = fmt.get("vcodec")
    if not acodec or acodec == "none":
        return -10000

    ext = (fmt.get("audio_ext") or fmt.get("ext") or "").lower()
    protocol = (fmt.get("protocol") or "").lower()
    score = 0

    if vcodec in (None, "none"):
        score += 420
    else:
        score += 40

    if ext == "m4a":
        score += 280
    elif ext == "webm":
        score += 190
    elif ext == "mp4":
        score += 150
    elif ext == "mp3":
        score += 120
    elif ext:
        score += 80

    if protocol in ("https", "http"):
        score += 60
    elif protocol.startswith("m3u8"):
        score -= 120
    elif protocol.startswith("dash"):
        score -= 40

    abr = fmt.get("abr") or fmt.get("tbr") or 0
    try:
        score += min(int(float(abr)), 256)
    except (TypeError, ValueError):
        pass

    if fmt.get("language") in ("", None):
        score += 5

    return score


def select_preferred_audio_format(video_info: dict) -> dict | None:
    formats = video_info.get("formats") or []
    if not formats:
        return None

    ranked_formats = sorted(
        formats,
        key=lambda fmt: (
            audio_format_score(fmt),
            float(fmt.get("abr") or 0),
            float(fmt.get("tbr") or 0),
        ),
        reverse=True,
    )
    return ranked_formats[0] if ranked_formats and audio_format_score(ranked_formats[0]) > -10000 else None


def extract_playback_info(video_id: str) -> dict:
    if not video_id:
        raise HTTPException(status_code=422, detail="videoId is required")

    ydl_opts = get_media_ydl_opts()
    ydl_opts.update({"skip_download": True, "logger": SilentYtdlpLogger()})

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)


def dedupe_entries(entries: list[dict], limit: int) -> list[dict]:
    unique_entries: list[dict] = []
    seen_video_ids: set[str] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue

        video_id = entry.get("id")
        if not video_id or video_id in seen_video_ids:
            continue

        seen_video_ids.add(video_id)
        unique_entries.append(entry)
        if len(unique_entries) >= limit:
            break

    return unique_entries


STRONG_NEGATIVE_SEARCH_HINTS = (
    "lyrics",
    "lyric",
    "歌詞",
    "歌词",
    "karaoke",
    "伴奏",
    "cover",
    "翻唱",
    "reaction",
    "remix",
    "nightcore",
    "sped up",
    "slowed",
    "reverb",
    "played by",
    "抖音",
    "加速",
    "加速版",
    "钢琴",
    "piano",
    "instrumental",
    "纯音乐",
    "純音樂",
)

MEDIUM_NEGATIVE_SEARCH_HINTS = (
    "live",
    "concert",
    "演唱会",
    "playlist",
    "full album",
    "mix",
    "1 hour",
    "loop",
)

POSITIVE_SEARCH_HINTS = (
    "official",
    "official video",
    "official audio",
    "music video",
    "audio",
    "topic",
    "vevo",
    "mv",
)


def normalize_search_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text or "").casefold()
    normalized = normalized.replace("&", " and ")
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = re.sub(r"_+", " ", normalized)
    return " ".join(normalized.split())


def text_contains_hint(text: str, hints: tuple[str, ...]) -> bool:
    normalized = normalize_search_text(text)
    return any(hint in normalized for hint in hints)


def token_hits(tokens: list[str], *texts: str) -> int:
    normalized_haystack = " ".join(normalize_search_text(text) for text in texts if text)
    return sum(1 for token in tokens if token and token in normalized_haystack)


def score_search_entry(query: str, entry: dict) -> int:
    title = entry.get("title") or ""
    uploader = entry.get("uploader") or entry.get("channel") or ""
    description = entry.get("description") or ""

    normalized_query = normalize_search_text(query)
    normalized_title = normalize_search_text(title)
    normalized_uploader = normalize_search_text(uploader)
    normalized_combined = normalize_search_text(f"{title} {uploader}")
    query_tokens = normalized_query.split()

    score = 0
    if normalized_title == normalized_query:
        score += 220
    elif normalized_query and normalized_query in normalized_title:
        score += 120

    if normalized_query and normalized_query in normalized_combined:
        score += 45

    score += int(difflib.SequenceMatcher(None, normalized_query, normalized_title).ratio() * 120)
    score += int(difflib.SequenceMatcher(None, normalized_query, normalized_combined).ratio() * 60)

    title_token_hits = token_hits(query_tokens, title)
    combined_token_hits = token_hits(query_tokens, title, uploader)
    uploader_token_hits = token_hits(query_tokens, uploader)

    score += title_token_hits * 16
    score += combined_token_hits * 12
    score += uploader_token_hits * 60

    if query_tokens and combined_token_hits == len(query_tokens):
        score += 35
    if uploader_token_hits and title_token_hits:
        score += 40

    if normalized_uploader and normalized_uploader in normalized_combined:
        score += 10

    if text_contains_hint(title, POSITIVE_SEARCH_HINTS) or text_contains_hint(uploader, POSITIVE_SEARCH_HINTS):
        score += 80
    if "topic" in normalized_uploader:
        score += 20

    if text_contains_hint(title, STRONG_NEGATIVE_SEARCH_HINTS):
        score -= 220
    if text_contains_hint(title, MEDIUM_NEGATIVE_SEARCH_HINTS):
        score -= 55
    if text_contains_hint(description, STRONG_NEGATIVE_SEARCH_HINTS):
        score -= 24
    if text_contains_hint(description, MEDIUM_NEGATIVE_SEARCH_HINTS):
        score -= 12
    if re.search(r"\b\d+(?:\.\d+)?x\b", normalized_title):
        score -= 120

    title_tokens = normalized_title.split()
    if len(title_tokens) > len(query_tokens) + 5 and not text_contains_hint(title, POSITIVE_SEARCH_HINTS):
        score -= min(50, (len(title_tokens) - len(query_tokens) - 5) * 8)

    duration = normalize_duration_seconds(entry.get("duration"))
    if duration is not None:
        if 90 <= duration <= 420:
            score += 10
        elif duration > 900:
            score -= 40

    return score


def search_youtube_entries(query: str, limit: int) -> list[dict]:
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        return []

    search_size = min(max(limit * 2, limit + 4), 30)
    ydl_opts = get_search_ydl_opts()
    ydl_opts.update(
        {
            "default_search": "ytsearch",
            "ignoreerrors": True,
            "logger": SilentYtdlpLogger(),
        }
    )

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(f"ytsearch{search_size}:{normalized_query}", download=False)
        entries = info.get("entries") or []

    unique_entries = dedupe_entries(entries, search_size)
    ranked_entries = sorted(
        unique_entries,
        key=lambda entry: (
            score_search_entry(normalized_query, entry),
            normalize_duration_seconds(entry.get("duration")) or 0,
        ),
        reverse=True,
    )
    return ranked_entries[:limit]


def get_dist_file(path_value: str) -> Path | None:
    if not frontend_is_built():
        return None

    candidate = (FRONTEND_DIST / path_value).resolve()
    dist_root = FRONTEND_DIST.resolve()

    try:
        candidate.relative_to(dist_root)
    except ValueError:
        return None

    return candidate if candidate.is_file() else None


def setup_page() -> str:
    return """
<!doctype html>
<html lang=\"zh-CN\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <title>NAS Local Setup</title>
  <style>
    body { font-family: Segoe UI, Arial, sans-serif; background:#0b1020; color:#e9efff; margin:0; }
    .wrap { max-width:760px; margin:48px auto; padding:24px; background:#121a31; border:1px solid #2a365c; border-radius:14px; }
    code { background:#0a0f1f; border:1px solid #2a365c; padding:2px 6px; border-radius:6px; color:#ffd58e; }
    h1 { margin-top:0; }
    li { margin:8px 0; }
  </style>
</head>
<body>
  <div class=\"wrap\">
    <h1>前端页面尚未构建</h1>
    <p>请在项目根目录运行：</p>
    <p><code>start-desktop.bat</code></p>
    <p>或手动执行：</p>
    <ul>
      <li><code>cd frontend</code></li>
      <li><code>npm install</code></li>
      <li><code>npm run build</code></li>
      <li><code>python main.py</code></li>
    </ul>
  </div>
</body>
</html>
"""


init_library_db()


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/system-check")
async def system_check():
    return get_system_check()


@app.get("/library", response_model=LibraryResponse)
async def get_library():
    return {
        "favorites": fetch_library_tracks("favorites", "saved_at", 100),
        "history": fetch_library_tracks("play_history", "played_at", 50),
        "recentSearches": fetch_recent_searches(12),
        "recentDownloads": fetch_recent_downloads(12),
    }


@app.post("/library/favorites", response_model=LibraryTrack)
async def upsert_favorite(item: LibraryTrack):
    payload = item.model_dump()
    saved_at = payload.get("savedAt") or utc_now_iso()

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO favorites (track_key, title, artist, cover, query, video_id, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_key) DO UPDATE SET
                title = excluded.title,
                artist = excluded.artist,
                cover = excluded.cover,
                query = excluded.query,
                video_id = excluded.video_id,
                saved_at = excluded.saved_at
            """,
            (
                payload["key"],
                payload["title"],
                payload["artist"],
                payload.get("cover") or "",
                payload.get("query") or "",
                payload.get("videoId"),
                saved_at,
            ),
        )

    payload["savedAt"] = saved_at
    payload["playedAt"] = None
    return payload


@app.delete("/library/favorites")
async def delete_favorite(key: str):
    with get_db_connection() as connection:
        connection.execute("DELETE FROM favorites WHERE track_key = ?", (key,))
    return {"ok": True, "key": key}


@app.post("/library/history", response_model=LibraryTrack)
async def upsert_history(item: LibraryTrack):
    payload = item.model_dump()
    played_at = payload.get("playedAt") or utc_now_iso()

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO play_history (track_key, title, artist, cover, query, video_id, played_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_key) DO UPDATE SET
                title = excluded.title,
                artist = excluded.artist,
                cover = excluded.cover,
                query = excluded.query,
                video_id = excluded.video_id,
                played_at = excluded.played_at
            """,
            (
                payload["key"],
                payload["title"],
                payload["artist"],
                payload.get("cover") or "",
                payload.get("query") or "",
                payload.get("videoId"),
                played_at,
            ),
        )

    payload["savedAt"] = None
    payload["playedAt"] = played_at
    return payload


@app.post("/library/searches", response_model=SearchHistoryEntry)
async def upsert_search_history(item: SearchHistoryEntry):
    query = (item.query or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="query is required")

    searched_at = item.searchedAt or utc_now_iso()

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO search_history (query, searched_at)
            VALUES (?, ?)
            ON CONFLICT(query) DO UPDATE SET
                searched_at = excluded.searched_at
            """,
            (query, searched_at),
        )

    return {"query": query, "searchedAt": searched_at}


@app.post("/library/downloads", response_model=DownloadHistoryEntry)
async def create_download_history(item: DownloadHistoryEntry):
    downloaded_at = item.downloadedAt or utc_now_iso()

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO download_history (track_key, title, artist, filename, source_url, downloaded_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                item.key,
                item.title,
                item.artist,
                item.filename,
                item.sourceUrl,
                downloaded_at,
            ),
        )

    return {
        "key": item.key,
        "title": item.title,
        "artist": item.artist,
        "filename": item.filename,
        "sourceUrl": item.sourceUrl,
        "downloadedAt": downloaded_at,
    }


@app.get("/lyrics-offset")
async def get_lyrics_offset(track_key: str = "", video_id: str = ""):
    return {
        "trackKey": track_key or None,
        "videoId": video_id or None,
        "offsetSeconds": fetch_saved_lyrics_offset(track_key=track_key, video_id=video_id),
    }


@app.post("/lyrics-offset", response_model=LyricsOffsetEntry)
async def save_lyrics_offset(item: LyricsOffsetEntry):
    return upsert_lyrics_offset(item)


@app.post("/search", response_model=SearchResponse)
async def search_tracks(req: SearchRequest):
    query = (req.query or "").strip()
    if not query:
        raise HTTPException(status_code=422, detail="Query is required")

    limit = max(1, min(int(req.limit), 15))

    try:
        entries = search_youtube_entries(query, limit)
        results: list[SearchItem] = []
        for entry in entries:
            if not entry:
                continue
            video_id = entry.get("id")
            title = entry.get("title") or "Unknown Title"
            artist = entry.get("uploader") or "Unknown Artist"
            cover = entry.get("thumbnail") or ""
            duration = entry.get("duration")
            if not video_id:
                continue
            query_text = f"{title} {artist}".strip()
            results.append(
                SearchItem(
                    title=title,
                    artist=artist,
                    cover=cover,
                    videoId=video_id,
                    query=query_text,
                    duration=duration,
                    durationText=format_duration(duration),
                )
            )

        return {"results": results}
    except Exception as exc:
        print(f"Search error: {exc}")
        raise HTTPException(status_code=500, detail="Search failed") from exc


def has_japanese(text: str) -> bool:
    return any('\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff' or '\uff66' <= c <= '\uff9f' for c in text)

def has_chinese(text: str) -> bool:
    return any('\u4e00' <= c <= '\u9fff' for c in text)

def score_lyrics(lyrics_text: str, target_lang: str) -> int:
    if not lyrics_text: return 0
    score = 0
    if target_lang == "ja" and has_japanese(lyrics_text): score += 100
    if target_lang == "zh" and has_chinese(lyrics_text): score += 100
    return score

def clean_text_for_lyrics(text):
    if not text:
        return ""
    import re
    cleaned = re.sub(r'[\(\[【《].*?[\)\]】》]', '', text)
    cleaned = re.sub(r'(?i)(official|music video|lyric video|lyrics|audio|mv|live|performance|remastered)', '', cleaned)
    cleaned = re.sub(r'(?i)(feat\.|ft\.).*$', '', cleaned)
    cleaned = re.sub(r'(?i)(vevo|topic|official)$', '', cleaned)
    cleaned = re.sub(r'[「」『』"“”]', ' ', cleaned)
    cleaned = " ".join(re.sub(r'[\_\|]+', ' ', cleaned).split())
    return cleaned.strip()

def extract_track_and_artist(raw_title, raw_artist):
    if " - " in raw_title:
        parts = raw_title.split(" - ", 1)
        return clean_text_for_lyrics(parts[1]), clean_text_for_lyrics(parts[0])
    import re
    if "「" in raw_title and "」" in raw_title:
        m = re.search(r'(.*?)「(.*?)」', raw_title)
        if m:
            return clean_text_for_lyrics(m.group(2)), clean_text_for_lyrics(m.group(1))
    return clean_text_for_lyrics(raw_title), clean_text_for_lyrics(raw_artist)


def normalize_duration_seconds(value: Optional[float]) -> Optional[int]:
    if value is None:
        return None
    try:
        duration = int(round(float(value)))
        return duration if duration > 0 else None
    except (TypeError, ValueError):
        return None


def get_result_duration_seconds(result: dict) -> Optional[int]:
    if not isinstance(result, dict):
        return None
    for key in ("trackLength", "duration", "length", "songLength"):
        if key in result:
            parsed = normalize_duration_seconds(result.get(key))
            if parsed is not None:
                return parsed
    return None


def duration_diff_seconds(result: dict, target_duration: Optional[int]) -> Optional[int]:
    if target_duration is None:
        return None
    result_duration = get_result_duration_seconds(result)
    if result_duration is None:
        return None
    return abs(result_duration - target_duration)


def get_target_language(track_name: str, artist_name: str = "") -> str:
    combined = f"{track_name} {artist_name}".strip()
    if has_japanese(combined):
        return "ja"
    if has_chinese(combined):
        return "zh"
    return "en"


def preferred_caption_languages(target_lang: str) -> list[str]:
    if target_lang == "ja":
        return ["ja", "ja-JP", "jpn", "en", "en-US", "en-GB"]
    if target_lang == "zh":
        return ["zh-Hans", "zh-CN", "zh", "zh-SG", "zh-Hant", "zh-TW", "en", "en-US", "en-GB"]
    return ["en", "en-US", "en-GB"]


def choose_caption_formats(caption_map: dict, preferred_langs: list[str]) -> tuple[str, list[dict]] | tuple[None, None]:
    if not caption_map:
        return None, None

    lowered_map = {str(key).lower(): key for key in caption_map.keys()}
    for preferred in preferred_langs:
        actual = lowered_map.get(preferred.lower())
        if actual:
            return actual, caption_map.get(actual) or []

    for preferred in preferred_langs:
        preferred_lower = preferred.lower()
        for actual in caption_map.keys():
            actual_lower = str(actual).lower()
            if actual_lower.startswith(preferred_lower) or preferred_lower.startswith(actual_lower):
                return actual, caption_map.get(actual) or []

    if len(caption_map) == 1:
        actual = next(iter(caption_map.keys()))
        return actual, caption_map.get(actual) or []

    return None, None


def choose_caption_format(formats: list[dict]) -> dict | None:
    if not formats:
        return None
    priorities = {"json3": 0, "srv3": 1, "srv1": 2, "vtt": 3}
    sorted_formats = sorted(formats, key=lambda item: priorities.get(item.get("ext"), 99))
    return sorted_formats[0] if sorted_formats else None


def normalize_caption_text(text: str) -> list[str]:
    cleaned = html.unescape(text or "").replace("\u00a0", " ")
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    lines = []
    for raw_line in cleaned.splitlines():
        line = " ".join(raw_line.split()).strip()
        if line:
            lines.append(line)
    return lines


def format_lrc_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    minutes = total_ms // 60000
    seconds_part = (total_ms % 60000) // 1000
    centiseconds = (total_ms % 1000) // 10
    return f"[{minutes:02d}:{seconds_part:02d}.{centiseconds:02d}]"


def build_lrc_payload(entries: list[tuple[float, str]], source: str) -> dict | None:
    deduped: list[tuple[float, str]] = []
    seen: set[tuple[int, str]] = set()
    plain_lines: list[str] = []

    for start_seconds, raw_text in entries:
        normalized_lines = normalize_caption_text(raw_text)
        for line in normalized_lines:
            key = (int(round(start_seconds * 100)), line)
            if key in seen:
                continue
            seen.add(key)
            deduped.append((start_seconds, line))
            plain_lines.append(line)

    if len(deduped) < 2:
        return None

    synced = "\n".join(f"{format_lrc_timestamp(start)}{line}" for start, line in deduped)
    plain = "\n".join(plain_lines)
    return {
        "syncedLyrics": synced,
        "plainLyrics": plain,
        "source": source,
    }


def parse_json3_captions(payload: dict) -> list[tuple[float, str]]:
    entries: list[tuple[float, str]] = []
    for event in payload.get("events") or []:
        start_ms = event.get("tStartMs")
        segments = event.get("segs") or []
        if start_ms is None or not segments:
            continue
        text = "".join(segment.get("utf8", "") for segment in segments)
        if text.strip():
            entries.append((float(start_ms) / 1000.0, text))
    return entries


def parse_xml_captions(payload: str) -> list[tuple[float, str]]:
    entries: list[tuple[float, str]] = []
    root = ET.fromstring(payload)
    for node in root.findall(".//p"):
        start_ms = node.attrib.get("t")
        if start_ms is None:
            continue
        text = "".join(node.itertext())
        if text.strip():
            entries.append((float(start_ms) / 1000.0, text))
    return entries


def fetch_youtube_captions(video_id: str, target_lang: str) -> dict | None:
    if not video_id:
        return None

    ydl_opts = get_media_ydl_opts()
    ydl_opts.update({"skip_download": True, "ignoreerrors": True, "logger": SilentYtdlpLogger()})

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
    except Exception as exc:
        print(f"YouTube captions info failed: {exc}")
        return None

    preferred_langs = preferred_caption_languages(target_lang)
    subtitle_lang, subtitle_formats = choose_caption_formats(info.get("subtitles") or {}, preferred_langs)
    auto_lang, auto_formats = choose_caption_formats(info.get("automatic_captions") or {}, preferred_langs)

    candidates = [
        ("youtube_subtitles", subtitle_lang, subtitle_formats),
        ("youtube_auto_captions", auto_lang, auto_formats),
    ]

    for source, lang, formats in candidates:
        if not formats:
            continue
        chosen = choose_caption_format(formats)
        if not chosen or not chosen.get("url"):
            continue
        try:
            response = requests.get(chosen["url"], timeout=15)
            response.raise_for_status()
            ext = chosen.get("ext")
            if ext == "json3":
                parsed_entries = parse_json3_captions(response.json())
            else:
                parsed_entries = parse_xml_captions(response.text)

            payload = build_lrc_payload(parsed_entries, source)
            if payload:
                payload["captionLanguage"] = lang
                return payload
        except Exception as exc:
            print(f"YouTube captions fetch failed ({source} {lang}): {exc}")

    return None


@app.get("/lyrics")
async def get_lyrics(
    track_name: str,
    artist_name: str = "",
    audio_duration: Optional[float] = None,
    video_id: str = "",
    track_key: str = "",
):
    if not track_name:
        raise HTTPException(status_code=422, detail="track_name is required")

    headers = {"User-Agent": "NSRL-Local-V3 (https://github.com/)"}
    clean_track, clean_artist = extract_track_and_artist(track_name, artist_name)
    target_duration = normalize_duration_seconds(audio_duration)
    target_lang = get_target_language(track_name, artist_name)
    saved_offset = fetch_saved_lyrics_offset(track_key=track_key, video_id=video_id)

    # 1. Exact Match
    url_get = f"https://lrclib.net/api/get?track_name={quote(clean_track)}&artist_name={quote(clean_artist)}"
    try:
        resp = requests.get(url_get, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            if data and (data.get("syncedLyrics") or data.get("plainLyrics")):
                if target_duration is not None:
                    exact_diff = duration_diff_seconds(data, target_duration)
                    if exact_diff is not None and exact_diff > 2:
                        data = None
                if data:
                    return {
                        "syncedLyrics": data.get("syncedLyrics"),
                        "plainLyrics": data.get("plainLyrics"),
                        "source": "lrclib",
                        "offsetSeconds": saved_offset,
                    }
    except Exception as exc:
        print(f"Exact match failed: {exc}")

    def is_valid_match(result_track, result_artist, target_track, target_artist):
        if not target_track:
            return False

        # Calculate similarity ratios
        track_sim = difflib.SequenceMatcher(None, target_track.lower(), (result_track or "").lower()).ratio()

        # If track similarity is very high, artist mismatch might be a cover, so accept it
        if track_sim > 0.8:
            return True

        # If track similarity is ok, check artist
        if track_sim > 0.5:
            if not target_artist:
                return True
            artist_sim = difflib.SequenceMatcher(None, target_artist.lower(), (result_artist or "").lower()).ratio()
            if artist_sim > 0.4:
                return True

        return False

    def match_priority(result: dict):
        diff = duration_diff_seconds(result, target_duration)
        close_duration_rank = 1
        if target_duration is not None:
            close_duration_rank = 0 if (diff is not None and diff <= 2) else 1

        missing_duration_rank = 1 if (target_duration is not None and diff is None) else 0
        duration_rank = diff if diff is not None else 9999
        lyrics_lang_rank = -score_lyrics(result.get("syncedLyrics") or result.get("plainLyrics") or "", target_lang)
        lyrics_sync_rank = 0 if result.get("syncedLyrics") else 1
        return (close_duration_rank, missing_duration_rank, duration_rank, lyrics_lang_rank, lyrics_sync_rank)

    def do_search(q, target_trk, target_art):
        try:
            r = requests.get(f"https://lrclib.net/api/search?q={quote(q)}", headers=headers, timeout=10)
            if r.status_code == 200:
                results = r.json()
                if results and isinstance(results, list):
                    # Filter out wildly wrong matches
                    valid_results = [
                        res for res in results
                        if is_valid_match(res.get("trackName"), res.get("artistName"), target_trk, target_art)
                    ]

                    if not valid_results:
                        return None

                    # If we can find close duration matches, force the shortlist to avoid wrong versions.
                    if target_duration is not None:
                        close_matches = [
                            res for res in valid_results
                            if (duration_diff_seconds(res, target_duration) is not None and duration_diff_seconds(res, target_duration) <= 2)
                        ]
                        if close_matches:
                            valid_results = close_matches

                    valid_results.sort(key=match_priority)
                    best_match = valid_results[0]
                    if best_match.get("syncedLyrics") or best_match.get("plainLyrics"):
                        return {
                            "syncedLyrics": best_match.get("syncedLyrics"),
                            "plainLyrics": best_match.get("plainLyrics"),
                            "source": "lrclib",
                            "offsetSeconds": saved_offset,
                        }
        except Exception:
            pass
        return None

    # 2. Search Fallback (Cleaned track + cleaned artist)
    q1 = f"{clean_track} {clean_artist}".strip()
    res = do_search(q1, clean_track, clean_artist)
    if res:
        return res

    # 3. Search Fallback 2 (Cleaned track ONLY)
    res2 = do_search(clean_track, clean_track, clean_artist)
    if res2:
        return res2

    # 4. Search Fallback 3 (Original cleaned track without split)
    orig_clean = clean_text_for_lyrics(track_name)
    res3 = do_search(orig_clean, orig_clean, artist_name)
    if res3:
        return res3

    youtube_caption_payload = fetch_youtube_captions(video_id, target_lang)
    if youtube_caption_payload:
        youtube_caption_payload["offsetSeconds"] = saved_offset
        return youtube_caption_payload

    return {
        "syncedLyrics": None,
        "plainLyrics": None,
        "source": None,
        "offsetSeconds": saved_offset,
    }


@app.post("/visualize", response_model=VisualizeResponse)
async def visualize(req: VisualizeRequest):
    if not req.videoId and not req.query:
        raise HTTPException(status_code=422, detail="query or videoId is required")

    request_label = req.videoId or req.query or ""
    print(f"Visualizing: {request_label}")

    try:
        candidates: list[dict] = []
        seen_video_ids: set[str] = set()

        if req.videoId:
            candidates.append({"id": req.videoId})
            seen_video_ids.add(req.videoId)

        if req.query:
            for match in search_youtube_entries(req.query or "", 6):
                video_id = match.get("id")
                if not video_id or video_id in seen_video_ids:
                    continue
                candidates.append(match)
                seen_video_ids.add(video_id)

        if not candidates:
            raise HTTPException(status_code=404, detail="Song not found")

        last_error = None
        for candidate in candidates:
            video_id = candidate.get("id")
            if not video_id:
                continue

            try:
                video_data = extract_playback_info(video_id)
                audio_format = select_preferred_audio_format(video_data)
                audio_url = audio_format.get("url") if audio_format else video_data.get("url")
                if not audio_url:
                    raise RuntimeError("missing playable stream URL")

                title = video_data.get("title") or candidate.get("title") or "Unknown Title"
                artist = video_data.get("uploader") or video_data.get("channel") or candidate.get("uploader") or "Unknown Artist"
                cover_url = video_data.get("thumbnail") or candidate.get("thumbnail") or ""
                query_text = req.query or f"{title} {artist}".strip()
                audio_ext = (
                    (audio_format or {}).get("audio_ext")
                    or (audio_format or {}).get("ext")
                    or "m4a"
                )
                if audio_ext == "none":
                    audio_ext = (audio_format or {}).get("ext") or "m4a"

                extracted_colors = get_dominant_colors(cover_url)
                theme = analyze_theme(title, extracted_colors)
                proxy_endpoint = f"/proxy-stream?url={quote(audio_url, safe='')}"

                return {
                    "title": title,
                    "artist": artist,
                    "cover": cover_url,
                    "audioSrc": proxy_endpoint,
                    "audioExt": audio_ext,
                    "colors": extracted_colors,
                    "theme": theme,
                    "videoId": video_id,
                    "query": query_text,
                }
            except Exception as candidate_error:
                last_error = candidate_error
                continue

        if last_error:
            raise HTTPException(status_code=502, detail="Unable to resolve a playable stream") from last_error
        raise HTTPException(status_code=404, detail="Song not found")

    except HTTPException:
        raise
    except Exception as exc:
        print(f"Visualize error: {exc}")
        raise HTTPException(status_code=500, detail="Visualize failed") from exc


@app.get("/proxy-stream")
async def proxy_stream(url: str, request: Request):
    try:
        print(f"Proxying stream: {url[:120]}")

        upstream_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }

        range_header = request.headers.get("range")
        if range_header:
            upstream_headers["Range"] = range_header

        upstream = requests.get(url, stream=True, headers=upstream_headers, timeout=25)
        upstream.raise_for_status()

        media_type = upstream.headers.get("content-type", "audio/mp4")
        response_headers = {}
        for header in ["content-length", "content-range", "cache-control", "expires", "accept-ranges"]:
            value = upstream.headers.get(header)
            if value:
                response_headers[header] = value

        if "accept-ranges" not in response_headers:
            response_headers["accept-ranges"] = "bytes"

        def iterfile():
            try:
                for chunk in upstream.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        yield chunk
            finally:
                upstream.close()

        return StreamingResponse(
            iterfile(),
            status_code=upstream.status_code,
            media_type=media_type,
            headers=response_headers,
        )
    except requests.RequestException as exc:
        print(f"Proxy request error: {exc}")
        raise HTTPException(status_code=502, detail="Upstream stream failed") from exc
    except Exception as exc:
        print(f"Proxy error: {exc}")
        raise HTTPException(status_code=500, detail="Stream failed") from exc


@app.get("/download")
async def download_track(url: str, filename: str = "music.mp3"):
    try:
        print(f"Downloading stream: {url[:120]}")
        upstream_headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        }
        upstream = requests.get(url, stream=True, headers=upstream_headers, timeout=60)
        upstream.raise_for_status()

        safe_filename = safe_download_filename(filename)
        ascii_filename = ascii_download_filename(safe_filename)
        encoded_filename = quote(safe_filename)
        response_headers = {
            "Content-Disposition": (
                f'attachment; filename="{ascii_filename}"; '
                f"filename*=UTF-8''{encoded_filename}"
            ),
            "Content-Type": guess_download_media_type(
                safe_filename,
                upstream.headers.get("content-type", "application/octet-stream"),
            ),
        }
        
        content_length = upstream.headers.get("content-length")
        if content_length:
            response_headers["Content-Length"] = content_length

        def iterfile():
            try:
                for chunk in upstream.iter_content(chunk_size=128 * 1024):
                    if chunk: yield chunk
            finally:
                upstream.close()

        return StreamingResponse(iterfile(), headers=response_headers)
    except Exception as exc:
        print(f"Download error: {exc}")
        raise HTTPException(status_code=500, detail="Download failed")

@app.get("/")
async def serve_index():
    if frontend_is_built():
        return FileResponse(FRONTEND_INDEX)
    return HTMLResponse(setup_page(), status_code=503)


@app.get("/{resource_path:path}")
async def serve_frontend_resource(resource_path: str):
    if not resource_path:
        if frontend_is_built():
            return FileResponse(FRONTEND_INDEX)
        return HTMLResponse(setup_page(), status_code=503)

    file_path = get_dist_file(resource_path)
    if file_path:
        return FileResponse(file_path)

    if frontend_is_built():
        return FileResponse(FRONTEND_INDEX)

    return HTMLResponse(setup_page(), status_code=503)


def run_backend_server() -> None:
    ensure_runtime_directories()
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT, reload=False)


if __name__ == "__main__":
    run_backend_server()

