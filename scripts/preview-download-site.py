"""Preview the download website with the verified local release assets."""
from __future__ import annotations

import argparse
import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "website" / "dist"
RELEASE = ROOT / "dist" / "release"
ALLOWED_DOWNLOADS = {"NASMusicBox-Setup.exe", "NASMusicBox-portable.zip"}


class DownloadPreviewHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def send_head(self):
        path = urlsplit(self.path).path
        if path == "/release.json":
            release = json.loads((SITE / "release.json").read_text(encoding="utf-8"))
            manifest_path = RELEASE / "release-manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if manifest.get("version") == release.get("version"):
                    for kind in ("installer", "portable"):
                        release[kind].update(manifest[kind])
                    release["localDownloadsReady"] = all(
                        (RELEASE / Path(release[k]["path"]).name).is_file()
                        for k in ("installer", "portable")
                    )
            body = json.dumps(release, ensure_ascii=False).encode("utf-8")
            from io import BytesIO
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return BytesIO(body)
        if path.startswith("/downloads/"):
            name = path.removeprefix("/downloads/")
            if name not in ALLOWED_DOWNLOADS or not (RELEASE / name).is_file():
                self.send_error(404)
                return None
            file = (RELEASE / name).open("rb")
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str((RELEASE / name).stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.end_headers()
            return file
        return super().send_head()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5349)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), DownloadPreviewHandler)
    print(f"NAS download website: http://127.0.0.1:{args.port}", flush=True)
    server.serve_forever()
