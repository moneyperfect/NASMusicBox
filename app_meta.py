APP_ID = "NASMusicBox"
APP_NAME = "NAS Music Box"
APP_BRAND_NAME = "NAS音乐器"
APP_SHORT_NAME = "NAS"
APP_VERSION = "1.2.2"
APP_AUTHOR = "moneyperfect"

BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8010
BACKEND_URL = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

GITHUB_OWNER = "moneyperfect"
GITHUB_REPO = "NASMusicBox"
GITHUB_RELEASES_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases"
GITHUB_LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

UPDATE_CHANNEL = "stable"


def release_tag() -> str:
    return f"v{APP_VERSION}"
