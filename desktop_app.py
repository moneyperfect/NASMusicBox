from __future__ import annotations

import argparse
import atexit
import ctypes
import json
import os
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path
from typing import Optional

import requests
import webview
from pystray import Icon, Menu, MenuItem

from app_meta import APP_BRAND_NAME, APP_ID, APP_VERSION, BACKEND_URL, GITHUB_RELEASES_URL
from app_paths import (
    DESKTOP_ENTRYPOINT,
    ICON_CACHE_DIR,
    IS_FROZEN,
    LOCAL_FFMPEG_BINARY,
    UPDATE_CACHE_DIR,
    WEBVIEW_STORAGE_DIR,
    ensure_runtime_directories,
)
from desktop_assets import create_app_icon_image, write_icon_assets
from desktop_updater import ReleaseInfo, download_release_asset, fetch_latest_release, is_newer_version

try:
    import keyboard
except Exception:  # pragma: no cover - optional dependency at runtime
    keyboard = None

try:
    import winreg
except Exception:  # pragma: no cover - non-Windows fallback
    winreg = None


HEALTH_URL = f"{BACKEND_URL}/health"
STARTUP_VALUE_NAME = f"{APP_ID}Desktop"


class DesktopApp:
    def __init__(self, *, start_fullscreen: bool = False) -> None:
        ensure_runtime_directories()
        self.backend_process: Optional[subprocess.Popen] = None
        self.owns_backend_process = False
        self.main_window = None
        self.mini_window = None
        self.tray_icon: Optional[Icon] = None
        self.hotkeys_registered = False
        self.quitting = False
        self.lock = threading.RLock()
        self.update_lock = threading.RLock()
        self.icon_image = create_app_icon_image()
        self.icon_png_path, self.icon_ico_path = write_icon_assets(ICON_CACHE_DIR)
        self.available_release: ReleaseInfo | None = None
        self.update_error = ""
        self.update_check_in_progress = False
        self.update_download_in_progress = False
        self.start_fullscreen = start_fullscreen

    @property
    def storage_path(self) -> str:
        WEBVIEW_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
        return str(WEBVIEW_STORAGE_DIR)

    def build_startup_command(self) -> str:
        if IS_FROZEN:
            return f'"{Path(sys.executable).resolve()}"'

        python_exe = Path(sys.executable).resolve()
        pythonw_exe = python_exe.with_name("pythonw.exe")
        launcher = pythonw_exe if pythonw_exe.exists() else python_exe
        return f'"{launcher}" "{DESKTOP_ENTRYPOINT}"'

    def backend_is_healthy(self) -> bool:
        try:
            response = requests.get(HEALTH_URL, timeout=1)
        except Exception:
            return False
        return response.ok

    def set_windows_app_id(self) -> None:
        if os.name != "nt":
            return
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(f"{APP_ID}.Desktop")
        except Exception:
            pass

    def is_startup_enabled(self) -> bool:
        if winreg is None:
            return False

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Run",
            ) as key:
                value, _ = winreg.QueryValueEx(key, STARTUP_VALUE_NAME)
                return value == self.build_startup_command()
        except (FileNotFoundError, OSError):
            return False

    def set_startup_enabled(self, enabled: bool) -> None:
        if winreg is None:
            return

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Run",
            0,
            winreg.KEY_SET_VALUE,
        ) as key:
            if enabled:
                winreg.SetValueEx(
                    key,
                    STARTUP_VALUE_NAME,
                    0,
                    winreg.REG_SZ,
                    self.build_startup_command(),
                )
            else:
                try:
                    winreg.DeleteValue(key, STARTUP_VALUE_NAME)
                except FileNotFoundError:
                    pass

    def toggle_startup(self, *_args) -> None:
        self.set_startup_enabled(not self.is_startup_enabled())
        self.refresh_tray_menu()

    def refresh_tray_menu(self) -> None:
        if self.tray_icon:
            self.tray_icon.update_menu()

    def start_backend(self) -> None:
        if self.backend_is_healthy():
            return

        env = os.environ.copy()
        if LOCAL_FFMPEG_BINARY.exists():
            ffmpeg_dir = LOCAL_FFMPEG_BINARY.parent
            env["PATH"] = f"{ffmpeg_dir}{os.pathsep}{env.get('PATH', '')}"

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        if IS_FROZEN:
            command = [str(Path(sys.executable).resolve()), "--backend"]
        else:
            command = [str(Path(sys.executable).resolve()), str(DESKTOP_ENTRYPOINT), "--backend"]

        self.backend_process = subprocess.Popen(
            command,
            cwd=str(DESKTOP_ENTRYPOINT.parent),
            env=env,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
        )
        self.owns_backend_process = True

        deadline = time.time() + 25
        last_error: Exception | None = None
        while time.time() < deadline:
            if self.backend_process.poll() is not None:
                raise RuntimeError("Backend process exited before it became healthy.")

            try:
                response = requests.get(HEALTH_URL, timeout=1)
                if response.ok:
                    return
            except Exception as exc:  # pragma: no cover - timing-dependent
                last_error = exc
            time.sleep(0.4)

        raise RuntimeError(f"Backend did not become healthy in time: {last_error}")

    def stop_backend(self) -> None:
        if not self.owns_backend_process:
            self.backend_process = None
            return

        process = self.backend_process
        if not process:
            return

        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()

        self.backend_process = None
        self.owns_backend_process = False

    def register_hotkeys(self) -> None:
        if keyboard is None or self.hotkeys_registered:
            return

        try:
            keyboard.add_hotkey("ctrl+alt+space", lambda: self.dispatch_shell_action("toggle-play"))
            keyboard.add_hotkey("ctrl+alt+right", lambda: self.dispatch_shell_action("next"))
            keyboard.add_hotkey("ctrl+alt+left", lambda: self.dispatch_shell_action("previous"))
            keyboard.add_hotkey("ctrl+alt+up", lambda: self.dispatch_shell_action("volume-up"))
            keyboard.add_hotkey("ctrl+alt+down", lambda: self.dispatch_shell_action("volume-down"))
            keyboard.add_hotkey("ctrl+alt+m", lambda: self.toggle_mini_window())
            keyboard.add_hotkey("ctrl+alt+enter", lambda: self.toggle_main_fullscreen())
            self.hotkeys_registered = True
        except Exception:
            self.hotkeys_registered = False

    def unregister_hotkeys(self) -> None:
        if keyboard is None or not self.hotkeys_registered:
            return
        try:
            keyboard.unhook_all_hotkeys()
        finally:
            self.hotkeys_registered = False

    def dispatch_shell_action(self, action_type: str, payload: Optional[dict] = None) -> None:
        event_payload = {"type": action_type, "payload": payload or {}}
        script = (
            "window.dispatchEvent(new CustomEvent('nas-desktop-shell-action', "
            f"{{detail: {json.dumps(event_payload, ensure_ascii=False)}}}));"
        )

        with self.lock:
            windows = [window for window in (self.main_window, self.mini_window) if window is not None]

        for window in windows:
            try:
                window.evaluate_js(script)
            except Exception:
                continue

    def show_main_window(self, *_args) -> None:
        if not self.main_window:
            return
        try:
            self.main_window.show()
            self.main_window.restore()
        except Exception:
            pass

    def hide_main_window(self, *_args) -> None:
        if not self.main_window:
            return
        try:
            self.main_window.hide()
        except Exception:
            pass

    def main_window_is_fullscreen(self) -> bool:
        if not self.main_window:
            return False
        try:
            return self.main_window.state == "fullscreen"
        except Exception:
            return False

    def toggle_main_fullscreen(self, *_args) -> None:
        if not self.main_window:
            return
        try:
            self.main_window.toggle_fullscreen()
        except Exception:
            return
        self.refresh_tray_menu()

    def create_mini_window(self) -> None:
        if self.mini_window is not None:
            return

        self.mini_window = webview.create_window(
            f"{APP_BRAND_NAME} Mini Player",
            f"{BACKEND_URL}/?mini=1",
            width=420,
            height=220,
            min_size=(420, 220),
            resizable=False,
            on_top=True,
            hidden=True,
            focus=False,
            background_color="#08111d",
        )
        self.mini_window.events.closed += lambda *_args: self.on_mini_window_closed()

    def on_mini_window_closed(self) -> None:
        with self.lock:
            self.mini_window = None
        self.refresh_tray_menu()

    def mini_window_visible(self) -> bool:
        if not self.mini_window:
            return False
        try:
            return self.mini_window.state != "hidden"
        except Exception:
            return False

    def show_mini_window(self, *_args) -> None:
        with self.lock:
            if self.mini_window is None:
                self.create_mini_window()
            window = self.mini_window

        if window is None:
            return

        try:
            window.show()
            window.restore()
        except Exception:
            pass
        self.refresh_tray_menu()

    def hide_mini_window(self, *_args) -> None:
        if not self.mini_window:
            return
        try:
            self.mini_window.hide()
        except Exception:
            pass
        self.refresh_tray_menu()

    def toggle_mini_window(self, *_args) -> None:
        if self.mini_window_visible():
            self.hide_mini_window()
        else:
            self.show_mini_window()

    def update_status_label(self, _item=None) -> str:
        if self.update_download_in_progress:
            return "Updates: downloading..."
        if self.update_check_in_progress:
            return "Updates: checking..."
        if self.update_error:
            return "Updates: check failed"
        if self.available_release and is_newer_version(self.available_release.version, APP_VERSION):
            return f"Update ready: v{self.available_release.version}"
        return f"Updates: current v{APP_VERSION}"

    def download_update_label(self, _item=None) -> str:
        if self.update_download_in_progress:
            return "Downloading update..."
        asset = self.available_release.preferred_asset if self.available_release else None
        if asset:
            return f"Download {asset.name}"
        return "Download Latest Installer"

    def trigger_update_check(self, *_args, background: bool = False) -> None:
        with self.update_lock:
            if self.update_check_in_progress:
                return
            self.update_check_in_progress = True
            self.update_error = ""
        self.refresh_tray_menu()

        worker = threading.Thread(
            target=self._check_for_updates_worker,
            name="nas-update-check",
            kwargs={"background": background},
            daemon=True,
        )
        worker.start()

    def _check_for_updates_worker(self, *, background: bool = False) -> None:
        try:
            release = fetch_latest_release()
            if release and is_newer_version(release.version, APP_VERSION):
                self.available_release = release
            else:
                self.available_release = None
        except Exception as exc:
            self.available_release = None
            self.update_error = str(exc)
            if not background:
                print(f"[WARN] Update check failed: {exc}")
        finally:
            with self.update_lock:
                self.update_check_in_progress = False
            self.refresh_tray_menu()

    def open_releases_page(self, *_args) -> None:
        release_url = self.available_release.html_url if self.available_release else GITHUB_RELEASES_URL
        webbrowser.open(release_url)

    def download_latest_update(self, *_args) -> None:
        if not self.available_release:
            self.open_releases_page()
            return

        asset = self.available_release.preferred_asset
        if not asset or self.update_download_in_progress:
            self.open_releases_page()
            return

        self.update_download_in_progress = True
        self.refresh_tray_menu()
        worker = threading.Thread(target=self._download_update_worker, name="nas-update-download", daemon=True)
        worker.start()

    def _download_update_worker(self) -> None:
        try:
            if not self.available_release or not self.available_release.preferred_asset:
                return

            asset = self.available_release.preferred_asset
            downloaded_path = download_release_asset(asset, UPDATE_CACHE_DIR)
            if os.name == "nt":
                os.startfile(downloaded_path)  # type: ignore[attr-defined]
            else:  # pragma: no cover - desktop shell targets Windows first
                webbrowser.open(downloaded_path.as_uri())
        except Exception as exc:
            self.update_error = str(exc)
            print(f"[WARN] Update download failed: {exc}")
        finally:
            self.update_download_in_progress = False
            self.refresh_tray_menu()

    def create_tray_menu(self) -> Menu:
        return Menu(
            MenuItem("Show NAS", lambda icon, item: self.show_main_window(), default=True),
            MenuItem("Hide NAS", lambda icon, item: self.hide_main_window()),
            MenuItem(
                "Immersive Fullscreen",
                lambda icon, item: self.toggle_main_fullscreen(),
                checked=lambda item: self.main_window_is_fullscreen(),
            ),
            MenuItem(
                "Mini Player",
                lambda icon, item: self.toggle_mini_window(),
                checked=lambda item: self.mini_window_visible(),
            ),
            MenuItem("Play / Pause", lambda icon, item: self.dispatch_shell_action("toggle-play")),
            MenuItem("Previous", lambda icon, item: self.dispatch_shell_action("previous")),
            MenuItem("Next", lambda icon, item: self.dispatch_shell_action("next")),
            MenuItem("Toggle Vibe", lambda icon, item: self.dispatch_shell_action("toggle-vibe")),
            MenuItem(self.update_status_label, lambda icon, item: None, enabled=False),
            MenuItem("Check for Updates", lambda icon, item: self.trigger_update_check()),
            MenuItem(
                self.download_update_label,
                lambda icon, item: self.download_latest_update(),
                enabled=lambda item: self.available_release is not None and not self.update_download_in_progress,
            ),
            MenuItem("Open Releases Page", lambda icon, item: self.open_releases_page()),
            MenuItem(
                "Launch at Login",
                lambda icon, item: self.toggle_startup(),
                checked=lambda item: self.is_startup_enabled(),
            ),
            MenuItem("Quit NAS", lambda icon, item: self.quit()),
        )

    def start_tray(self) -> None:
        if self.tray_icon is not None:
            return

        self.tray_icon = Icon(
            APP_ID,
            self.icon_image.resize((64, 64)),
            APP_BRAND_NAME,
            self.create_tray_menu(),
        )
        self.tray_icon.run_detached()

    def stop_tray(self) -> None:
        if not self.tray_icon:
            return
        try:
            self.tray_icon.stop()
        finally:
            self.tray_icon = None

    def quit(self, *_args) -> None:
        if self.quitting:
            return
        self.quitting = True

        self.unregister_hotkeys()
        self.stop_tray()

        for window in [self.mini_window, self.main_window]:
            if window is None:
                continue
            try:
                window.destroy()
            except Exception:
                continue

        self.stop_backend()

    def on_main_window_closed(self) -> None:
        self.quit()

    def on_webview_ready(self) -> None:
        self.start_tray()
        self.register_hotkeys()
        self.trigger_update_check(background=True)

    def run(self) -> None:
        self.set_windows_app_id()
        self.start_backend()
        atexit.register(self.stop_backend)

        self.main_window = webview.create_window(
            APP_BRAND_NAME,
            f"{BACKEND_URL}/",
            width=1440,
            height=900,
            min_size=(1100, 720),
            fullscreen=self.start_fullscreen,
            background_color="#08111d",
        )
        self.main_window.events.closed += lambda *_args: self.on_main_window_closed()

        webview.start(
            self.on_webview_ready,
            private_mode=False,
            storage_path=self.storage_path,
            icon=self.icon_ico_path,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=f"Launch {APP_BRAND_NAME} desktop shell")
    parser.add_argument("--backend", action="store_true", help="Run the bundled FastAPI backend only")
    parser.add_argument("--fullscreen", action="store_true", help="Launch the desktop shell in immersive fullscreen")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.backend:
        from main import run_backend_server

        run_backend_server()
        return 0

    app = DesktopApp(start_fullscreen=args.fullscreen)
    try:
        app.run()
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        app.quit()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
