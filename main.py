from io import BytesIO
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional
from pathlib import Path
from urllib.parse import quote
import base64
import os
import platform
import shutil
import socket
import sys
import difflib
import html
import json
import re
import sqlite3
import threading
import time
import unicodedata
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import colorgram
import requests
import uvicorn
import yt_dlp
from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

try:
    from ytmusicapi import YTMusic
except ImportError:  # pragma: no cover - optional dependency in local dev
    YTMusic = None

from app_meta import APP_BRAND_NAME, APP_VERSION, APP_VERSION_LABEL, BACKEND_HOST, BACKEND_PORT, UPDATE_CHANNEL
from app_paths import (
    DATA_DIR,
    FRONTEND_DIST,
    FRONTEND_INDEX,
    IS_FROZEN,
    LEGACY_SOURCE_LIBRARY_DB,
    LIBRARY_DB,
    LOCAL_FFMPEG_BINARY,
    ensure_runtime_directories,
)

app = FastAPI(title=APP_BRAND_NAME, description=f"{APP_BRAND_NAME} local music visualize and stream API")


class QQMusicResolveError(RuntimeError):
    def __init__(self, reason: str, detail: str = "", attempts: Optional[list[dict[str, Any]]] = None):
        self.reason = reason or QQMUSIC_FAILURE_UNKNOWN
        self.detail = detail or self.reason
        self.attempts = attempts or []
        super().__init__(self.detail)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_NO_CACHE_HEADERS = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}

STATIC_ASSET_PREFIXES = (
    "assets/",
    "apple-touch-icon",
    "favicon",
    "pwa-",
    "manifest",
    "robots.txt",
)


class SearchRequest(BaseModel):
    query: str
    limit: int = 8
    source: Optional[str] = None


class SearchItem(BaseModel):
    title: str
    artist: str
    cover: str
    videoId: str = ""
    query: str
    duration: Optional[int] = None
    durationText: Optional[str] = None
    provider: Optional[str] = None
    source: Optional[str] = None
    sourceId: Optional[str] = None
    trackKey: Optional[str] = None


class SearchResponse(BaseModel):
    results: list[SearchItem]
    provider: Optional[str] = None


class VisualizeRequest(BaseModel):
    query: Optional[str] = None
    videoId: Optional[str] = None
    source: Optional[str] = None
    sourceId: Optional[str] = None
    trackKey: Optional[str] = None
    sourceMode: Optional[str] = None


class VisualizeResponse(BaseModel):
    title: str
    artist: str
    cover: str
    audioSrc: str
    proxyAudioSrc: Optional[str] = None
    audioExt: Optional[str] = None
    colors: list[str]
    theme: str
    videoId: Optional[str] = None
    query: Optional[str] = None
    provider: Optional[str] = None
    streamMode: Optional[str] = None
    source: Optional[str] = None
    sourceId: Optional[str] = None
    trackKey: Optional[str] = None
    fallbackReason: Optional[str] = None
    fallbackTrace: Optional[list[dict[str, Any]]] = None


class LibraryTrack(BaseModel):
    key: str
    title: str
    artist: str
    cover: str = ""
    query: str = ""
    videoId: Optional[str] = None
    source: Optional[str] = None
    sourceId: Optional[str] = None
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
    savedPath: str = ""
    cover: str = ""
    query: str = ""
    videoId: Optional[str] = None
    source: Optional[str] = None
    sourceId: Optional[str] = None
    downloadedAt: Optional[str] = None


class LibraryResponse(BaseModel):
    favorites: list[LibraryTrack]
    history: list[LibraryTrack]
    recentSearches: list[SearchHistoryEntry]
    recentDownloads: list[DownloadHistoryEntry]


class RecommendationSection(BaseModel):
    id: str
    title: str
    subtitle: str = ""
    items: list[SearchItem]
    source: str = "mixed"


class RecommendationsResponse(BaseModel):
    mode: str
    generatedAt: str
    sections: list[RecommendationSection]


class LyricsOffsetEntry(BaseModel):
    trackKey: str
    videoId: Optional[str] = None
    source: Optional[str] = None
    sourceId: Optional[str] = None
    title: str = ""
    artist: str = ""
    offsetSeconds: float = 0
    updatedAt: Optional[str] = None


class AppSettingsResponse(BaseModel):
    downloadDirectory: str
    runtimeMode: str


class AppSettingsUpdateRequest(BaseModel):
    downloadDirectory: str = ""


class DownloadJobCreateRequest(BaseModel):
    key: Optional[str] = None
    title: str
    artist: str = ""
    filename: str
    sourceUrl: str


class DownloadJobResponse(BaseModel):
    id: str
    status: str
    progress: float = 0
    bytesReceived: int = 0
    totalBytes: int = 0
    filename: str = ""
    savedPath: str = ""
    sourceUrl: str = ""
    error: str = ""
    createdAt: str
    startedAt: Optional[str] = None
    completedAt: Optional[str] = None


class LocalLibraryItem(BaseModel):
    key: str
    title: str
    artist: str
    cover: str = ""
    filename: str
    savedPath: str
    sourceUrl: str = ""
    query: str = ""
    videoId: Optional[str] = None
    source: Optional[str] = None
    sourceId: Optional[str] = None
    downloadedAt: Optional[str] = None
    fileSize: int = 0
    offlineUrl: str
    duplicateGroup: str = ""
    duplicateCount: int = 1


class LocalLibraryResponse(BaseModel):
    downloadDirectory: str
    totalTracks: int
    duplicateGroups: int
    duplicateTracks: int
    totalSize: int
    items: list[LocalLibraryItem]


class FrontendErrorReport(BaseModel):
    eventType: str = "client-error"
    message: str = ""
    stack: str = ""
    componentStack: str = ""
    url: str = ""
    userAgent: str = ""
    timestamp: str = ""
    meta: dict[str, Any] = {}


class SilentYtdlpLogger:
    def debug(self, _: str) -> None:
        pass

    def warning(self, _: str) -> None:
        pass

    def error(self, _: str) -> None:
        pass


DEFAULT_VISUAL_COLORS = ["#49dcb1", "#08111d", "#02060c"]
SEARCH_CACHE_TTL_SECONDS = 180
SEARCH_NEGATIVE_CACHE_TTL_SECONDS = 35
VISUALIZE_CACHE_TTL_SECONDS = 75
VISUALIZE_NEGATIVE_CACHE_TTL_SECONDS = 20
PLAYBACK_INFO_CACHE_TTL_SECONDS = 120
PLAYBACK_INFO_NEGATIVE_CACHE_TTL_SECONDS = 25
LYRICS_CACHE_TTL_SECONDS = 60 * 60 * 6
LYRICS_NEGATIVE_CACHE_TTL_SECONDS = 60 * 8
COLOR_CACHE_TTL_SECONDS = 60 * 60 * 24
RECOMMENDATIONS_CACHE_TTL_SECONDS = 45
RECOMMENDATIONS_MIN_ITEMS = 4
RECOMMENDATION_SEED_LIMIT = 4
RECOMMENDATION_SEARCH_RESULTS_PER_SEED = 6
RECOMMENDATION_NETWORK_WORKERS = 4
CACHE_MISS = object()

CURATED_RECOMMENDATION_SEEDS = [
    {"title": "Yellow", "artist": "Coldplay", "query": "Yellow Coldplay"},
    {"title": "Blinding Lights", "artist": "The Weeknd", "query": "Blinding Lights The Weeknd"},
    {"title": "Take On Me", "artist": "a-ha", "query": "Take On Me a-ha"},
    {"title": "A Thousand Years", "artist": "Christina Perri", "query": "A Thousand Years Christina Perri"},
    {"title": "Nightcall", "artist": "Kavinsky", "query": "Nightcall Kavinsky"},
    {"title": "Viva La Vida", "artist": "Coldplay", "query": "Viva La Vida Coldplay"},
]


class TTLMemoryCache:
    def __init__(self) -> None:
        self._items: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str, default: Any = CACHE_MISS) -> Any:
        now = time.monotonic()
        with self._lock:
            entry = self._items.get(key)
            if not entry:
                return default
            expires_at, value = entry
            if expires_at <= now:
                self._items.pop(key, None)
                return default
            return value

    def set(self, key: str, value: Any, ttl_seconds: int) -> Any:
        with self._lock:
            self._items[key] = (time.monotonic() + max(1, int(ttl_seconds)), value)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


SEARCH_RESULTS_CACHE = TTLMemoryCache()
PLAYBACK_INFO_CACHE = TTLMemoryCache()
VISUALIZE_CACHE = TTLMemoryCache()
LYRICS_CACHE = TTLMemoryCache()
COLOR_CACHE = TTLMemoryCache()
RECOMMENDATIONS_CACHE = TTLMemoryCache()
COLOR_WARMUP_IN_FLIGHT: set[str] = set()
COLOR_WARMUP_LOCK = threading.Lock()
HTTP_SESSION_CACHE: dict[tuple[str, str, str], requests.Session] = {}
HTTP_SESSION_LOCK = threading.Lock()
YTMUSIC_CLIENT: Any = None
YTMUSIC_CLIENT_LOCK = threading.Lock()
APP_SETTING_DOWNLOAD_DIRECTORY = "download_directory"
DOWNLOAD_JOBS: dict[str, dict[str, Any]] = {}
DOWNLOAD_JOBS_LOCK = threading.Lock()
LOCAL_AUDIO_EXTENSIONS = {".m4a", ".mp3", ".webm", ".ogg", ".wav", ".flac", ".aac", ".opus"}
LIBRARY_MIGRATION_LOCK = threading.Lock()
LIBRARY_MIGRATION_DONE = False

YOUTUBE_DATA_API_KEY = os.getenv("YOUTUBE_DATA_API_KEY", "").strip()
NAS_SEARCH_PROVIDER = os.getenv("NAS_SEARCH_PROVIDER", "auto").strip().lower() or "auto"
NAS_ENABLE_YOUTUBE_FALLBACK = os.getenv("NAS_ENABLE_YOUTUBE_FALLBACK", "true").strip().lower() not in {"0", "false", "no", "off"}
NAS_METADATA_PROXY_MODE = os.getenv("NAS_METADATA_PROXY_MODE", "auto").strip().lower() or "auto"
NAS_MEDIA_TRANSPORT = os.getenv("NAS_MEDIA_TRANSPORT", "auto").strip().lower() or "auto"
NAS_CUSTOM_PROXY_URL = os.getenv("NAS_CUSTOM_PROXY_URL", "").strip()
NAS_SEARCH_REGION = (os.getenv("NAS_SEARCH_REGION", "CN").strip() or "CN").upper()
NAS_SEARCH_LANGUAGE = os.getenv("NAS_SEARCH_LANGUAGE", "zh-CN").strip() or "zh-CN"
DEFAULT_HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
SOURCE_QQMUSIC = "qqmusic"
SOURCE_YOUTUBE = "youtube"
SOURCE_LOCAL = "local"
QQMUSIC_FAILURE_EMPTY_PURL = "empty_purl"
QQMUSIC_FAILURE_PREVIEW_ONLY = "preview_only"
QQMUSIC_FAILURE_VIP_REQUIRED = "vip_required"
QQMUSIC_FAILURE_COPYRIGHT_RESTRICTED = "copyright_restricted"
QQMUSIC_FAILURE_HTTP_403 = "http_403"
QQMUSIC_FAILURE_STALE_VKEY = "stale_vkey"
QQMUSIC_FAILURE_NETWORK = "network_error"
QQMUSIC_FAILURE_TRACK_DETAIL = "missing_track_detail"
QQMUSIC_FAILURE_UNKNOWN = "unknown"
QQMUSIC_MUSICU_URL = "https://u.y.qq.com/cgi-bin/musicu.fcg"
QQMUSIC_AUDIO_FALLBACK_DOMAIN = "https://isure.stream.qqmusic.qq.com/"
QQMUSIC_COVER_URL = "https://y.gtimg.cn/music/photo_new/T002R500x500M000{album_mid}.jpg"
QQMUSIC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
YOUTUBE_SEARCH_PROVIDERS = {"youtube", "youtube_data_api", "ytmusicapi", "legacy_ytdlp"}
SUPPORTED_YTMUSIC_LANGUAGES = {
    "ar",
    "cs",
    "de",
    "en",
    "es",
    "fr",
    "hi",
    "it",
    "ja",
    "ko",
    "nl",
    "pt",
    "ru",
    "tr",
    "ur",
    "zh_CN",
    "zh_TW",
}


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


def perf_counter_ms() -> float:
    return time.perf_counter() * 1000.0


def log_timing(event: str, **payload: Any) -> None:
    normalized_parts = []
    for key, value in payload.items():
        if value is None:
            continue
        normalized_parts.append(f"{key}={value}")
    print(f"[NAS] {event} {' '.join(normalized_parts)}".strip())


def env_proxy_available() -> bool:
    return bool(os.getenv("HTTPS_PROXY") or os.getenv("https_proxy") or os.getenv("HTTP_PROXY") or os.getenv("http_proxy"))


def metadata_proxy_mode() -> str:
    mode = NAS_METADATA_PROXY_MODE
    if mode == "auto":
        if NAS_CUSTOM_PROXY_URL:
            return "custom"
        if env_proxy_available():
            return "system"
        return "direct"
    if mode == "custom" and not NAS_CUSTOM_PROXY_URL:
        return "direct"
    return mode


def custom_proxy_mapping() -> dict[str, str]:
    if not NAS_CUSTOM_PROXY_URL:
        return {}
    return {"http": NAS_CUSTOM_PROXY_URL, "https": NAS_CUSTOM_PROXY_URL}


def get_http_session(kind: str, mode: str) -> requests.Session:
    effective_mode = mode or "direct"
    cache_key = (kind, effective_mode, NAS_CUSTOM_PROXY_URL)
    with HTTP_SESSION_LOCK:
        cached = HTTP_SESSION_CACHE.get(cache_key)
        if cached:
            return cached

        session = requests.Session()
        session.headers.update(
            {
                "User-Agent": DEFAULT_HTTP_USER_AGENT,
                "Accept-Encoding": "gzip, deflate",
                "Accept-Language": NAS_SEARCH_LANGUAGE.replace("_", "-"),
            }
        )
        session.trust_env = effective_mode == "system"
        if effective_mode == "custom":
            session.trust_env = False
            session.proxies.update(custom_proxy_mapping())
        HTTP_SESSION_CACHE[cache_key] = session
        return session


def metadata_session() -> requests.Session:
    return get_http_session("metadata", metadata_proxy_mode())


def media_attempt_modes() -> list[str]:
    if NAS_MEDIA_TRANSPORT == "direct":
        return ["direct"]
    if NAS_MEDIA_TRANSPORT == "proxy":
        modes = []
        if NAS_CUSTOM_PROXY_URL:
            modes.append("custom")
        if env_proxy_available():
            modes.append("system")
        if not modes:
            modes.append("direct")
        return modes

    modes = ["direct"]
    if NAS_CUSTOM_PROXY_URL:
        modes.append("custom")
    if env_proxy_available():
        modes.append("system")
    return list(dict.fromkeys(modes))


def request_json(url: str, *, params: Optional[dict[str, Any]] = None, timeout: int = 12, kind: str = "metadata") -> Any:
    session = metadata_session() if kind == "metadata" else get_http_session(kind, "direct")
    response = session.get(url, params=params, timeout=timeout)
    response.raise_for_status()
    return response.json()


def request_text(url: str, *, timeout: int = 12, kind: str = "metadata") -> str:
    session = metadata_session() if kind == "metadata" else get_http_session(kind, "direct")
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    return response.text


