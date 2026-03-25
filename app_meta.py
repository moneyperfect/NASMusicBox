APP_ID = "NASMusicBox"
APP_NAME = "NAS Music Box"
APP_BRAND_NAME = "NAS音乐器"
APP_SHORT_NAME = "NAS"
APP_VERSION = "1.6.0"
APP_AUTHOR = "moneyperfect"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8010
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

GITHUB_OWNER = "moneyperfect"
GITHUB_REPO = "NASMusicBox"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

UPDATE_CHANNEL = "stable"


def display_version(value: str | None = None) -> str:
    normalized = (value or APP_VERSION or "").strip()
    parts = normalized.split(".")
    if len(parts) == 3 and parts[2] == "0" and parts[0].isdigit() and parts[1].isdigit():
        if len(parts[1]) == 1:
            return f"{int(parts[0])}.{parts[1]}0"
        return f"{int(parts[0])}.{parts[1]}"
    return normalized


APP_VERSION_LABEL = display_version()


def release_tag() -> str:
    return f"v{APP_VERSION}"
