from __future__ import annotations

import os
import sys
from pathlib import Path

from app_meta import APP_ID

SOURCE_ROOT = Path(__file__).resolve().parent
IS_FROZEN = bool(getattr(sys, "frozen", False))
_BUNDLE_CANDIDATE = getattr(sys, "_MEIPASS", None)
BUNDLE_ROOT = Path(_BUNDLE_CANDIDATE).resolve() if _BUNDLE_CANDIDATE else (
    Path(sys.executable).resolve().parent if IS_FROZEN else SOURCE_ROOT
)


def _windows_local_appdata() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA")
    if local_appdata:
        return Path(local_appdata)
    return Path.home() / "AppData" / "Local"


def get_app_root() -> Path:
    if IS_FROZEN:
        return _windows_local_appdata() / APP_ID
    return SOURCE_ROOT


APP_ROOT = get_app_root()
DATA_DIR = APP_ROOT / "data"
WEBVIEW_STORAGE_DIR = DATA_DIR / "webview-storage"
ICON_CACHE_DIR = DATA_DIR / "desktop-assets"
UPDATE_CACHE_DIR = APP_ROOT / "updates"
FRONTEND_DIST = BUNDLE_ROOT / "frontend" / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"
LOCAL_FFMPEG_BINARY = BUNDLE_ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe"
LIBRARY_DB = DATA_DIR / "nas_local.db"
ASSETS_DIR = BUNDLE_ROOT / "assets"
APP_ICON_PNG = ASSETS_DIR / "app-icon.png"
APP_ICON_ICO = ASSETS_DIR / "app-icon.ico"
DESKTOP_ENTRYPOINT = SOURCE_ROOT / "desktop_app.py"


def ensure_runtime_directories() -> None:
    for path in (DATA_DIR, WEBVIEW_STORAGE_DIR, ICON_CACHE_DIR, UPDATE_CACHE_DIR):
        path.mkdir(parents=True, exist_ok=True)