def request_qqmusic_api(request_item: dict[str, Any], *, timeout: int = 12) -> dict[str, Any]:
    payload = {
        "comm": {
            "ct": 24,
            "cv": 0,
            "format": "json",
            "inCharset": "utf-8",
            "outCharset": "utf-8",
        },
        "req_0": request_item,
    }
    response = get_http_session("qqmusic", "direct").post(
        QQMUSIC_MUSICU_URL,
        json=payload,
        headers={
            "User-Agent": QQMUSIC_USER_AGENT,
            "Referer": "https://y.qq.com/",
            "Origin": "https://y.qq.com",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    data = response.json()
    item = data.get("req_0") or {}
    if item.get("code") not in (None, 0):
        raise requests.RequestException(f"QQ Music API error: {item.get('code')}")
    return item.get("data") or {}


def request_media_response(url: str, *, headers: Optional[dict[str, str]] = None, timeout: int = 25, stream: bool = True) -> tuple[requests.Response, str]:
    last_error: Exception | None = None
    for mode in media_attempt_modes():
        session = get_http_session("media", mode)
        try:
            response = session.get(url, stream=stream, headers=headers, timeout=timeout)
            response.raise_for_status()
            return response, mode
        except requests.RequestException as exc:
            last_error = exc
            log_timing("media_attempt_failed", mode=mode, error=exc.__class__.__name__)
            continue
    if last_error:
        raise last_error
    raise requests.RequestException("No media transport mode available")


def get_db_connection() -> sqlite3.Connection:
    maybe_migrate_legacy_library_db()
    ensure_runtime_directories()
    connection = sqlite3.connect(LIBRARY_DB)
    connection.row_factory = sqlite3.Row
    return connection


def sqlite_table_exists(connection: sqlite3.Connection, table_name: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def sqlite_table_columns(connection: sqlite3.Connection, table_name: str) -> set[str]:
    if not sqlite_table_exists(connection, table_name):
        return set()
    rows = connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row[1] if not isinstance(row, sqlite3.Row) else row["name"] for row in rows}


def read_sqlite_rows(connection: sqlite3.Connection, table_name: str, columns: dict[str, Any]) -> list[dict[str, Any]]:
    available_columns = sqlite_table_columns(connection, table_name)
    if not available_columns:
        return []

    selected_columns = [column for column in columns if column in available_columns]
    if not selected_columns:
        return []

    rows = connection.execute(
        f"SELECT {', '.join(selected_columns)} FROM {table_name}"
    ).fetchall()
    normalized_rows: list[dict[str, Any]] = []
    for row in rows:
        normalized = dict(columns)
        if isinstance(row, sqlite3.Row):
            for column in selected_columns:
                normalized[column] = row[column]
        else:
            for column, value in zip(selected_columns, row):
                normalized[column] = value
        normalized_rows.append(normalized)
    return normalized_rows


def timestamp_sort_key(value: str) -> str:
    return str(value or "")


def merge_library_databases(source_db: Path, target_db: Path) -> dict[str, int]:
    if not source_db.exists() or source_db.resolve() == target_db.resolve():
        return {"favorites": 0, "history": 0, "searches": 0, "downloads": 0, "lyricsOffsets": 0, "settings": 0}

    merged_counts = {"favorites": 0, "history": 0, "searches": 0, "downloads": 0, "lyricsOffsets": 0, "settings": 0}
    source_connection = sqlite3.connect(source_db)
    target_connection = sqlite3.connect(target_db)
    source_connection.row_factory = sqlite3.Row
    target_connection.row_factory = sqlite3.Row

    try:
        target_connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS favorites (
                track_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                cover TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                source TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                saved_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS play_history (
                track_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                cover TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                source TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
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
                saved_path TEXT NOT NULL DEFAULT '',
                cover TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                source TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                downloaded_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS lyrics_offsets (
                track_key TEXT PRIMARY KEY,
                video_id TEXT,
                source TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                artist TEXT NOT NULL DEFAULT '',
                offset_seconds REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );
            """
        )
        for table_name in ("favorites", "play_history", "download_history", "lyrics_offsets"):
            ensure_column_exists(target_connection, table_name, "source", "TEXT NOT NULL DEFAULT ''")
            ensure_column_exists(target_connection, table_name, "source_id", "TEXT NOT NULL DEFAULT ''")

        for table_name, key_column, timestamp_column, bucket_name, defaults in [
            (
                "favorites",
                "track_key",
                "saved_at",
                "favorites",
                {"track_key": "", "title": "", "artist": "", "cover": "", "query": "", "video_id": None, "source": "", "source_id": "", "saved_at": ""},
            ),
            (
                "play_history",
                "track_key",
                "played_at",
                "history",
                {"track_key": "", "title": "", "artist": "", "cover": "", "query": "", "video_id": None, "source": "", "source_id": "", "played_at": ""},
            ),
            (
                "search_history",
                "query",
                "searched_at",
                "searches",
                {"query": "", "searched_at": ""},
            ),
            (
                "lyrics_offsets",
                "track_key",
                "updated_at",
                "lyricsOffsets",
                {"track_key": "", "video_id": None, "source": "", "source_id": "", "title": "", "artist": "", "offset_seconds": 0.0, "updated_at": ""},
            ),
        ]:
            source_rows = read_sqlite_rows(source_connection, table_name, defaults)
            if not source_rows:
                continue

            existing_rows = {
                row[key_column]: row[timestamp_column]
                for row in read_sqlite_rows(target_connection, table_name, defaults)
                if row.get(key_column)
            }
            columns = list(defaults.keys())
            placeholders = ", ".join(["?"] * len(columns))
            updatable_columns = [column for column in columns if column != key_column]
            update_sql = ", ".join(f"{column} = excluded.{column}" for column in updatable_columns)

            for row in source_rows:
                key_value = row.get(key_column)
                if not key_value:
                    continue
                current_timestamp = existing_rows.get(key_value, "")
                if key_value in existing_rows and timestamp_sort_key(current_timestamp) >= timestamp_sort_key(row.get(timestamp_column, "")):
                    continue
                target_connection.execute(
                    f"""
                    INSERT INTO {table_name} ({', '.join(columns)})
                    VALUES ({placeholders})
                    ON CONFLICT({key_column}) DO UPDATE SET {update_sql}
                    """,
                    tuple(row[column] for column in columns),
                )
                existing_rows[key_value] = row.get(timestamp_column, "")
                merged_counts[bucket_name] += 1

        source_download_rows = read_sqlite_rows(
            source_connection,
            "download_history",
            {
                "track_key": "",
                "title": "",
                "artist": "",
                "filename": "",
                "source_url": "",
                "saved_path": "",
                "cover": "",
                "query": "",
                "video_id": None,
                "source": "",
                "source_id": "",
                "downloaded_at": "",
            },
        )
        if source_download_rows:
            existing_download_identities = {
                (
                    row["track_key"] or "",
                    row["filename"] or "",
                    row["saved_path"] or "",
                    row["downloaded_at"] or "",
                )
                for row in read_sqlite_rows(
                    target_connection,
                    "download_history",
                    {
                        "track_key": "",
                        "title": "",
                        "artist": "",
                        "filename": "",
                        "source_url": "",
                        "saved_path": "",
                        "cover": "",
                        "query": "",
                        "video_id": None,
                        "source": "",
                        "source_id": "",
                        "downloaded_at": "",
                    },
                )
            }
            for row in source_download_rows:
                identity = (
                    row["track_key"] or "",
                    row["filename"] or "",
                    row["saved_path"] or "",
                    row["downloaded_at"] or "",
                )
                if identity in existing_download_identities:
                    continue
                target_connection.execute(
                    """
                    INSERT INTO download_history (
                        track_key, title, artist, filename, source_url, saved_path, cover, query, video_id, source, source_id, downloaded_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["track_key"],
                        row["title"],
                        row["artist"],
                        row["filename"],
                        row["source_url"],
                        row["saved_path"],
                        row["cover"],
                        row["query"],
                        row["video_id"],
                        row["source"],
                        row["source_id"],
                        row["downloaded_at"],
                    ),
                )
                existing_download_identities.add(identity)
                merged_counts["downloads"] += 1

        source_settings_rows = read_sqlite_rows(
            source_connection,
            "app_settings",
            {"setting_key": "", "setting_value": "", "updated_at": ""},
        )
        if source_settings_rows:
            existing_settings = {
                row["setting_key"]: row
                for row in read_sqlite_rows(
                    target_connection,
                    "app_settings",
                    {"setting_key": "", "setting_value": "", "updated_at": ""},
                )
                if row.get("setting_key")
            }
            for row in source_settings_rows:
                key_value = row.get("setting_key")
                if not key_value:
                    continue
                current = existing_settings.get(key_value)
                if current and str(current.get("setting_value") or "").strip():
                    continue
                target_connection.execute(
                    """
                    INSERT INTO app_settings (setting_key, setting_value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(setting_key) DO UPDATE SET
                        setting_value = excluded.setting_value,
                        updated_at = excluded.updated_at
                    """,
                    (row["setting_key"], row["setting_value"], row["updated_at"] or utc_now_iso()),
                )
                existing_settings[key_value] = row
                merged_counts["settings"] += 1

        target_connection.commit()
    finally:
        source_connection.close()
        target_connection.close()

    return merged_counts


def maybe_migrate_legacy_library_db() -> None:
    global LIBRARY_MIGRATION_DONE
    if LIBRARY_MIGRATION_DONE:
        return

    with LIBRARY_MIGRATION_LOCK:
        if LIBRARY_MIGRATION_DONE:
            return

        ensure_runtime_directories()
        legacy_db = LEGACY_SOURCE_LIBRARY_DB

        try:
            same_location = legacy_db.resolve() == LIBRARY_DB.resolve()
        except OSError:
            same_location = legacy_db == LIBRARY_DB

        if not legacy_db.exists() or same_location:
            LIBRARY_MIGRATION_DONE = True
            return

        if not LIBRARY_DB.exists():
            shutil.copy2(legacy_db, LIBRARY_DB)
            log_timing("library_migrated", mode="copy", source=str(legacy_db), target=str(LIBRARY_DB))
            LIBRARY_MIGRATION_DONE = True
            return

        merged_counts = merge_library_databases(legacy_db, LIBRARY_DB)
        if any(merged_counts.values()):
            log_timing("library_migrated", mode="merge", source=str(legacy_db), target=str(LIBRARY_DB), **merged_counts)
        LIBRARY_MIGRATION_DONE = True


def ensure_column_exists(connection: sqlite3.Connection, table_name: str, column_name: str, definition_sql: str) -> None:
    existing_columns = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    if column_name not in existing_columns:
        connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition_sql}")


def default_download_directory() -> Path:
    downloads_root = Path.home() / "Downloads"
    return downloads_root / APP_BRAND_NAME


def get_app_setting(key: str, default: str = "") -> str:
    with get_db_connection() as connection:
        row = connection.execute(
            """
            SELECT setting_value
            FROM app_settings
            WHERE setting_key = ?
            """,
            (key,),
        ).fetchone()
    if not row:
        return default
    return str(row["setting_value"] or default)


def set_app_setting(key: str, value: str) -> str:
    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO app_settings (setting_key, setting_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(setting_key) DO UPDATE SET
                setting_value = excluded.setting_value,
                updated_at = excluded.updated_at
            """,
            (key, value, utc_now_iso()),
        )
    return value


def resolve_download_directory_path(preferred_value: str = "") -> Path:
    candidate = (preferred_value or get_app_setting(APP_SETTING_DOWNLOAD_DIRECTORY, "")).strip()
    if candidate:
        path = Path(candidate).expanduser()
    else:
        path = default_download_directory()
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def get_app_settings_payload() -> dict:
    return {
        "downloadDirectory": str(resolve_download_directory_path()),
        "runtimeMode": "packaged" if IS_FROZEN else "source",
    }


def open_path_in_file_manager(path_value: Path) -> None:
    target = Path(path_value)
    if not target.exists():
        raise HTTPException(status_code=404, detail="Path does not exist")
    if platform.system().lower().startswith("win"):
        os.startfile(str(target))  # type: ignore[attr-defined]
        return
    raise HTTPException(status_code=501, detail="Open folder is only available on Windows")


def make_unique_download_path(directory: Path, filename: str) -> Path:
    safe_name = safe_download_filename(filename)
    base_name = Path(safe_name).stem or "music"
    suffix = Path(safe_name).suffix or ".m4a"
    candidate = directory / f"{base_name}{suffix}"
    counter = 2
    while candidate.exists():
        candidate = directory / f"{base_name} ({counter}){suffix}"
        counter += 1
    return candidate


def snapshot_download_job(job_id: str) -> dict:
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Download job not found")
        return dict(job)


def update_download_job(job_id: str, **fields: Any) -> dict:
    with DOWNLOAD_JOBS_LOCK:
        job = DOWNLOAD_JOBS.get(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Download job not found")
        job.update(fields)
        return dict(job)


def run_download_job(job_id: str, source_url: str, filename: str) -> None:
    part_path: Path | None = None
    try:
        destination_dir = resolve_download_directory_path()
        destination_path = make_unique_download_path(destination_dir, filename)
        part_path = destination_path.with_suffix(destination_path.suffix + ".part")
        update_download_job(
            job_id,
            status="downloading",
            progress=0.0,
            bytesReceived=0,
            totalBytes=0,
            filename=destination_path.name,
            savedPath=str(destination_path),
            startedAt=utc_now_iso(),
        )

        upstream, transport_mode = request_media_response(
            source_url,
            timeout=60,
            stream=True,
        )
        total_bytes = int(upstream.headers.get("content-length") or 0)
        bytes_received = 0
        update_download_job(job_id, totalBytes=total_bytes)

        with open(part_path, "wb") as handle:
            for chunk in upstream.iter_content(chunk_size=1024 * 256):
                if not chunk:
                    continue
                handle.write(chunk)
                bytes_received += len(chunk)
                progress = (bytes_received / total_bytes) if total_bytes > 0 else 0.0
                update_download_job(
                    job_id,
                    bytesReceived=bytes_received,
                    totalBytes=total_bytes,
                    progress=min(0.99, progress) if total_bytes <= 0 else min(1.0, progress),
                )

        os.replace(part_path, destination_path)
        update_download_job(
            job_id,
            status="completed",
            progress=1.0,
            bytesReceived=bytes_received,
            totalBytes=max(total_bytes, bytes_received),
            filename=destination_path.name,
            savedPath=str(destination_path),
            completedAt=utc_now_iso(),
            error="",
            transportMode=transport_mode,
        )
    except Exception as exc:
        if part_path and part_path.exists():
            try:
                part_path.unlink()
            except OSError:
                pass
        update_download_job(
            job_id,
            status="failed",
            error=str(exc) or exc.__class__.__name__,
            completedAt=utc_now_iso(),
        )


def create_download_job(request: DownloadJobCreateRequest) -> dict:
    source_url = (request.sourceUrl or "").strip()
    if not source_url:
        raise HTTPException(status_code=422, detail="sourceUrl is required")
    safe_filename = safe_download_filename(request.filename)
    if not safe_filename:
        raise HTTPException(status_code=422, detail="filename is required")

    job_id = f"job_{uuid.uuid4().hex[:12]}"
    job_payload = {
        "id": job_id,
        "status": "queued",
        "progress": 0.0,
        "bytesReceived": 0,
        "totalBytes": 0,
        "filename": safe_filename,
        "savedPath": "",
        "sourceUrl": source_url,
        "error": "",
        "createdAt": utc_now_iso(),
        "startedAt": None,
        "completedAt": None,
        "title": request.title,
        "artist": request.artist,
        "key": request.key,
    }
    with DOWNLOAD_JOBS_LOCK:
        DOWNLOAD_JOBS[job_id] = job_payload

    worker = threading.Thread(
        target=run_download_job,
        args=(job_id, source_url, safe_filename),
        daemon=True,
        name=f"download-job-{job_id}",
    )
    worker.start()
    return dict(job_payload)


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
                source TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                saved_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS play_history (
                track_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL,
                cover TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                source TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
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
                saved_path TEXT NOT NULL DEFAULT '',
                cover TEXT NOT NULL DEFAULT '',
                query TEXT NOT NULL DEFAULT '',
                video_id TEXT,
                source TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                downloaded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS lyrics_offsets (
                track_key TEXT PRIMARY KEY,
                video_id TEXT,
                source TEXT NOT NULL DEFAULT '',
                source_id TEXT NOT NULL DEFAULT '',
                title TEXT NOT NULL DEFAULT '',
                artist TEXT NOT NULL DEFAULT '',
                offset_seconds REAL NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_settings (
                setting_key TEXT PRIMARY KEY,
                setting_value TEXT NOT NULL DEFAULT '',
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
        ensure_column_exists(connection, "download_history", "saved_path", "TEXT NOT NULL DEFAULT ''")
        ensure_column_exists(connection, "download_history", "cover", "TEXT NOT NULL DEFAULT ''")
        ensure_column_exists(connection, "download_history", "query", "TEXT NOT NULL DEFAULT ''")
        ensure_column_exists(connection, "download_history", "video_id", "TEXT")
        for table_name in ("favorites", "play_history", "download_history", "lyrics_offsets"):
            ensure_column_exists(connection, table_name, "source", "TEXT NOT NULL DEFAULT ''")
            ensure_column_exists(connection, table_name, "source_id", "TEXT NOT NULL DEFAULT ''")


def library_track_from_row(row: sqlite3.Row, timestamp_field: str) -> dict:
    source, source_id = legacy_source_fields(row["source"], row["source_id"], row["video_id"])
    key = stable_track_key(row["track_key"], source, source_id, row["video_id"], row["title"], row["artist"])
    return {
        "key": key,
        "title": row["title"],
        "artist": row["artist"],
        "cover": row["cover"],
        "query": row["query"],
        "videoId": row["video_id"],
        "source": source or None,
        "sourceId": source_id or None,
        "savedAt": row["saved_at"] if timestamp_field == "saved_at" else None,
        "playedAt": row["played_at"] if timestamp_field == "played_at" else None,
    }


def fetch_library_tracks(table_name: str, timestamp_field: str, limit: int) -> list[dict]:
    with get_db_connection() as connection:
        rows = connection.execute(
            f"""
            SELECT track_key, title, artist, cover, query, video_id, source, source_id, {timestamp_field}
            FROM {table_name}
            ORDER BY {timestamp_field} DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    items = [library_track_from_row(row, timestamp_field) for row in rows]
    deduped: list[dict] = []
    seen_keys: set[str] = set()
    for item in items:
        key = item.get("key") or ""
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        deduped.append(item)
    return deduped


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
            SELECT track_key, title, artist, filename, source_url, saved_path, cover, query, video_id, source, source_id, downloaded_at
            FROM download_history
            ORDER BY downloaded_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    items = []
    for row in rows:
        source, source_id = legacy_source_fields(row["source"], row["source_id"], row["video_id"])
        items.append({
            "key": stable_track_key(row["track_key"], source, source_id, row["video_id"], row["title"], row["artist"]),
            "title": row["title"],
            "artist": row["artist"],
            "filename": row["filename"],
            "sourceUrl": row["source_url"],
            "savedPath": row["saved_path"],
            "cover": row["cover"],
            "query": row["query"],
            "videoId": row["video_id"],
            "source": source or None,
            "sourceId": source_id or None,
            "downloadedAt": row["downloaded_at"],
        })
    return items


def fetch_download_history_rows(limit: int = 500) -> list[sqlite3.Row]:
    with get_db_connection() as connection:
        return connection.execute(
            """
            SELECT track_key, title, artist, filename, source_url, saved_path, cover, query, video_id, source, source_id, downloaded_at
            FROM download_history
            ORDER BY downloaded_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()


def infer_track_metadata_from_filename(filename: str) -> tuple[str, str]:
    stem = Path(filename or "").stem.strip()
    if " - " in stem:
        title, artist = stem.rsplit(" - ", 1)
        return title.strip(), artist.strip()
    return stem, ""


def path_is_relative_to(path_value: Path, base_path: Path) -> bool:
    try:
        path_value.resolve().relative_to(base_path.resolve())
        return True
    except Exception:
        return False


def allowed_local_media_paths() -> set[str]:
    allowed: set[str] = set()
    for row in fetch_download_history_rows(1000):
        saved_path = str(row["saved_path"] or "").strip()
        if not saved_path:
            continue
        try:
            allowed.add(str(Path(saved_path).resolve()))
        except OSError:
            allowed.add(str(Path(saved_path)))
    return allowed


def resolve_local_media_path(raw_path: str) -> Path:
    candidate = Path((raw_path or "").strip()).expanduser()
    if not str(candidate):
        raise HTTPException(status_code=422, detail="path is required")

    try:
        resolved = candidate.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Local file not found") from exc

    download_root = resolve_download_directory_path()
    allowed_paths = allowed_local_media_paths()
    if path_is_relative_to(resolved, download_root) or str(resolved) in allowed_paths:
        return resolved
    raise HTTPException(status_code=403, detail="Local file is outside the allowed media library")


def build_local_media_url(path_value: Path) -> str:
    return f"/local-media?path={quote(str(path_value))}"


def build_local_library_payload() -> dict:
    download_directory = resolve_download_directory_path()
    history_rows = fetch_download_history_rows(1000)

    metadata_by_path: dict[str, dict[str, Any]] = {}
    metadata_by_filename: dict[str, dict[str, Any]] = {}
    for row in history_rows:
        source, source_id = legacy_source_fields(row["source"], row["source_id"], row["video_id"])
        payload = {
            "key": stable_track_key(row["track_key"], source, source_id, row["video_id"], row["title"], row["artist"]),
            "title": row["title"] or "",
            "artist": row["artist"] or "",
            "filename": row["filename"] or "",
            "sourceUrl": row["source_url"] or "",
            "savedPath": row["saved_path"] or "",
            "cover": row["cover"] or "",
            "query": row["query"] or "",
            "videoId": row["video_id"],
            "source": source or None,
            "sourceId": source_id or None,
            "downloadedAt": row["downloaded_at"] or "",
        }
        saved_path = str(payload["savedPath"]).strip()
        if saved_path:
            try:
                metadata_by_path[str(Path(saved_path).resolve())] = payload
            except OSError:
                metadata_by_path[saved_path] = payload
        if payload["filename"] and payload["filename"] not in metadata_by_filename:
            metadata_by_filename[payload["filename"]] = payload

    files = [
        candidate
        for candidate in download_directory.rglob("*")
        if candidate.is_file() and candidate.suffix.lower() in LOCAL_AUDIO_EXTENSIONS
    ]

    items: list[dict[str, Any]] = []
    duplicate_buckets: dict[str, list[int]] = {}
    total_size = 0

    for file_path in files:
        try:
            resolved_path = file_path.resolve()
        except OSError:
            resolved_path = file_path

        stat = file_path.stat()
        total_size += stat.st_size

        metadata = metadata_by_path.get(str(resolved_path)) or metadata_by_filename.get(file_path.name) or {}
        inferred_title, inferred_artist = infer_track_metadata_from_filename(file_path.name)
        title = metadata.get("title") or inferred_title or file_path.stem
        artist = metadata.get("artist") or inferred_artist or "本地文件"
        query = metadata.get("query") or " ".join(part for part in [title, artist] if part and artist != "本地文件").strip()
        key = metadata.get("key") or f"local::{normalize_cache_text(str(resolved_path))}"
        duplicate_identity = metadata.get("sourceId") or metadata.get("videoId") or normalize_cache_text(f"{title}::{artist}")

        item = {
            "key": key,
            "title": title,
            "artist": artist,
            "cover": metadata.get("cover") or "",
            "filename": file_path.name,
            "savedPath": str(resolved_path),
            "sourceUrl": metadata.get("sourceUrl") or "",
            "query": query,
            "videoId": metadata.get("videoId"),
            "source": metadata.get("source"),
            "sourceId": metadata.get("sourceId"),
            "downloadedAt": metadata.get("downloadedAt") or datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            "fileSize": stat.st_size,
            "offlineUrl": build_local_media_url(resolved_path),
            "duplicateGroup": duplicate_identity,
            "duplicateCount": 1,
        }
        duplicate_buckets.setdefault(duplicate_identity, []).append(len(items))
        items.append(item)

    duplicate_groups = 0
    duplicate_tracks = 0
    for indexes in duplicate_buckets.values():
        if len(indexes) <= 1:
            continue
        duplicate_groups += 1
        duplicate_tracks += len(indexes)
        for index in indexes:
            items[index]["duplicateCount"] = len(indexes)

    items.sort(key=lambda item: item.get("downloadedAt") or "", reverse=True)

    return {
        "downloadDirectory": str(download_directory),
        "totalTracks": len(items),
        "duplicateGroups": duplicate_groups,
        "duplicateTracks": duplicate_tracks,
        "totalSize": total_size,
        "items": items,
    }


def append_frontend_error_report(report: FrontendErrorReport) -> Path:
    ensure_runtime_directories()
    log_path = frontend_error_log_path()
    payload = {
        "eventType": report.eventType or "client-error",
        "message": report.message or "",
        "stack": report.stack or "",
        "componentStack": report.componentStack or "",
        "url": report.url or "",
        "userAgent": report.userAgent or "",
        "timestamp": report.timestamp or utc_now_iso(),
        "meta": report.meta or {},
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
    return log_path


def fetch_saved_lyrics_offset(track_key: str = "", video_id: str = "", source: str = "", source_id: str = "") -> float:
    query = None
    params: tuple[str, ...] = ()
    resolved_source, resolved_source_id = legacy_source_fields(source, source_id, video_id)

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
    elif resolved_source and resolved_source_id:
        query = """
            SELECT offset_seconds
            FROM lyrics_offsets
            WHERE source = ? AND source_id = ?
            ORDER BY updated_at DESC
            LIMIT 1
        """
        params = (resolved_source, resolved_source_id)

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
    source, source_id = legacy_source_fields(entry.source, entry.sourceId, entry.videoId)
    track_key = stable_track_key(track_key, source, source_id, entry.videoId, entry.title, entry.artist)

    with get_db_connection() as connection:
        delete_duplicate_source_rows(connection, "lyrics_offsets", track_key, source, source_id, entry.videoId)
        connection.execute(
            """
            INSERT INTO lyrics_offsets (track_key, video_id, source, source_id, title, artist, offset_seconds, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_key) DO UPDATE SET
                video_id = excluded.video_id,
                source = excluded.source,
                source_id = excluded.source_id,
                title = excluded.title,
                artist = excluded.artist,
                offset_seconds = excluded.offset_seconds,
                updated_at = excluded.updated_at
            """,
            (
                track_key,
                entry.videoId,
                source,
                source_id,
                entry.title,
                entry.artist,
                float(entry.offsetSeconds),
                updated_at,
            ),
        )

    return {
        "trackKey": track_key,
        "videoId": entry.videoId,
        "source": source or None,
        "sourceId": source_id or None,
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
    proxy_available = env_proxy_available()
    frontend_error_log = frontend_error_log_path()

    issues = []
    if not ffmpeg_available:
        issues.append("未检测到 ffmpeg，部分音源可能无法正常解码。")
    if not frontend_built:
        issues.append("前端未构建，请运行 start-desktop.bat 或执行 npm run build。")
    if not node_available and not frontend_built:
        issues.append("未检测到 Node.js，当前无法构建前端页面。")

    return {
        "appVersion": APP_VERSION,
        "appVersionLabel": APP_VERSION_LABEL,
        "runtimeMode": "packaged" if IS_FROZEN else "source",
        "packaged": IS_FROZEN,
        "updateChannel": UPDATE_CHANNEL,
        "pythonVersion": sys.version.split()[0],
        "platform": platform.platform(),
        "ytDlpVersion": yt_dlp.version.__version__,
        "ytMusicApiAvailable": YTMusic is not None,
        "youtubeDataApiEnabled": bool(YOUTUBE_DATA_API_KEY),
        "youtubeFallbackEnabled": NAS_ENABLE_YOUTUBE_FALLBACK,
        "searchProvider": NAS_SEARCH_PROVIDER,
        "searchProviderOrder": search_provider_order(),
        "youtubeSearchProviderOrder": youtube_search_provider_order(),
        "metadataProxyMode": metadata_proxy_mode(),
        "envProxyAvailable": proxy_available,
        "mediaTransport": NAS_MEDIA_TRANSPORT,
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
        "frontendErrorLog": str(frontend_error_log),
        "frontendErrorLogExists": frontend_error_log.is_file(),
        "libraryStats": library_stats,
        "downloadDirectory": str(resolve_download_directory_path()),
        "recommendedEntry": "http://localhost:8010",
        "issues": issues,
    }


def frontend_error_log_path() -> Path:
    return DATA_DIR / "frontend-errors.log"


def diagnose_http_endpoint(
    endpoint_id: str,
    label: str,
    url: str,
    *,
    timeout: int = 6,
) -> dict[str, Any]:
    payload = {
        "id": endpoint_id,
        "label": label,
        "url": url,
        "ok": False,
        "statusCode": None,
        "error": "",
    }
    try:
        response = metadata_session().get(url, timeout=timeout)
        payload["statusCode"] = response.status_code
        payload["ok"] = response.ok
    except Exception as exc:
        payload["error"] = f"{exc.__class__.__name__}: {exc}"
    return payload


def build_search_diagnostics_payload(sample_query: str = "Coldplay Yellow") -> dict[str, Any]:
    checks = [
        diagnose_http_endpoint("qqmusic", "QQ 音乐", "https://y.qq.com"),
        diagnose_http_endpoint("youtube", "YouTube", "https://www.youtube.com"),
        diagnose_http_endpoint("ytmusic", "YT Music", "https://music.youtube.com"),
        diagnose_http_endpoint("lrclib", "LRCLIB", "https://lrclib.net/api/search?q=yellow"),
    ]
    started_ms = perf_counter_ms()
    search_probe = {
        "query": sample_query,
        "ok": False,
        "count": 0,
        "provider": "",
        "elapsedMs": 0,
        "error": "",
        "items": [],
    }

    try:
        results = search_catalog_entries(sample_query, 3)
        search_probe["count"] = len(results)
        search_probe["ok"] = bool(results)
        if results:
            search_probe["provider"] = str(results[0].get("source") or results[0].get("provider") or "")
            search_probe["items"] = [
                {
                    "title": entry.get("title") or "",
                    "artist": entry.get("uploader") or "",
                    "provider": entry.get("source") or entry.get("provider") or "",
                }
                for entry in results[:3]
            ]
    except Exception as exc:
        search_probe["error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        search_probe["elapsedMs"] = int(perf_counter_ms() - started_ms)

    proxy_mode = metadata_proxy_mode()
    proxy_available = env_proxy_available()
    youtube_reachable = any(check["id"] in {"youtube", "ytmusic"} and check["ok"] for check in checks)
    qqmusic_reachable = any(check["id"] == "qqmusic" and check["ok"] for check in checks)
    advice: list[str] = []

    if search_probe["ok"]:
        if search_probe["provider"] == SOURCE_QQMUSIC:
            advice.append("当前 QQ 音乐搜索链路可用，日常搜索不需要依赖 YouTube 代理。")
        elif proxy_mode == "direct" and not proxy_available:
            advice.append("当前环境下搜索可直连使用，并不是硬性要求开启代理。")
        else:
            advice.append("当前环境下搜索链路可用，是否需要代理主要取决于用户本机网络。")
    elif not qqmusic_reachable and not youtube_reachable:
        advice.append("当前环境下 QQ 音乐与 YouTube / YT Music 都不可达，搜索通常会失败；优先检查本机网络。")
    elif not qqmusic_reachable:
        advice.append("当前环境下 QQ 音乐不可达，国内音源搜索会失败；如启用 YouTube 兜底，仍可能需要代理。")
    elif not youtube_reachable and NAS_ENABLE_YOUTUBE_FALLBACK:
        advice.append("当前环境下 YouTube / YT Music 不可达，但 QQ 音乐仍可作为主搜索源使用。")
    else:
        advice.append("基础站点可达，但搜索探针仍失败，优先检查音源接口变化、系统代理或防火墙拦截。")

    if proxy_mode == "system":
        advice.append("当前应用正在跟随系统代理设置访问搜索源。")
    elif proxy_mode == "custom":
        advice.append("当前应用正在使用自定义代理地址访问搜索源。")
    else:
        advice.append("当前应用正在以直连方式访问搜索源。")

    if not YOUTUBE_DATA_API_KEY:
        advice.append("当前未配置 YouTube Data API Key，搜索主要依赖 YT Music / yt-dlp。")

    return {
        "checkedAt": utc_now_iso(),
        "appVersion": APP_VERSION,
        "appVersionLabel": APP_VERSION_LABEL,
        "metadataProxyMode": proxy_mode,
        "envProxyAvailable": proxy_available,
        "searchProvider": NAS_SEARCH_PROVIDER,
        "searchProviderOrder": search_provider_order(),
        "youtubeSearchProviderOrder": youtube_search_provider_order(),
        "youtubeFallbackEnabled": NAS_ENABLE_YOUTUBE_FALLBACK,
        "youtubeDataApiEnabled": bool(YOUTUBE_DATA_API_KEY),
        "checks": checks,
        "searchProbe": search_probe,
        "likelyNeedsProxy": not search_probe["ok"] and not qqmusic_reachable and not youtube_reachable and proxy_mode == "direct" and not proxy_available,
        "advice": advice,
    }


def normalize_cache_text(value: str) -> str:
    return " ".join((value or "").strip().casefold().split())


def normalize_source(value: Optional[str], *, video_id: str = "", source_id: str = "") -> str:
    normalized = (value or "").strip().lower()
    if normalized in {SOURCE_QQMUSIC, SOURCE_YOUTUBE, SOURCE_LOCAL}:
        return normalized
    if normalized in YOUTUBE_SEARCH_PROVIDERS or video_id:
        return SOURCE_YOUTUBE
    if source_id:
        return SOURCE_QQMUSIC
    return ""


def make_track_key(source: Optional[str], source_id: Optional[str], title: str = "", artist: str = "", video_id: Optional[str] = None) -> str:
    normalized_source = normalize_source(source, video_id=video_id or "", source_id=source_id or "")
    normalized_source_id = (source_id or video_id or "").strip()
    if normalized_source and normalized_source_id:
        return f"{normalized_source}:{normalized_source_id}"
    if video_id:
        return f"{SOURCE_YOUTUBE}:{video_id}"
    return f"{normalize_cache_text(title)}::{normalize_cache_text(artist)}"


def legacy_source_fields(source: Optional[str], source_id: Optional[str], video_id: Optional[str]) -> tuple[str, str]:
    normalized_source = normalize_source(source, video_id=video_id or "", source_id=source_id or "")
    normalized_source_id = (source_id or "").strip()
    if not normalized_source_id and normalized_source == SOURCE_YOUTUBE and video_id:
        normalized_source_id = video_id
    return normalized_source, normalized_source_id


def stable_track_key(
    stored_key: Optional[str],
    source: Optional[str],
    source_id: Optional[str],
    video_id: Optional[str],
    title: str = "",
    artist: str = "",
) -> str:
    resolved_source, resolved_source_id = legacy_source_fields(source, source_id, video_id)
    if resolved_source and resolved_source_id:
        return make_track_key(resolved_source, resolved_source_id, title, artist, video_id)
    return (stored_key or make_track_key(resolved_source, resolved_source_id, title, artist, video_id)).strip()


def parse_stable_track_key(track_key: str) -> tuple[str, str]:
    key = (track_key or "").strip()
    if ":" not in key:
        return "", ""
    source, source_id = key.split(":", 1)
    source = normalize_source(source)
    source_id = source_id.strip()
    if not source or not source_id:
        return "", ""
    return source, source_id


def delete_duplicate_source_rows(
    connection: sqlite3.Connection,
    table_name: str,
    track_key: str,
    source: str,
    source_id: str,
    video_id: Optional[str],
) -> None:
    if table_name not in {"favorites", "play_history", "lyrics_offsets"}:
        return

    clauses: list[str] = []
    params: list[Any] = [track_key]
    if source and source_id:
        clauses.append("(source = ? AND source_id = ?)")
        params.extend([source, source_id])
    if video_id:
        clauses.append("video_id = ?")
        params.append(video_id)
    elif source == SOURCE_YOUTUBE and source_id:
        clauses.append("video_id = ?")
        params.append(source_id)

    if not clauses:
        return

    connection.execute(
        f"DELETE FROM {table_name} WHERE track_key <> ? AND ({' OR '.join(clauses)})",
        tuple(params),
    )


def build_search_cache_key(query: str, limit: int, provider: str = "auto", region: str = "", language: str = "") -> str:
    return "::".join(
        [
            normalize_cache_text(query),
            str(limit),
            provider or "auto",
            (region or NAS_SEARCH_REGION).upper(),
            (language or NAS_SEARCH_LANGUAGE).lower(),
        ]
    )


def build_playback_cache_key(video_id: str) -> str:
    return f"playback::{(video_id or '').strip()}"


def build_visualize_cache_key(query: str = "", video_id: str = "", source: str = "", source_id: str = "") -> str:
    return "::".join(
        [
            "visualize",
            normalize_source(source, video_id=video_id, source_id=source_id) or "auto",
            normalize_cache_text(source_id or video_id),
            normalize_cache_text(query),
        ]
    )


def build_lyrics_cache_key(
    track_name: str,
    artist_name: str = "",
    audio_duration: Optional[float] = None,
    video_id: str = "",
    source: str = "",
    source_id: str = "",
) -> str:
    rounded_duration = normalize_duration_seconds(audio_duration) or 0
    return "::".join(
        [
            normalize_cache_text(track_name),
            normalize_cache_text(artist_name),
            str(rounded_duration),
            normalize_source(source, video_id=video_id, source_id=source_id) or "",
            normalize_cache_text(source_id),
            normalize_cache_text(video_id),
        ]
    )


def make_track_identity(video_id: Optional[str], title: str, artist: str, source: Optional[str] = None, source_id: Optional[str] = None) -> str:
    return make_track_key(source, source_id, title, artist, video_id)


def recommendation_cache_key() -> str:
    favorites = fetch_library_tracks("favorites", "saved_at", 12)
    history = fetch_library_tracks("play_history", "played_at", 12)
    searches = fetch_recent_searches(8)

    segments = []
    for item in favorites:
        segments.append(f"f:{item['key']}:{item.get('savedAt') or ''}")
    for item in history:
        segments.append(f"h:{item['key']}:{item.get('playedAt') or ''}")
    for item in searches:
        segments.append(f"s:{normalize_cache_text(item.get('query') or '')}:{item.get('searchedAt') or ''}")
    return "|".join(segments) or "empty"


def get_dominant_colors(image_url: str, num_colors: int = 4) -> list[str]:
    try:
        if not image_url:
            return DEFAULT_VISUAL_COLORS

        resp = metadata_session().get(image_url, timeout=8)
        if resp.status_code != 200:
            return DEFAULT_VISUAL_COLORS

        image = BytesIO(resp.content)
        colors = colorgram.extract(image, num_colors)
        hex_colors = [f"#{c.rgb.r:02x}{c.rgb.g:02x}{c.rgb.b:02x}" for c in colors]
        while len(hex_colors) < 2:
            hex_colors.append(DEFAULT_VISUAL_COLORS[min(len(hex_colors), len(DEFAULT_VISUAL_COLORS) - 1)])
        return hex_colors
    except Exception as exc:
        print(f"Color extraction failed: {exc}")
        return DEFAULT_VISUAL_COLORS


def get_cached_cover_colors(image_url: str) -> list[str] | None:
    if not image_url:
        return DEFAULT_VISUAL_COLORS

    cached = COLOR_CACHE.get(image_url)
    if cached is CACHE_MISS:
        return None
    return list(cached)


def warm_cover_colors(image_url: str) -> list[str]:
    if not image_url:
        return DEFAULT_VISUAL_COLORS

    cached = get_cached_cover_colors(image_url)
    if cached:
        return cached

    with COLOR_WARMUP_LOCK:
        if image_url in COLOR_WARMUP_IN_FLIGHT:
            return DEFAULT_VISUAL_COLORS
        COLOR_WARMUP_IN_FLIGHT.add(image_url)

    def worker() -> None:
        try:
            COLOR_CACHE.set(image_url, get_dominant_colors(image_url), COLOR_CACHE_TTL_SECONDS)
        finally:
            with COLOR_WARMUP_LOCK:
                COLOR_WARMUP_IN_FLIGHT.discard(image_url)

    threading.Thread(target=worker, name="nas-cover-colors", daemon=True).start()
    return DEFAULT_VISUAL_COLORS


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


def search_item_from_entry(entry: dict, fallback_query: str = "") -> SearchItem | None:
    if not isinstance(entry, dict):
        return None

    video_id = entry.get("id")
    source = normalize_source(entry.get("source"), video_id=video_id or "", source_id=entry.get("sourceId") or "")
    source_id = entry.get("sourceId") or (video_id if source == SOURCE_YOUTUBE else "")
    title = entry.get("title") or "Unknown Title"
    artist = entry.get("uploader") or entry.get("channel") or "Unknown Artist"
    if not source_id and not video_id:
        return None

    duration = normalize_duration_seconds(entry.get("duration"))
    return SearchItem(
        title=title,
        artist=artist,
        cover=entry.get("thumbnail") or "",
        videoId=video_id or "",
        query=fallback_query or f"{title} {artist}".strip(),
        duration=duration,
        durationText=format_duration(duration),
        provider=entry.get("provider"),
        source=source or None,
        sourceId=source_id or None,
        trackKey=entry.get("trackKey") or make_track_key(source, source_id, title, artist, video_id),
    )


def search_item_from_library_track(item: dict) -> SearchItem | None:
    if not isinstance(item, dict):
        return None
    title = item.get("title") or ""
    artist = item.get("artist") or ""
    if not title and not artist:
        return None
    return SearchItem(
        title=title or "Unknown Title",
        artist=artist or "Unknown Artist",
        cover=item.get("cover") or "",
        videoId=item.get("videoId") or "",
        query=item.get("query") or f"{title} {artist}".strip(),
        duration=None,
        durationText=None,
        provider="library",
        source=item.get("source") or None,
        sourceId=item.get("sourceId") or None,
        trackKey=stable_track_key(item.get("key"), item.get("source"), item.get("sourceId"), item.get("videoId"), title, artist),
    )


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


def get_fast_media_ydl_opts() -> dict:
    opts = get_ydl_opts(prefer_audio_only=True, relaxed_clients=True)
    extractor_args = opts.setdefault("extractor_args", {})
    youtube_args = extractor_args.setdefault("youtube", {})
    youtube_args["player_skip"] = ["configs", "webpage", "js", "initial_data"]
    youtube_args.setdefault("player_client", ["android", "tv_simply", "web"])
    return opts


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

    cache_key = build_playback_cache_key(video_id)
    cached = PLAYBACK_INFO_CACHE.get(cache_key)
    if cached is not CACHE_MISS:
        return cached

    started_ms = perf_counter_ms()
    info = None
    last_error: Exception | None = None

    for attempt_name, ydl_opts in (
        ("fast", get_fast_media_ydl_opts()),
        ("safe", get_media_ydl_opts()),
    ):
        try:
            ydl_opts.update({"skip_download": True, "logger": SilentYtdlpLogger()})
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(f"https://www.youtube.com/watch?v={video_id}", download=False)
            if info:
                log_timing("playback_info_resolved", video_id=video_id, resolve_ms=int(perf_counter_ms() - started_ms), attempt=attempt_name)
                break
        except Exception as exc:
            last_error = exc
            log_timing("playback_info_attempt_failed", video_id=video_id, attempt=attempt_name, error=exc.__class__.__name__)
            continue

    if not info and last_error:
        raise last_error

    ttl = PLAYBACK_INFO_CACHE_TTL_SECONDS if info else PLAYBACK_INFO_NEGATIVE_CACHE_TTL_SECONDS
    PLAYBACK_INFO_CACHE.set(cache_key, info, ttl)
    return info


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


def parse_duration_text(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return normalize_duration_seconds(value)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if re.fullmatch(r"\d+", text):
        return normalize_duration_seconds(text)
    parts = text.split(":")
    if not all(part.isdigit() for part in parts):
        return None
    try:
        seconds = 0
        for part in parts:
            seconds = seconds * 60 + int(part)
        return normalize_duration_seconds(seconds)
    except (TypeError, ValueError):
        return None


def parse_iso8601_duration(value: str) -> Optional[int]:
    if not value:
        return None
    match = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", value)
    if not match:
        return None
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    seconds = int(match.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def pick_thumbnail_url(thumbnails: Any) -> str:
    if isinstance(thumbnails, list):
        valid_items = [item for item in thumbnails if isinstance(item, dict) and item.get("url")]
        if not valid_items:
            return ""
        valid_items.sort(key=lambda item: (item.get("width") or 0, item.get("height") or 0), reverse=True)
        return str(valid_items[0].get("url") or "")
    if isinstance(thumbnails, dict):
        for key in ("maxres", "high", "medium", "default"):
            candidate = thumbnails.get(key) or {}
            if isinstance(candidate, dict) and candidate.get("url"):
                return str(candidate.get("url") or "")
    return ""


def normalize_ytmusic_language(value: str) -> str:
    normalized = (value or "").strip().replace("-", "_")
    if normalized in SUPPORTED_YTMUSIC_LANGUAGES:
        return normalized

    base_language = normalized.split("_", 1)[0].lower()
    if base_language == "zh":
        return "zh_CN"
    if base_language in SUPPORTED_YTMUSIC_LANGUAGES:
        return base_language
    return "en"


def looks_like_metric_label(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    return bool(re.search(r"(播放次数|次观看|views?\b|watching\b)", text, re.IGNORECASE))


def youtube_search_provider_order() -> list[str]:
    mode = NAS_SEARCH_PROVIDER
    if mode in {"auto", SOURCE_QQMUSIC, SOURCE_YOUTUBE}:
        providers: list[str] = []
        if YOUTUBE_DATA_API_KEY:
            providers.append("youtube_data_api")
        if YTMusic is not None:
            providers.append("ytmusicapi")
        providers.append("legacy_ytdlp")
        return providers
    return [mode]


def search_provider_order() -> list[str]:
    mode = NAS_SEARCH_PROVIDER
    if mode == "auto":
        providers = [SOURCE_QQMUSIC]
        if NAS_ENABLE_YOUTUBE_FALLBACK:
            providers.append(SOURCE_YOUTUBE)
        return providers
    if mode in YOUTUBE_SEARCH_PROVIDERS:
        return [SOURCE_YOUTUBE]
    if mode == SOURCE_YOUTUBE:
        return [SOURCE_YOUTUBE]
    if mode == SOURCE_QQMUSIC:
        providers = [SOURCE_QQMUSIC]
        if NAS_ENABLE_YOUTUBE_FALLBACK:
            providers.append(SOURCE_YOUTUBE)
        return providers
    return [SOURCE_QQMUSIC]


def normalize_catalog_entry(entry: dict, provider: str) -> dict:
    normalized = dict(entry)
    normalized["provider"] = provider
    if provider in YOUTUBE_SEARCH_PROVIDERS:
        normalized["source"] = SOURCE_YOUTUBE
        normalized["sourceId"] = normalized.get("sourceId") or normalized.get("id") or ""
    else:
        normalized["source"] = normalize_source(normalized.get("source") or provider, source_id=normalized.get("sourceId") or "")
    normalized["duration"] = normalize_duration_seconds(entry.get("duration"))
    normalized["trackKey"] = normalized.get("trackKey") or make_track_key(
        normalized.get("source"),
        normalized.get("sourceId"),
        normalized.get("title") or "",
        normalized.get("uploader") or normalized.get("channel") or "",
        normalized.get("id"),
    )
    return normalized


def qqmusic_search_id() -> str:
    base = 18014398509481984
    jitter = int(time.time() * 1000) % (24 * 60 * 60 * 1000)
    return str(base + (uuid.uuid4().int % 4194304) * 4294967296 + jitter)


def qqmusic_request_item(module: str, method: str, param: dict[str, Any]) -> dict[str, Any]:
    return {"module": module, "method": method, "param": param}


def qqmusic_artist_names(item: dict[str, Any]) -> str:
    names = []
    for singer in item.get("singer") or []:
        if isinstance(singer, dict):
            name = str(singer.get("name") or singer.get("title") or "").strip()
            if name:
                names.append(name)
    return ", ".join(names) or "Unknown Artist"


def qqmusic_album_cover(item: dict[str, Any]) -> str:
    album = item.get("album") or {}
    album_mid = str(album.get("mid") or album.get("pmid") or "").split("_", 1)[0]
    if not album_mid:
        return ""
    return QQMUSIC_COVER_URL.format(album_mid=album_mid)


def qqmusic_track_from_raw(item: dict[str, Any]) -> dict[str, Any] | None:
    song_mid = str(item.get("mid") or "").strip()
    if not song_mid:
        return None
    title = html.unescape(str(item.get("title") or item.get("name") or "Unknown Title"))
    title = re.sub(r"<[^>]+>", "", title).strip() or "Unknown Title"
    artist = qqmusic_artist_names(item)
    duration = normalize_duration_seconds(item.get("interval"))
    return {
        "id": "",
        "source": SOURCE_QQMUSIC,
        "sourceId": song_mid,
        "trackKey": make_track_key(SOURCE_QQMUSIC, song_mid, title, artist),
        "title": title,
        "uploader": artist,
        "channel": artist,
        "description": "QQ Music",
        "thumbnail": qqmusic_album_cover(item),
        "duration": duration,
        "provider": SOURCE_QQMUSIC,
        "qqMusicId": item.get("id"),
        "qqMediaMid": (item.get("file") or {}).get("media_mid") or song_mid,
        "qqFile": item.get("file") or {},
    }


def search_qqmusic_entries(query: str, limit: int) -> list[dict]:
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        return []

    search_size = min(max(limit * 2, limit + 4), 20)
    started_ms = perf_counter_ms()
    payload = request_qqmusic_api(
        qqmusic_request_item(
            "music.adaptor.SearchAdaptor",
            "do_search_v2",
            {
                "searchid": qqmusic_search_id(),
                "search_type": 100,
                "page_num": 15,
                "query": normalized_query,
                "page_id": 1,
                "highlight": 0,
                "grp": 1,
            },
        ),
        timeout=10,
    )
    raw_items = (((payload.get("body") or {}).get("item_song") or {}).get("items") or [])[:search_size]
    entries: list[dict] = []
    seen_source_ids: set[str] = set()
    for raw_item in raw_items:
        if not isinstance(raw_item, dict):
            continue
        entry = qqmusic_track_from_raw(raw_item)
        if not entry:
            continue
        source_id = entry.get("sourceId") or ""
        if source_id in seen_source_ids:
            continue
        seen_source_ids.add(source_id)
        entries.append(normalize_catalog_entry(entry, SOURCE_QQMUSIC))
        if len(entries) >= limit:
            break

    log_timing("search_provider", provider=SOURCE_QQMUSIC, search_ms=int(perf_counter_ms() - started_ms), count=len(entries))
    return entries


def fetch_qqmusic_track_detail(song_mid: str) -> dict[str, Any] | None:
    source_id = (song_mid or "").strip()
    if not source_id:
        return None
    payload = request_qqmusic_api(
        qqmusic_request_item(
            "music.trackInfo.UniformRuleCtrl",
            "CgiGetTrackInfo",
            {
                "types": [0],
                "modify_stamp": [0],
                "ctx": 0,
                "client": 1,
                "mids": [source_id],
            },
        ),
        timeout=10,
    )
    tracks = payload.get("tracks") or []
    if not tracks or not isinstance(tracks[0], dict):
        return None
    return qqmusic_track_from_raw(tracks[0])


def qqmusic_file_candidates(entry: dict[str, Any]) -> list[tuple[str, str, str]]:
    file_info = entry.get("qqFile") or {}
    candidates = [
        ("C400", ".m4a", "size_96aac"),
        ("M500", ".mp3", "size_128mp3"),
        ("C600", ".m4a", "size_192aac"),
        ("M800", ".mp3", "size_320mp3"),
    ]
    available = []
    for prefix, extension, size_key in candidates:
        try:
            size = int(file_info.get(size_key) or 0)
        except (TypeError, ValueError):
            size = 0
        if size > 0:
            available.append((prefix, extension, size_key))
    return available or candidates[:2]


def fetch_qqmusic_vkey_info(song_mid: str, media_mid: str, prefix: str, extension: str) -> dict[str, Any]:
    guid = uuid.uuid4().hex
    filename = f"{prefix}{media_mid}{extension}"
    payload = request_qqmusic_api(
        qqmusic_request_item(
            "music.vkey.GetVkey",
            "UrlGetVkey",
            {
                "uin": "0",
                "filename": [filename],
                "guid": guid,
                "songmid": [song_mid],
                "songtype": [0],
                "ctx": 0,
            },
        ),
        timeout=10,
    )
    info_items = payload.get("midurlinfo") or []
    if not info_items or not isinstance(info_items[0], dict):
        return {
            "url": "",
            "purl": "",
            "filename": filename,
            "prefix": prefix,
            "extension": extension,
            "reason": QQMUSIC_FAILURE_EMPTY_PURL,
            "message": "missing midurlinfo",
        }
    info = info_items[0]
    purl = str(info_items[0].get("purl") or "").strip()
    if not purl:
        return {
            "url": "",
            "purl": "",
            "filename": filename,
            "prefix": prefix,
            "extension": extension,
            "reason": classify_qqmusic_vkey_failure(info),
            "message": str(info.get("msg") or info.get("errmsg") or info.get("message") or ""),
            "result": info.get("result"),
        }
    if purl.startswith("http"):
        audio_url = purl
        domain = ""
    else:
        domains = [domain for domain in payload.get("sip") or [] if domain]
        domain = domains[0] if domains else QQMUSIC_AUDIO_FALLBACK_DOMAIN
        audio_url = f"{domain.rstrip('/')}/{purl.lstrip('/')}"
    return {
        "url": audio_url,
        "purl": purl,
        "filename": filename,
        "prefix": prefix,
        "extension": extension,
        "domain": domain,
        "reason": "",
        "message": str(info.get("msg") or info.get("errmsg") or info.get("message") or ""),
        "result": info.get("result"),
    }


def fetch_qqmusic_vkey(song_mid: str, media_mid: str, prefix: str, extension: str) -> str:
    return str(fetch_qqmusic_vkey_info(song_mid, media_mid, prefix, extension).get("url") or "")


def classify_qqmusic_vkey_failure(info: dict[str, Any]) -> str:
    text = " ".join(str(info.get(key) or "") for key in ("msg", "errmsg", "message", "tips", "result"))
    lowered = text.lower()
    if any(token in lowered for token in ("vip", "pay", "green", "premium")) or any(token in text for token in ("会员", "付费", "绿钻")):
        return QQMUSIC_FAILURE_VIP_REQUIRED
    if any(token in lowered for token in ("copyright", "right")) or any(token in text for token in ("版权", "无版权", "暂无版权")):
        return QQMUSIC_FAILURE_COPYRIGHT_RESTRICTED
    return QQMUSIC_FAILURE_EMPTY_PURL


def qqmusic_failure_label(reason: str) -> str:
    mapping = {
        QQMUSIC_FAILURE_EMPTY_PURL: "QQ 音乐未返回完整播放地址",
        QQMUSIC_FAILURE_PREVIEW_ONLY: "QQ 音乐仅返回试听片段",
        QQMUSIC_FAILURE_VIP_REQUIRED: "QQ 音乐可能需要会员权益",
        QQMUSIC_FAILURE_COPYRIGHT_RESTRICTED: "QQ 音乐版权受限",
        QQMUSIC_FAILURE_HTTP_403: "QQ 音乐播放地址拒绝访问",
        QQMUSIC_FAILURE_STALE_VKEY: "QQ 音乐播放地址已过期，已重试",
        QQMUSIC_FAILURE_NETWORK: "QQ 音乐播放地址网络探测失败",
        QQMUSIC_FAILURE_TRACK_DETAIL: "QQ 音乐曲目信息缺失",
    }
    return mapping.get(reason or "", "QQ 音乐解析失败")


def is_qqmusic_preview_url(url: str, purl: str = "") -> bool:
    value = f"{url or ''} {purl or ''}".lower()
    return bool(re.search(r"(^|[/_-])rs0[12]", value)) or "preview" in value or "试听" in value


def probe_playable_media_url_info(url: str) -> dict[str, Any]:
    if not url:
        return {"ok": False, "reason": QQMUSIC_FAILURE_EMPTY_PURL, "statusCode": None, "error": ""}
    upstream = None
    headers = media_request_headers(url)
    headers["Range"] = "bytes=0-1"
    try:
        upstream, _transport_mode = request_media_response(
            url,
            headers=headers,
            timeout=8,
            stream=True,
        )
        return {
            "ok": upstream.ok,
            "reason": "" if upstream.ok else QQMUSIC_FAILURE_UNKNOWN,
            "statusCode": upstream.status_code,
            "error": "",
        }
    except requests.HTTPError as exc:
        response = exc.response
        status_code = response.status_code if response is not None else None
        reason = QQMUSIC_FAILURE_HTTP_403 if status_code == 403 else QQMUSIC_FAILURE_NETWORK
        log_timing("media_probe_failed", provider=SOURCE_QQMUSIC, status=status_code or "", error=exc.__class__.__name__)
        return {"ok": False, "reason": reason, "statusCode": status_code, "error": exc.__class__.__name__}
    except Exception as exc:
        log_timing("media_probe_failed", provider=SOURCE_QQMUSIC, error=exc.__class__.__name__)
        return {"ok": False, "reason": QQMUSIC_FAILURE_NETWORK, "statusCode": None, "error": exc.__class__.__name__}
    finally:
        if upstream is not None:
            upstream.close()


def qqmusic_attempt_payload(
    *,
    source_id: str,
    title: str,
    artist: str,
    prefix: str = "",
    extension: str = "",
    reason: str = "",
    status_code: Optional[int] = None,
    message: str = "",
) -> dict[str, Any]:
    return {
        "source": SOURCE_QQMUSIC,
        "sourceId": source_id,
        "title": title,
        "artist": artist,
        "format": f"{prefix}{extension}".strip(),
        "reason": reason or QQMUSIC_FAILURE_UNKNOWN,
        "message": message or qqmusic_failure_label(reason),
        "statusCode": status_code,
    }


def dominant_qqmusic_failure(attempts: list[dict[str, Any]]) -> str:
    reasons = [str(item.get("reason") or "") for item in attempts if item.get("reason")]
    for preferred in (
        QQMUSIC_FAILURE_VIP_REQUIRED,
        QQMUSIC_FAILURE_COPYRIGHT_RESTRICTED,
        QQMUSIC_FAILURE_PREVIEW_ONLY,
        QQMUSIC_FAILURE_HTTP_403,
        QQMUSIC_FAILURE_EMPTY_PURL,
        QQMUSIC_FAILURE_NETWORK,
    ):
        if preferred in reasons:
            return preferred
    return reasons[-1] if reasons else QQMUSIC_FAILURE_UNKNOWN


def media_request_headers(url: str) -> dict[str, str]:
    headers = {"User-Agent": DEFAULT_HTTP_USER_AGENT}
    lowered_url = (url or "").lower()
    if "qqmusic.qq.com" in lowered_url or "music.tc.qq.com" in lowered_url:
        headers["Referer"] = "https://y.qq.com/"
        headers["Origin"] = "https://y.qq.com"
    return headers


def probe_playable_media_url(url: str) -> bool:
    return bool(probe_playable_media_url_info(url).get("ok"))


def resolve_qqmusic_entry(source_id: str, candidate: dict | None = None) -> dict:
    source_id = (source_id or "").strip()
    if not source_id:
        raise HTTPException(status_code=422, detail="sourceId is required")

    cache_key = f"playback::{SOURCE_QQMUSIC}::{source_id}"
    cached = PLAYBACK_INFO_CACHE.get(cache_key)
    if cached is not CACHE_MISS:
        if isinstance(cached, dict) and cached.get("__error__"):
            raise QQMusicResolveError(
                str(cached.get("reason") or QQMUSIC_FAILURE_UNKNOWN),
                str(cached.get("detail") or ""),
                list(cached.get("attempts") or []),
            )
        if cached:
            return dict(cached)
        raise QQMusicResolveError(QQMUSIC_FAILURE_EMPTY_PURL, "missing playable QQ Music stream URL")

    entry = candidate if candidate and candidate.get("sourceId") == source_id else None
    if not entry:
        entry = fetch_qqmusic_track_detail(source_id)
    if not entry:
        attempts = [
            qqmusic_attempt_payload(
                source_id=source_id,
                title="",
                artist="",
                reason=QQMUSIC_FAILURE_TRACK_DETAIL,
                message=qqmusic_failure_label(QQMUSIC_FAILURE_TRACK_DETAIL),
            )
        ]
        PLAYBACK_INFO_CACHE.set(
            cache_key,
            {"__error__": True, "reason": QQMUSIC_FAILURE_TRACK_DETAIL, "detail": "missing QQ Music track detail", "attempts": attempts},
            PLAYBACK_INFO_NEGATIVE_CACHE_TTL_SECONDS,
        )
        raise QQMusicResolveError(QQMUSIC_FAILURE_TRACK_DETAIL, "missing QQ Music track detail", attempts)

    media_mid = str(entry.get("qqMediaMid") or source_id).strip()
    title = str(entry.get("title") or "").strip()
    artist = str(entry.get("uploader") or entry.get("channel") or "").strip()
    attempts: list[dict[str, Any]] = []
    for prefix, extension, _size_key in qqmusic_file_candidates(entry):
        for refresh_attempt in range(2):
            try:
                vkey_info = fetch_qqmusic_vkey_info(source_id, media_mid, prefix, extension)
            except Exception as exc:
                attempts.append(
                    qqmusic_attempt_payload(
                        source_id=source_id,
                        title=title,
                        artist=artist,
                        prefix=prefix,
                        extension=extension,
                        reason=QQMUSIC_FAILURE_NETWORK,
                        message=exc.__class__.__name__,
                    )
                )
                break

            audio_url = str(vkey_info.get("url") or "")
            purl = str(vkey_info.get("purl") or "")
            if not audio_url:
                reason = str(vkey_info.get("reason") or QQMUSIC_FAILURE_EMPTY_PURL)
                attempts.append(
                    qqmusic_attempt_payload(
                        source_id=source_id,
                        title=title,
                        artist=artist,
                        prefix=prefix,
                        extension=extension,
                        reason=reason,
                        message=str(vkey_info.get("message") or qqmusic_failure_label(reason)),
                    )
                )
                break

            if is_qqmusic_preview_url(audio_url, purl):
                attempts.append(
                    qqmusic_attempt_payload(
                        source_id=source_id,
                        title=title,
                        artist=artist,
                        prefix=prefix,
                        extension=extension,
                        reason=QQMUSIC_FAILURE_PREVIEW_ONLY,
                        message=qqmusic_failure_label(QQMUSIC_FAILURE_PREVIEW_ONLY),
                    )
                )
                break

            probe_info = probe_playable_media_url_info(audio_url)
            if probe_info.get("ok"):
                payload = {
                    **entry,
                    "audioUrl": audio_url,
                    "audioExt": extension.lstrip("."),
                    "resolveAttempts": attempts,
                }
                PLAYBACK_INFO_CACHE.set(cache_key, payload, PLAYBACK_INFO_CACHE_TTL_SECONDS)
                return payload

            reason = str(probe_info.get("reason") or QQMUSIC_FAILURE_UNKNOWN)
            if reason == QQMUSIC_FAILURE_HTTP_403 and refresh_attempt == 0:
                attempts.append(
                    qqmusic_attempt_payload(
                        source_id=source_id,
                        title=title,
                        artist=artist,
                        prefix=prefix,
                        extension=extension,
                        reason=QQMUSIC_FAILURE_STALE_VKEY,
                        status_code=403,
                        message=qqmusic_failure_label(QQMUSIC_FAILURE_STALE_VKEY),
                    )
                )
                continue

            attempts.append(
                qqmusic_attempt_payload(
                    source_id=source_id,
                    title=title,
                    artist=artist,
                    prefix=prefix,
                    extension=extension,
                    reason=reason,
                    status_code=probe_info.get("statusCode"),
                    message=str(probe_info.get("error") or qqmusic_failure_label(reason)),
                )
            )
            break

    reason = dominant_qqmusic_failure(attempts)
    detail = qqmusic_failure_label(reason)
    PLAYBACK_INFO_CACHE.set(
        cache_key,
        {"__error__": True, "reason": reason, "detail": detail, "attempts": attempts},
        PLAYBACK_INFO_NEGATIVE_CACHE_TTL_SECONDS,
    )
    raise QQMusicResolveError(reason, detail, attempts)


def ytmusic_client() -> Any:
    global YTMUSIC_CLIENT
    if YTMusic is None:
        return None
    with YTMUSIC_CLIENT_LOCK:
        if YTMUSIC_CLIENT is None:
            preferred_language = normalize_ytmusic_language(NAS_SEARCH_LANGUAGE)
            mode = metadata_proxy_mode()
            init_attempts: list[dict[str, Any]] = []

            def append_language_attempts(language: str) -> None:
                if mode == "direct":
                    init_attempts.append({"language": language, "requests_session": get_http_session("ytmusic", "direct")})
                elif mode == "custom" and NAS_CUSTOM_PROXY_URL:
                    init_attempts.append({"language": language, "proxies": custom_proxy_mapping()})
                init_attempts.append({"language": language})

            append_language_attempts(preferred_language)
            if preferred_language != "en":
                append_language_attempts("en")
            init_attempts.append({})

            last_error: Exception | None = None
            for kwargs in init_attempts:
                try:
                    YTMUSIC_CLIENT = YTMusic(**kwargs)
                    break
                except TypeError:
                    continue
                except Exception as exc:
                    last_error = exc
                    continue

            if YTMUSIC_CLIENT is None and last_error:
                log_timing("ytmusic_client_fallback", preferred_language=preferred_language, mode=mode, error=last_error.__class__.__name__)
        return YTMUSIC_CLIENT


def search_youtube_data_api(query: str, limit: int) -> list[dict]:
    if not YOUTUBE_DATA_API_KEY:
        return []

    search_size = min(max(limit * 2, limit + 4), 15)
    started_ms = perf_counter_ms()
    payload = request_json(
        "https://www.googleapis.com/youtube/v3/search",
        params={
            "part": "snippet",
            "q": query,
            "type": "video",
            "maxResults": search_size,
            "videoEmbeddable": "true",
            "videoCategoryId": "10",
            "regionCode": NAS_SEARCH_REGION,
            "relevanceLanguage": NAS_SEARCH_LANGUAGE,
            "fields": "items(id/videoId,snippet(title,description,channelTitle,thumbnails))",
            "key": YOUTUBE_DATA_API_KEY,
        },
        timeout=10,
        kind="metadata",
    )
    items = payload.get("items") or []
    video_ids = [item.get("id", {}).get("videoId") for item in items if item.get("id", {}).get("videoId")]
    durations_by_id: dict[str, Optional[int]] = {}

    if video_ids:
        details_payload = request_json(
            "https://www.googleapis.com/youtube/v3/videos",
            params={
                "part": "contentDetails",
                "id": ",".join(video_ids),
                "fields": "items(id,contentDetails/duration)",
                "key": YOUTUBE_DATA_API_KEY,
            },
            timeout=10,
            kind="metadata",
        )
        for item in details_payload.get("items") or []:
            video_id = item.get("id")
            if video_id:
                durations_by_id[video_id] = parse_iso8601_duration((item.get("contentDetails") or {}).get("duration") or "")

    entries = []
    for item in items:
        snippet = item.get("snippet") or {}
        video_id = (item.get("id") or {}).get("videoId")
        if not video_id:
            continue
        entries.append(
            {
                "id": video_id,
                "title": snippet.get("title") or "Unknown Title",
                "uploader": snippet.get("channelTitle") or "Unknown Artist",
                "channel": snippet.get("channelTitle") or "Unknown Artist",
                "description": snippet.get("description") or "",
                "thumbnail": pick_thumbnail_url(snippet.get("thumbnails")),
                "duration": durations_by_id.get(video_id),
            }
        )

    log_timing("search_provider", provider="youtube_data_api", search_ms=int(perf_counter_ms() - started_ms), count=len(entries))
    return [normalize_catalog_entry(entry, "youtube_data_api") for entry in entries]


def search_ytmusicapi_entries(query: str, limit: int) -> list[dict]:
    client = ytmusic_client()
    if client is None:
        return []

    search_size = min(max(limit + 2, 6), 10)
    combined_entries: list[dict] = []
    seen_video_ids: set[str] = set()
    started_ms = perf_counter_ms()
    target_size = max(limit, 6)

    for search_filter in ("songs", "videos"):
        try:
            results = client.search(query, filter=search_filter, limit=search_size)
        except Exception as exc:
            log_timing("search_provider_failed", provider=f"ytmusicapi:{search_filter}", error=exc.__class__.__name__)
            continue

        for result in results or []:
            video_id = result.get("videoId")
            if not video_id or video_id in seen_video_ids:
                continue
            seen_video_ids.add(video_id)

            artists = result.get("artists") or []
            artist_names = []
            if isinstance(artists, list):
                for artist in artists:
                    if isinstance(artist, dict):
                        name = str(artist.get("name") or "").strip()
                        if name and not looks_like_metric_label(name):
                            artist_names.append(name)
                    elif artist:
                        name = str(artist).strip()
                        if name and not looks_like_metric_label(name):
                            artist_names.append(name)
            artist = ", ".join(artist_names) or result.get("author") or result.get("byline") or result.get("subtitle") or "Unknown Artist"
            combined_entries.append(
                {
                    "id": video_id,
                    "title": result.get("title") or "Unknown Title",
                    "uploader": artist,
                    "channel": result.get("author") or artist,
                    "description": " ".join(str(part) for part in [result.get("category"), result.get("resultType")] if part),
                    "thumbnail": pick_thumbnail_url(result.get("thumbnails")),
                    "duration": normalize_duration_seconds(result.get("duration_seconds")) or parse_duration_text(result.get("duration")),
                }
            )
            if len(combined_entries) >= target_size:
                break

        if len(combined_entries) >= target_size:
            break

    log_timing("search_provider", provider="ytmusicapi", search_ms=int(perf_counter_ms() - started_ms), count=len(combined_entries))
    return [normalize_catalog_entry(entry, "ytmusicapi") for entry in combined_entries]


def search_youtube_entries_legacy(query: str, limit: int) -> list[dict]:
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        return []

    search_size = min(max(limit * 2, limit + 4), 30)
    started_ms = perf_counter_ms()
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
    log_timing("search_provider", provider="legacy_ytdlp", search_ms=int(perf_counter_ms() - started_ms), count=len(ranked_entries))
    return [normalize_catalog_entry(entry, "legacy_ytdlp") for entry in ranked_entries[:limit]]


def search_entries_with_provider(query: str, limit: int, provider: str, *, allow_network: bool = True) -> list[dict]:
    cache_key = build_search_cache_key(query, limit, provider)
    cached = SEARCH_RESULTS_CACHE.get(cache_key)
    if cached is not CACHE_MISS:
        return list(cached)
    if not allow_network:
        return []

    try:
        if provider == "youtube_data_api":
            results = search_youtube_data_api(query, limit)
        elif provider == "ytmusicapi":
            results = search_ytmusicapi_entries(query, limit)
        else:
            results = search_youtube_entries_legacy(query, limit)
    except Exception as exc:
        log_timing("search_provider_failed", provider=provider, error=exc.__class__.__name__)
        results = []

    ttl = SEARCH_CACHE_TTL_SECONDS if results else SEARCH_NEGATIVE_CACHE_TTL_SECONDS
    SEARCH_RESULTS_CACHE.set(cache_key, results, ttl)
    return results


def search_youtube_entries(query: str, limit: int, *, allow_network: bool = True) -> list[dict]:
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        return []

    for provider in youtube_search_provider_order():
        results = search_entries_with_provider(normalized_query, limit, provider, allow_network=allow_network)
        if results:
            return results[:limit]
    return []


def search_entries_with_source(query: str, limit: int, source: str, *, allow_network: bool = True) -> list[dict]:
    normalized_source = normalize_source(source) or SOURCE_QQMUSIC
    cache_key = build_search_cache_key(query, limit, normalized_source)
    cached = SEARCH_RESULTS_CACHE.get(cache_key)
    if cached is not CACHE_MISS:
        return list(cached)
    if not allow_network:
        return []

    try:
        if normalized_source == SOURCE_YOUTUBE:
            results = search_youtube_entries(query, limit, allow_network=allow_network)
        else:
            results = search_qqmusic_entries(query, limit)
    except Exception as exc:
        log_timing("search_provider_failed", provider=normalized_source, error=exc.__class__.__name__)
        results = []

    ttl = SEARCH_CACHE_TTL_SECONDS if results else SEARCH_NEGATIVE_CACHE_TTL_SECONDS
    SEARCH_RESULTS_CACHE.set(cache_key, results, ttl)
    return results


def search_catalog_entries(query: str, limit: int, *, allow_network: bool = True) -> list[dict]:
    normalized_query = " ".join((query or "").split())
    if not normalized_query:
        return []
    for source in search_provider_order():
        results = search_entries_with_source(normalized_query, limit, source, allow_network=allow_network)
        if results:
            return results[:limit]
    return []


def build_search_response_payload(query: str, limit: int, source: str = "") -> dict:
    provider = None
    results: list[SearchItem] = []
    normalized_source = normalize_source(source)
    if normalized_source in {SOURCE_QQMUSIC, SOURCE_YOUTUBE}:
        entries = search_entries_with_source(query, limit, normalized_source)
    else:
        entries = search_catalog_entries(query, limit)
    for entry in entries:
        provider = provider or entry.get("source") or entry.get("provider")
        item = search_item_from_entry(entry)
        if item:
            results.append(item)
    return {"results": results, "provider": provider}


def build_visualize_error_payload(detail: str, status_code: int) -> dict:
    return {"__error__": True, "detail": detail, "statusCode": status_code}


def resolve_failure_reason(exc: Exception) -> str:
    if isinstance(exc, QQMusicResolveError):
        return exc.reason
    text = str(exc).lower()
    if "403" in text or "forbidden" in text:
        return QQMUSIC_FAILURE_HTTP_403
    if "network" in text or "timeout" in text:
        return QQMUSIC_FAILURE_NETWORK
    return QQMUSIC_FAILURE_UNKNOWN


def candidate_failure_payload(candidate: dict, exc: Exception) -> list[dict[str, Any]]:
    if isinstance(exc, QQMusicResolveError) and exc.attempts:
        return [dict(item) for item in exc.attempts]

    candidate_video_id = candidate.get("id") or ""
    candidate_source = normalize_source(candidate.get("source"), video_id=candidate_video_id, source_id=candidate.get("sourceId") or "")
    candidate_source_id = candidate.get("sourceId") or (candidate_video_id if candidate_source == SOURCE_YOUTUBE else "")
    reason = resolve_failure_reason(exc)
    return [
        {
            "source": candidate_source or "",
            "sourceId": candidate_source_id or "",
            "title": candidate.get("title") or "",
            "artist": candidate.get("uploader") or candidate.get("channel") or "",
            "reason": reason,
            "message": str(exc) or qqmusic_failure_label(reason),
            "statusCode": None,
        }
    ]


def cache_visualize_payload(query: str, video_id: str, payload: dict, ttl_seconds: int, *, source: str = "", source_id: str = "") -> None:
    resolved_source = source or payload.get("source") or ""
    resolved_source_id = source_id or payload.get("sourceId") or ""
    VISUALIZE_CACHE.set(
        build_visualize_cache_key(query=query, video_id=video_id, source=resolved_source, source_id=resolved_source_id),
        payload,
        ttl_seconds,
    )
    if resolved_source_id:
        VISUALIZE_CACHE.set(
            build_visualize_cache_key(source=resolved_source, source_id=resolved_source_id),
            payload,
            ttl_seconds,
        )
    if video_id:
        VISUALIZE_CACHE.set(build_visualize_cache_key(video_id=video_id, source=SOURCE_YOUTUBE), payload, ttl_seconds)


def build_visualize_response_payload(
    query: str = "",
    video_id: str = "",
    source: str = "",
    source_id: str = "",
    track_key: str = "",
    source_mode: str = "",
) -> dict:
    requested_source = normalize_source(source, video_id=video_id, source_id=source_id)
    forced_source = normalize_source(source_mode)
    requested_source_id = (source_id or "").strip()
    if not requested_source_id and requested_source == SOURCE_YOUTUBE and video_id:
        requested_source_id = video_id
    cache_key = build_visualize_cache_key(query=query, video_id=video_id, source=requested_source, source_id=requested_source_id)
    cached = VISUALIZE_CACHE.get(cache_key)
    if cached is not CACHE_MISS:
        if isinstance(cached, dict) and cached.get("__error__"):
            raise HTTPException(status_code=int(cached.get("statusCode") or 502), detail=cached.get("detail") or "Visualize failed")
        return dict(cached)

    request_label = requested_source_id or video_id or query or ""
    started_ms = perf_counter_ms()
    print(f"Visualizing: {request_label}")
    fallback_trace: list[dict[str, Any]] = []

    def resolve_candidate(candidate: dict) -> dict:
        candidate_video_id = candidate.get("id")
        candidate_source = normalize_source(candidate.get("source"), video_id=candidate_video_id or "", source_id=candidate.get("sourceId") or "")
        candidate_source_id = candidate.get("sourceId") or (candidate_video_id if candidate_source == SOURCE_YOUTUBE else "")
        if not candidate_source_id and not candidate_video_id:
            raise RuntimeError("missing source id")

        if candidate_source == SOURCE_QQMUSIC:
            media_data = resolve_qqmusic_entry(candidate_source_id, candidate)
            audio_url = media_data.get("audioUrl")
            title = media_data.get("title") or candidate.get("title") or "Unknown Title"
            artist = media_data.get("uploader") or media_data.get("channel") or candidate.get("uploader") or "Unknown Artist"
            cover_url = media_data.get("thumbnail") or candidate.get("thumbnail") or ""
            audio_ext = media_data.get("audioExt") or "m4a"
            provider = SOURCE_QQMUSIC
            resolved_video_id = ""
        else:
            resolved_video_id = candidate_video_id or candidate_source_id
            if not resolved_video_id:
                raise RuntimeError("missing video id")
            media_data = extract_playback_info(resolved_video_id)
            audio_format = select_preferred_audio_format(media_data)
            audio_url = audio_format.get("url") if audio_format else media_data.get("url")
            title = media_data.get("title") or candidate.get("title") or "Unknown Title"
            artist = media_data.get("uploader") or media_data.get("channel") or candidate.get("uploader") or "Unknown Artist"
            cover_url = media_data.get("thumbnail") or candidate.get("thumbnail") or ""
            audio_ext = (
                (audio_format or {}).get("audio_ext")
                or (audio_format or {}).get("ext")
                or "m4a"
            )
            if audio_ext == "none":
                audio_ext = (audio_format or {}).get("ext") or "m4a"
            provider = candidate.get("provider") or SOURCE_YOUTUBE
            candidate_source = SOURCE_YOUTUBE
            candidate_source_id = resolved_video_id

        if not audio_url:
            raise RuntimeError("missing playable stream URL")
        query_text = query or f"{title} {artist}".strip()
        extracted_colors = get_cached_cover_colors(cover_url) or warm_cover_colors(cover_url)
        theme = analyze_theme(title, extracted_colors)
        proxy_endpoint = f"/proxy-stream?url={quote(audio_url, safe='')}"
        stream_mode = "proxy" if NAS_MEDIA_TRANSPORT == "proxy" else "direct"
        primary_audio_src = proxy_endpoint if stream_mode == "proxy" else audio_url
        resolved_track_key = candidate.get("trackKey") or track_key or make_track_key(candidate_source, candidate_source_id, title, artist, resolved_video_id)

        return {
            "title": title,
            "artist": artist,
            "cover": cover_url,
            "audioSrc": primary_audio_src,
            "proxyAudioSrc": proxy_endpoint,
            "audioExt": audio_ext,
            "colors": extracted_colors,
            "theme": theme,
            "videoId": resolved_video_id if candidate_source == SOURCE_YOUTUBE else None,
            "query": query_text,
            "provider": provider,
            "streamMode": stream_mode,
            "source": candidate_source,
            "sourceId": candidate_source_id,
            "trackKey": resolved_track_key,
            "fallbackReason": "auto_fallback" if fallback_trace else "none",
            "fallbackTrace": list(fallback_trace),
        }

    last_error: Exception | None = None

    if requested_source_id or video_id:
        try:
            direct_candidate = {
                    "id": video_id,
                    "source": requested_source or (SOURCE_YOUTUBE if video_id else ""),
                    "sourceId": requested_source_id,
                    "trackKey": track_key,
            }
            payload = resolve_candidate(direct_candidate)
            cache_visualize_payload(query, payload.get("videoId") or "", payload, VISUALIZE_CACHE_TTL_SECONDS)
            log_timing(
                "visualize_resolved",
                resolve_ms=int(perf_counter_ms() - started_ms),
                stream_mode=payload.get("streamMode"),
                provider=payload.get("provider") or "video_lookup",
                fallback_reason="none",
            )
            return payload
        except Exception as exc:
            last_error = exc
            fallback_trace.extend(candidate_failure_payload(direct_candidate, exc))

    seen_identities: set[str] = set()
    if requested_source_id or video_id:
        seen_identities.add(make_track_key(requested_source, requested_source_id, video_id=video_id))
    if query:
        provider_sources = [forced_source] if forced_source in {SOURCE_QQMUSIC, SOURCE_YOUTUBE} else search_provider_order()
        for provider_source in provider_sources:
            for match in search_entries_with_source(query, 6, provider_source):
                match_source = normalize_source(match.get("source"), video_id=match.get("id") or "", source_id=match.get("sourceId") or "")
                match_source_id = match.get("sourceId") or (match.get("id") if match_source == SOURCE_YOUTUBE else "")
                identity = make_track_key(match_source, match_source_id, match.get("title") or "", match.get("uploader") or "", match.get("id"))
                if identity in seen_identities:
                    continue
                seen_identities.add(identity)
                try:
                    payload = resolve_candidate(match)
                    cache_visualize_payload(query, payload.get("videoId") or "", payload, VISUALIZE_CACHE_TTL_SECONDS)
                    log_timing(
                        "visualize_resolved",
                        resolve_ms=int(perf_counter_ms() - started_ms),
                        stream_mode=payload.get("streamMode"),
                        provider=payload.get("provider"),
                        fallback_reason="search_fallback",
                    )
                    return payload
                except Exception as exc:
                    last_error = exc
                    fallback_trace.extend(candidate_failure_payload(match, exc))
                    continue

    if last_error:
        error_payload = build_visualize_error_payload("Unable to resolve a playable stream", 502)
        VISUALIZE_CACHE.set(cache_key, error_payload, VISUALIZE_NEGATIVE_CACHE_TTL_SECONDS)
        raise HTTPException(status_code=502, detail="Unable to resolve a playable stream") from last_error

    error_payload = build_visualize_error_payload("Song not found", 404)
    VISUALIZE_CACHE.set(cache_key, error_payload, VISUALIZE_NEGATIVE_CACHE_TTL_SECONDS)
    raise HTTPException(status_code=404, detail="Song not found")


def fetch_lyrics_payload(
    track_name: str,
    artist_name: str = "",
    audio_duration: Optional[float] = None,
    video_id: str = "",
    source: str = "",
    source_id: str = "",
) -> dict:
    resolved_source = normalize_source(source, video_id=video_id, source_id=source_id)
    resolved_source_id = (source_id or "").strip()
    if not resolved_source_id and resolved_source == SOURCE_YOUTUBE and video_id:
        resolved_source_id = video_id
    cache_key = build_lyrics_cache_key(track_name, artist_name, audio_duration, video_id, resolved_source, resolved_source_id)
    cached = LYRICS_CACHE.get(cache_key)
    if cached is not CACHE_MISS:
        return dict(cached)

    clean_track, clean_artist = extract_track_and_artist(track_name, artist_name)
    target_duration = normalize_duration_seconds(audio_duration)
    target_lang = get_target_language(track_name, artist_name)
    best_plain_payload: dict | None = None

    def remember_plain_candidate(payload: dict | None) -> None:
        nonlocal best_plain_payload
        if not payload or payload.get("syncedLyrics") or not payload.get("plainLyrics"):
            return

        if best_plain_payload is None:
            best_plain_payload = payload
            return

        current_score = score_lyrics(
            best_plain_payload.get("syncedLyrics") or best_plain_payload.get("plainLyrics") or "",
            target_lang,
        )
        next_score = score_lyrics(
            payload.get("syncedLyrics") or payload.get("plainLyrics") or "",
            target_lang,
        )
        if next_score > current_score:
            best_plain_payload = payload

    if resolved_source == SOURCE_QQMUSIC and resolved_source_id:
        qqmusic_payload = fetch_qqmusic_lyrics(resolved_source_id)
        if qqmusic_payload:
            if qqmusic_payload.get("syncedLyrics"):
                LYRICS_CACHE.set(cache_key, qqmusic_payload, LYRICS_CACHE_TTL_SECONDS)
                return qqmusic_payload
            remember_plain_candidate(qqmusic_payload)

    if resolved_source == SOURCE_YOUTUBE and video_id:
        ytmusic_payload = fetch_ytmusic_lyrics(video_id)
        if ytmusic_payload:
            remember_plain_candidate(ytmusic_payload)

    url_get = f"https://lrclib.net/api/get?track_name={quote(clean_track)}&artist_name={quote(clean_artist)}"
    try:
        data = request_json(url_get, timeout=10, kind="metadata")
        if data and (data.get("syncedLyrics") or data.get("plainLyrics")):
            if target_duration is not None:
                exact_diff = duration_diff_seconds(data, target_duration)
                if exact_diff is not None and exact_diff > 2:
                    data = None
            if data:
                payload = {
                    "syncedLyrics": data.get("syncedLyrics"),
                    "plainLyrics": data.get("plainLyrics"),
                    "source": "lrclib",
                }
                if payload.get("syncedLyrics"):
                    LYRICS_CACHE.set(cache_key, payload, LYRICS_CACHE_TTL_SECONDS)
                    return payload
                remember_plain_candidate(payload)
    except Exception as exc:
        print(f"Exact match failed: {exc}")

    def is_valid_match(result_track: str, result_artist: str, target_track: str, target_artist: str) -> bool:
        if not target_track:
            return False

        track_sim = difflib.SequenceMatcher(None, target_track.lower(), (result_track or "").lower()).ratio()
        if track_sim > 0.8:
            return True
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

    def do_search(q: str, target_trk: str, target_art: str):
        try:
            results = request_json(f"https://lrclib.net/api/search?q={quote(q)}", timeout=10, kind="metadata")
            if results and isinstance(results, list):
                valid_results = [
                    res for res in results
                    if is_valid_match(res.get("trackName"), res.get("artistName"), target_trk, target_art)
                ]

                if not valid_results:
                    return None

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
                    }
        except Exception:
            pass
        return None

    fallback_queries: list[tuple[str, str, str]] = []
    seen_queries: set[str] = set()
    for fallback_query, target_track, target_artist in [
        (f"{clean_track} {clean_artist}".strip(), clean_track, clean_artist),
        (clean_track, clean_track, clean_artist),
        (clean_text_for_lyrics(track_name), clean_text_for_lyrics(track_name), artist_name),
    ]:
        normalized_fallback = normalize_cache_text(fallback_query)
        if not normalized_fallback or normalized_fallback in seen_queries:
            continue
        seen_queries.add(normalized_fallback)
        fallback_queries.append((fallback_query, target_track, target_artist))

    for fallback_query, target_track, target_artist in fallback_queries:
        result = do_search(fallback_query, target_track, target_artist)
        if result:
            if result.get("syncedLyrics"):
                LYRICS_CACHE.set(cache_key, result, LYRICS_CACHE_TTL_SECONDS)
                return result
            remember_plain_candidate(result)

    if resolved_source == SOURCE_YOUTUBE:
        youtube_caption_payload = fetch_youtube_captions(video_id, target_lang)
        if youtube_caption_payload:
            LYRICS_CACHE.set(cache_key, youtube_caption_payload, LYRICS_CACHE_TTL_SECONDS)
            return youtube_caption_payload

    if best_plain_payload:
        LYRICS_CACHE.set(cache_key, best_plain_payload, LYRICS_CACHE_TTL_SECONDS)
        return best_plain_payload

    empty_payload = {
        "syncedLyrics": None,
        "plainLyrics": None,
        "source": None,
    }
    LYRICS_CACHE.set(cache_key, empty_payload, LYRICS_NEGATIVE_CACHE_TTL_SECONDS)
    return empty_payload


def recommendation_item_identity(item: SearchItem) -> str:
    return item.trackKey or make_track_identity(item.videoId or None, item.title, item.artist, item.source, item.sourceId)


def personalized_recommendation_seeds(
    favorites: list[dict],
    history: list[dict],
    searches: list[dict],
) -> list[str]:
    artist_weights: Counter[str] = Counter()
    query_weights: Counter[str] = Counter()

    for index, item in enumerate(favorites[:12]):
        artist = (item.get("artist") or "").strip()
        query = (item.get("query") or "").strip()
        if artist:
            artist_weights[artist] += max(35, 120 - index * 8)
        if query and len(query.split()) >= 2:
            query_weights[query] += max(20, 70 - index * 5)

    for index, item in enumerate(history[:12]):
        artist = (item.get("artist") or "").strip()
        query = (item.get("query") or "").strip()
        if artist:
            artist_weights[artist] += max(20, 90 - index * 6)
        if query and len(query.split()) >= 2:
            query_weights[query] += max(10, 55 - index * 4)

    for index, item in enumerate(searches[:8]):
        query = (item.get("query") or "").strip()
        if query:
            query_weights[query] += max(15, 60 - index * 5)

    seeds: list[str] = []
    seen: set[str] = set()

    for artist, _weight in artist_weights.most_common(3):
        normalized = normalize_cache_text(artist)
        if normalized and normalized not in seen:
            seeds.append(artist)
            seen.add(normalized)

    for query, _weight in query_weights.most_common(4):
        normalized = normalize_cache_text(query)
        if normalized and normalized not in seen:
            seeds.append(query)
            seen.add(normalized)

    return seeds[:5]


def resolve_recommendation_seed_items(
    seed_queries: list[str],
    *,
    excluded_identities: set[str],
    limit: int,
) -> list[SearchItem]:
    normalized_seed_queries: list[str] = []
    seen_queries: set[str] = set()
    for seed_query in seed_queries[: max(limit, RECOMMENDATION_SEED_LIMIT)]:
        normalized_query = normalize_cache_text(seed_query)
        if not normalized_query or normalized_query in seen_queries:
            continue
        seen_queries.add(normalized_query)
        normalized_seed_queries.append(seed_query)

    if not normalized_seed_queries:
        return []

    max_workers = max(1, min(RECOMMENDATION_NETWORK_WORKERS, len(normalized_seed_queries)))
    collected_items: list[SearchItem] = []
    seen_identities = set(excluded_identities)

    def search_seed(query: str) -> list[dict]:
        try:
            return search_catalog_entries(
                query,
                RECOMMENDATION_SEARCH_RESULTS_PER_SEED,
                allow_network=True,
            )
        except Exception as exc:
            log_timing("recommendation_seed_failed", query=query, error=exc.__class__.__name__)
            return []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results_iter = executor.map(search_seed, normalized_seed_queries)

        for seed_query, entries in zip(normalized_seed_queries, results_iter):
            for entry in entries:
                candidate = search_item_from_entry(entry, fallback_query=seed_query)
                if not candidate:
                    continue
                identity = recommendation_item_identity(candidate)
                if identity in seen_identities:
                    continue
                seen_identities.add(identity)
                collected_items.append(candidate)
                if len(collected_items) >= limit:
                    return collected_items

    return collected_items


def curated_recommendation_items(excluded_identities: set[str]) -> list[SearchItem]:
    live_items = resolve_recommendation_seed_items(
        [seed["query"] for seed in CURATED_RECOMMENDATION_SEEDS],
        excluded_identities=excluded_identities,
        limit=RECOMMENDATIONS_MIN_ITEMS,
    )
    if live_items:
        return live_items

    items: list[SearchItem] = []
    for seed in CURATED_RECOMMENDATION_SEEDS[:RECOMMENDATIONS_MIN_ITEMS]:
        items.append(
            SearchItem(
                title=seed["title"],
                artist=seed["artist"],
                cover="",
                videoId="",
                query=seed["query"],
                duration=None,
                durationText=None,
            )
        )
    return items


def build_recommendations_payload() -> dict:
    cache_key = recommendation_cache_key()
    cached = RECOMMENDATIONS_CACHE.get(cache_key)
    if cached is not CACHE_MISS:
        return dict(cached)

    favorites = fetch_library_tracks("favorites", "saved_at", 30)
    history = fetch_library_tracks("play_history", "played_at", 30)
    searches = fetch_recent_searches(12)

    sections: list[RecommendationSection] = []
    excluded_identities = {
        make_track_identity(item.get("videoId"), item.get("title") or "", item.get("artist") or "", item.get("source"), item.get("sourceId"))
        for item in [*favorites, *history]
    }

    continue_listening: list[SearchItem] = []
    continue_seen: set[str] = set()
    for item in history:
        next_item = search_item_from_library_track(item)
        if not next_item:
            continue
        identity = recommendation_item_identity(next_item)
        if identity in continue_seen:
            continue
        continue_seen.add(identity)
        continue_listening.append(next_item)
        if len(continue_listening) >= RECOMMENDATIONS_MIN_ITEMS:
            break

    if continue_listening:
        sections.append(
            RecommendationSection(
                id="continue-listening",
                title="继续听",
                subtitle="从你最近播放的歌里继续进入状态",
                items=continue_listening,
                source="history",
            )
        )

    personalized_items = resolve_recommendation_seed_items(
        personalized_recommendation_seeds(favorites, history, searches),
        excluded_identities=excluded_identities.union(continue_seen),
        limit=RECOMMENDATIONS_MIN_ITEMS,
    )

    personalized_seen = {recommendation_item_identity(item) for item in personalized_items}
    if len(personalized_items) < RECOMMENDATIONS_MIN_ITEMS:
        for item in [*favorites, *history]:
            candidate = search_item_from_library_track(item)
            if not candidate:
                continue
            identity = recommendation_item_identity(candidate)
            if identity in personalized_seen or identity in continue_seen:
                continue
            personalized_seen.add(identity)
            personalized_items.append(candidate)
            if len(personalized_items) >= RECOMMENDATIONS_MIN_ITEMS:
                break

    if personalized_items:
        sections.append(
            RecommendationSection(
                id="for-you",
                title="为你推荐",
                subtitle="根据你的收藏、最近播放和搜索习惯实时生成",
                items=personalized_items,
                source="behavior",
            )
        )

    curated_items = curated_recommendation_items(excluded_identities.union(personalized_seen))
    sections.append(
        RecommendationSection(
            id="nas-curated",
            title="NAS 精选",
            subtitle="冷启动也能立即开始播放的固定精选",
            items=curated_items,
            source="curated",
        )
    )

    mode = "mixed" if personalized_items else "curated"
    payload = {
        "mode": mode,
        "generatedAt": utc_now_iso(),
        "sections": sections,
    }
    RECOMMENDATIONS_CACHE.set(cache_key, payload, RECOMMENDATIONS_CACHE_TTL_SECONDS)
    return payload


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


def frontend_index_response() -> FileResponse:
    return FileResponse(FRONTEND_INDEX, headers=FRONTEND_NO_CACHE_HEADERS)


def looks_like_static_asset_path(resource_path: str) -> bool:
    normalized = (resource_path or "").strip().lstrip("/")
    if not normalized:
        return False
    lowered = normalized.casefold()
    if any(lowered.startswith(prefix) for prefix in STATIC_ASSET_PREFIXES):
        return True
    return bool(Path(normalized).suffix)


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
    return {
        "status": "ok",
        "runtimeMode": "packaged" if IS_FROZEN else "source",
        "dataDir": str(DATA_DIR),
        "libraryDb": str(LIBRARY_DB),
    }


@app.get("/system-check")
async def system_check():
    return get_system_check()


@app.get("/app-settings", response_model=AppSettingsResponse)
async def get_app_settings():
    init_library_db()
    return get_app_settings_payload()


@app.post("/app-settings", response_model=AppSettingsResponse)
async def update_app_settings(item: AppSettingsUpdateRequest):
    init_library_db()
    requested_directory = (item.downloadDirectory or "").strip()
    resolved_directory = resolve_download_directory_path(requested_directory)
    set_app_setting(APP_SETTING_DOWNLOAD_DIRECTORY, str(resolved_directory))
    return get_app_settings_payload()


@app.post("/app-settings/open-download-directory")
async def open_download_directory():
    init_library_db()
    directory = resolve_download_directory_path()
    open_path_in_file_manager(directory)
    return {"ok": True, "path": str(directory)}


@app.get("/library", response_model=LibraryResponse)
async def get_library():
    return {
        "favorites": fetch_library_tracks("favorites", "saved_at", 100),
        "history": fetch_library_tracks("play_history", "played_at", 50),
        "recentSearches": fetch_recent_searches(12),
        "recentDownloads": fetch_recent_downloads(30),
    }


@app.get("/local-library", response_model=LocalLibraryResponse)
async def get_local_library():
    init_library_db()
    return build_local_library_payload()


@app.post("/diagnostics/frontend-error")
async def log_frontend_error(report: FrontendErrorReport):
    log_path = append_frontend_error_report(report)
    return {"ok": True, "path": str(log_path)}


@app.get("/diagnostics/search-network")
async def diagnostics_search_network():
    return await run_in_threadpool(build_search_diagnostics_payload)


@app.get("/recommendations", response_model=RecommendationsResponse)
async def get_recommendations():
    return await run_in_threadpool(build_recommendations_payload)


@app.post("/library/favorites", response_model=LibraryTrack)
async def upsert_favorite(item: LibraryTrack):
    payload = item.model_dump()
    saved_at = payload.get("savedAt") or utc_now_iso()
    source, source_id = legacy_source_fields(payload.get("source"), payload.get("sourceId"), payload.get("videoId"))
    track_key = stable_track_key(payload.get("key"), source, source_id, payload.get("videoId"), payload["title"], payload["artist"])

    with get_db_connection() as connection:
        delete_duplicate_source_rows(connection, "favorites", track_key, source, source_id, payload.get("videoId"))
        connection.execute(
            """
            INSERT INTO favorites (track_key, title, artist, cover, query, video_id, source, source_id, saved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_key) DO UPDATE SET
                title = excluded.title,
                artist = excluded.artist,
                cover = excluded.cover,
                query = excluded.query,
                video_id = excluded.video_id,
                source = excluded.source,
                source_id = excluded.source_id,
                saved_at = excluded.saved_at
            """,
            (
                track_key,
                payload["title"],
                payload["artist"],
                payload.get("cover") or "",
                payload.get("query") or "",
                payload.get("videoId"),
                source,
                source_id,
                saved_at,
            ),
        )

    payload["key"] = track_key
    payload["savedAt"] = saved_at
    payload["playedAt"] = None
    payload["source"] = source or None
    payload["sourceId"] = source_id or None
    return payload


@app.delete("/library/favorites")
async def delete_favorite(key: str):
    with get_db_connection() as connection:
        source, source_id = parse_stable_track_key(key)
        clauses = ["track_key = ?"]
        params: list[Any] = [key]
        if source and source_id:
            clauses.append("(source = ? AND source_id = ?)")
            params.extend([source, source_id])
            if source == SOURCE_YOUTUBE:
                clauses.append("video_id = ?")
                params.append(source_id)
                clauses.append("track_key = ?")
                params.append(f"vid:{source_id}")
        connection.execute(f"DELETE FROM favorites WHERE {' OR '.join(clauses)}", tuple(params))
    return {"ok": True, "key": key}


@app.post("/library/history", response_model=LibraryTrack)
async def upsert_history(item: LibraryTrack):
    payload = item.model_dump()
    played_at = payload.get("playedAt") or utc_now_iso()
    source, source_id = legacy_source_fields(payload.get("source"), payload.get("sourceId"), payload.get("videoId"))
    track_key = stable_track_key(payload.get("key"), source, source_id, payload.get("videoId"), payload["title"], payload["artist"])

    with get_db_connection() as connection:
        delete_duplicate_source_rows(connection, "play_history", track_key, source, source_id, payload.get("videoId"))
        connection.execute(
            """
            INSERT INTO play_history (track_key, title, artist, cover, query, video_id, source, source_id, played_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(track_key) DO UPDATE SET
                title = excluded.title,
                artist = excluded.artist,
                cover = excluded.cover,
                query = excluded.query,
                video_id = excluded.video_id,
                source = excluded.source,
                source_id = excluded.source_id,
                played_at = excluded.played_at
            """,
            (
                track_key,
                payload["title"],
                payload["artist"],
                payload.get("cover") or "",
                payload.get("query") or "",
                payload.get("videoId"),
                source,
                source_id,
                played_at,
            ),
        )

    payload["key"] = track_key
    payload["savedAt"] = None
    payload["playedAt"] = played_at
    payload["source"] = source or None
    payload["sourceId"] = source_id or None
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
    source, source_id = legacy_source_fields(item.source, item.sourceId, item.videoId)
    track_key = stable_track_key(item.key, source, source_id, item.videoId, item.title, item.artist)

    with get_db_connection() as connection:
        connection.execute(
            """
            INSERT INTO download_history (track_key, title, artist, filename, source_url, saved_path, cover, query, video_id, source, source_id, downloaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track_key,
                item.title,
                item.artist,
                item.filename,
                item.sourceUrl,
                item.savedPath,
                item.cover,
                item.query,
                item.videoId,
                source,
                source_id,
                downloaded_at,
            ),
        )

    return {
        "key": track_key,
        "title": item.title,
        "artist": item.artist,
        "filename": item.filename,
        "sourceUrl": item.sourceUrl,
        "savedPath": item.savedPath,
        "cover": item.cover,
        "query": item.query,
        "videoId": item.videoId,
        "source": source or None,
        "sourceId": source_id or None,
        "downloadedAt": downloaded_at,
    }


@app.post("/download-jobs", response_model=DownloadJobResponse)
async def create_desktop_download_job(item: DownloadJobCreateRequest):
    init_library_db()
    return create_download_job(item)


@app.get("/download-jobs/{job_id}", response_model=DownloadJobResponse)
async def get_download_job(job_id: str):
    return snapshot_download_job(job_id)


@app.post("/download-jobs/{job_id}/open-folder")
async def open_download_job_folder(job_id: str):
    job = snapshot_download_job(job_id)
    saved_path = str(job.get("savedPath") or "").strip()
    target_path = Path(saved_path).parent if saved_path else resolve_download_directory_path()
    open_path_in_file_manager(target_path)
    return {"ok": True, "path": str(target_path)}


@app.get("/lyrics-offset")
async def get_lyrics_offset(track_key: str = "", video_id: str = "", source: str = "", source_id: str = ""):
    resolved_source, resolved_source_id = legacy_source_fields(source, source_id, video_id)
    return {
        "trackKey": stable_track_key(track_key, resolved_source, resolved_source_id, video_id) or None,
        "videoId": video_id or None,
        "source": resolved_source or None,
        "sourceId": resolved_source_id or None,
        "offsetSeconds": fetch_saved_lyrics_offset(track_key=track_key, video_id=video_id, source=resolved_source, source_id=resolved_source_id),
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
    started_ms = perf_counter_ms()

    try:
        payload = await run_in_threadpool(build_search_response_payload, query, limit, req.source or "")
        log_timing(
            "search_completed",
            search_ms=int(perf_counter_ms() - started_ms),
            provider=payload.get("provider"),
            count=len(payload.get("results") or []),
        )
        return payload
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


def extract_ytmusic_browse_id(payload: Any) -> str | None:
    if isinstance(payload, str):
        return payload if payload.startswith("M") else None
    if isinstance(payload, dict):
        for key in ("lyricsBrowseId", "browseId", "lyrics"):
            candidate = payload.get(key)
            browse_id = extract_ytmusic_browse_id(candidate)
            if browse_id:
                return browse_id
        for value in payload.values():
            browse_id = extract_ytmusic_browse_id(value)
            if browse_id:
                return browse_id
    if isinstance(payload, list):
        for item in payload:
            browse_id = extract_ytmusic_browse_id(item)
            if browse_id:
                return browse_id
    return None


def decode_qqmusic_lyric(value: str) -> str:
    raw_value = (value or "").strip()
    if not raw_value:
        return ""
    try:
        return base64.b64decode(raw_value).decode("utf-8", errors="ignore")
    except Exception:
        return raw_value


def plain_text_from_lrc(value: str) -> str:
    lines = []
    for raw_line in (value or "").splitlines():
        cleaned = re.sub(r"\[[^\]]+\]", "", raw_line).strip()
        if cleaned:
            lines.append(cleaned)
    return "\n".join(lines)


def fetch_qqmusic_lyrics(source_id: str) -> dict | None:
    song_mid = (source_id or "").strip()
    if not song_mid:
        return None
    try:
        payload = request_qqmusic_api(
            qqmusic_request_item(
                "music.musichallSong.PlayLyricInfo",
                "GetPlayLyricInfo",
                {
                    "crypt": 0,
                    "lrc_t": 0,
                    "qrc": 0,
                    "qrc_t": 0,
                    "roma": 0,
                    "roma_t": 0,
                    "trans": 0,
                    "trans_t": 0,
                    "type": 1,
                    "songMid": song_mid,
                    "cv": 0,
                    "ct": 24,
                },
            ),
            timeout=10,
        )
    except Exception as exc:
        log_timing("qqmusic_lyrics_failed", error=exc.__class__.__name__)
        return None

    lyric_text = decode_qqmusic_lyric(str(payload.get("lyric") or ""))
    if not lyric_text.strip():
        return None
    has_timestamps = bool(re.search(r"\[\d{1,2}:\d{2}(?:\.\d{1,3})?\]", lyric_text))
    return {
        "syncedLyrics": lyric_text if has_timestamps else None,
        "plainLyrics": plain_text_from_lrc(lyric_text) if has_timestamps else lyric_text,
        "source": SOURCE_QQMUSIC,
    }


def fetch_ytmusic_lyrics(video_id: str) -> dict | None:
    client = ytmusic_client()
    if client is None or not video_id:
        return None

    try:
        try:
            watch_payload = client.get_watch_playlist(videoId=video_id, limit=1)
        except TypeError:
            watch_payload = client.get_watch_playlist(video_id, limit=1)
    except Exception as exc:
        log_timing("ytmusic_lyrics_failed", step="watch", error=exc.__class__.__name__)
        return None

    browse_id = extract_ytmusic_browse_id(watch_payload)
    if not browse_id:
        return None

    try:
        lyrics_payload = client.get_lyrics(browse_id)
    except Exception as exc:
        log_timing("ytmusic_lyrics_failed", step="lyrics", error=exc.__class__.__name__)
        return None

    if isinstance(lyrics_payload, dict):
        plain_lyrics = lyrics_payload.get("lyrics") or lyrics_payload.get("text")
        if isinstance(plain_lyrics, list):
            plain_lyrics = "\n".join(str(line) for line in plain_lyrics if line)
        if plain_lyrics:
            return {
                "syncedLyrics": None,
                "plainLyrics": str(plain_lyrics),
                "source": "ytmusicapi",
            }
    return None


def fetch_youtube_captions(video_id: str, target_lang: str) -> dict | None:
    if not video_id:
        return None

    try:
        info = extract_playback_info(video_id)
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
            ext = chosen.get("ext")
            if ext == "json3":
                parsed_entries = parse_json3_captions(request_json(chosen["url"], timeout=15, kind="metadata"))
            else:
                parsed_entries = parse_xml_captions(request_text(chosen["url"], timeout=15, kind="metadata"))

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
    source: str = "",
    source_id: str = "",
    track_key: str = "",
):
    if not track_name:
        raise HTTPException(status_code=422, detail="track_name is required")

    saved_offset = fetch_saved_lyrics_offset(track_key=track_key, video_id=video_id, source=source, source_id=source_id)

    try:
        payload = await run_in_threadpool(fetch_lyrics_payload, track_name, artist_name, audio_duration, video_id, source, source_id)
    except Exception as exc:
        print(f"Lyrics error: {exc}")
        payload = {
            "syncedLyrics": None,
            "plainLyrics": None,
            "source": None,
        }

    return {
        **payload,
        "offsetSeconds": saved_offset,
    }


@app.post("/visualize", response_model=VisualizeResponse)
async def visualize(req: VisualizeRequest):
    if not req.videoId and not req.sourceId and not req.query:
        raise HTTPException(status_code=422, detail="query, sourceId, or videoId is required")

    try:
        return await run_in_threadpool(
            build_visualize_response_payload,
            req.query or "",
            req.videoId or "",
            req.source or "",
            req.sourceId or "",
            req.trackKey or "",
            req.sourceMode or "",
        )
    except HTTPException:
        raise
    except Exception as exc:
        print(f"Visualize error: {exc}")
        raise HTTPException(status_code=500, detail="Visualize failed") from exc


@app.get("/proxy-stream")
async def proxy_stream(url: str, request: Request):
    try:
        started_ms = perf_counter_ms()
        print(f"Proxying stream: {url[:120]}")

        upstream_headers = media_request_headers(url)

        range_header = request.headers.get("range")
        if range_header:
            upstream_headers["Range"] = range_header

        upstream, transport_mode = request_media_response(url, headers=upstream_headers, timeout=25, stream=True)

        media_type = upstream.headers.get("content-type", "audio/mp4")
        response_headers = {}
        for header in ["content-length", "content-range", "cache-control", "expires", "accept-ranges"]:
            value = upstream.headers.get(header)
            if value:
                response_headers[header] = value

        if "accept-ranges" not in response_headers:
            response_headers["accept-ranges"] = "bytes"

        log_timing(
            "proxy_stream_opened",
            fetch_ms=int(perf_counter_ms() - started_ms),
            stream_mode=transport_mode,
            range="yes" if range_header else "no",
        )

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


@app.get("/local-media")
async def local_media(path: str):
    media_path = resolve_local_media_path(path)
    return FileResponse(
        media_path,
        media_type=guess_download_media_type(media_path.name, "application/octet-stream"),
        filename=media_path.name,
    )


@app.get("/download")
async def download_track(url: str, filename: str = "music.mp3"):
    try:
        started_ms = perf_counter_ms()
        print(f"Downloading stream: {url[:120]}")
        upstream, transport_mode = request_media_response(
            url,
            headers={"User-Agent": DEFAULT_HTTP_USER_AGENT},
            timeout=60,
            stream=True,
        )

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

        log_timing(
            "download_opened",
            fetch_ms=int(perf_counter_ms() - started_ms),
            stream_mode=transport_mode,
            filename=safe_filename,
        )

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
        return frontend_index_response()
    return HTMLResponse(setup_page(), status_code=503)


@app.get("/{resource_path:path}")
async def serve_frontend_resource(resource_path: str):
    if not resource_path:
        if frontend_is_built():
            return frontend_index_response()
        return HTMLResponse(setup_page(), status_code=503)

    file_path = get_dist_file(resource_path)
    if file_path:
        return FileResponse(file_path)

    if looks_like_static_asset_path(resource_path):
        raise HTTPException(status_code=404, detail="Static asset not found")

    if frontend_is_built():
        return frontend_index_response()

    return HTMLResponse(setup_page(), status_code=503)


def run_backend_server() -> None:
    ensure_runtime_directories()
    uvicorn.run(app, host=BACKEND_HOST, port=BACKEND_PORT, reload=False)


if __name__ == "__main__":
    run_backend_server()

