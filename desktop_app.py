from __future__ import annotations

import argparse
import atexit
import json
import os
import subprocess
import sys
import threading
import time
import ctypes
from pathlib import Path
from typing import Optional

import requests
import webview
from PIL import Image, ImageDraw
from pystray import Icon, Menu, MenuItem

try:
    import keyboard
except Exception:  # pragma: no cover - optional dependency at runtime
    keyboard = None

try:
    import winreg
except Exception:  # pragma: no cover - non-Windows fallback
    winreg = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
ICON_DIR = DATA_DIR / "desktop-assets"
BACKEND_URL = "http://127.0.0.1:8010"
HEALTH_URL = f"{BACKEND_URL}/health"
STARTUP_VALUE_NAME = "NASLocalDesktop"
DESKTOP_ENTRYPOINT = BASE_DIR / "desktop_app.py"


class DesktopApp:
    def __init__(self) -> None:
        self.backend_process: Optional[subprocess.Popen] = None
        self.owns_backend_process = False
        self.main_window = None
        self.mini_window = None
        self.tray_icon: Optional[Icon] = None
        self.hotkeys_registered = False
        self.quitting = False
        self.lock = threading.RLock()
        self.icon_image = self.create_icon_image()
        self.icon_png_path, self.icon_ico_path = self.write_icon_assets()

    @property
    def storage_path(self) -> str:
        path = DATA_DIR / "webview-storage"
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def create_icon_image(self, size: int = 256) -> Image.Image:
        image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image, "RGBA")
        padding = max(12, size // 18)
        radius = size // 4

        draw.rounded_rectangle(
            (padding, padding, size - padding, size - padding),
            radius=radius,
            fill=(7, 14, 26, 255),
            outline=(101, 193, 255, 130),
            width=max(3, size // 64),
        )

        glow_box = (size * 0.54, size * 0.08, size * 0.90, size * 0.44)
        draw.ellipse(glow_box, fill=(69, 220, 177, 175))
        draw.ellipse((size * 0.62, size * 0.16, size * 0.82, size * 0.36), fill=(255, 255, 255, 52))

        disc_box = (size * 0.12, size * 0.34, size * 0.78, size * 1.00)
        draw.ellipse(disc_box, fill=(13, 29, 52, 255), outline=(116, 204, 255, 145), width=max(3, size // 64))
        draw.ellipse((size * 0.23, size * 0.45, size * 0.67, size * 0.89), outline=(84, 167, 236, 110), width=max(3, size // 72))
        draw.ellipse((size * 0.34, size * 0.56, size * 0.56, size * 0.78), fill=(9, 18, 32, 255), outline=(191, 236, 255, 110), width=max(2, size // 96))

        bar_width = max(10, size // 20)
        bars = [
            (size * 0.58, size * 0.50, size * 0.58 + bar_width, size * 0.75),
            (size * 0.67, size * 0.42, size * 0.67 + bar_width, size * 0.79),
            (size * 0.76, size * 0.55, size * 0.76 + bar_width, size * 0.73),
        ]
        bar_colors = [(255, 255, 255, 235), (96, 211, 255, 240), (69, 220, 177, 240)]
        for box, color in zip(bars, bar_colors):
            draw.rounded_rectangle(box, radius=bar_width // 2, fill=color)

        draw.ellipse((size * 0.21, size * 0.43, size * 0.31, size * 0.53), fill=(255, 255, 255, 230))
        return image

    def write_icon_assets(self) -> tuple[str, str]:
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        png_path = ICON_DIR / "nas-app-icon.png"
        ico_path = ICON_DIR / "nas-app-icon.ico"
        self.icon_image.save(png_path, format="PNG")
        self.icon_image.save(
            ico_path,
            format="ICO",
            sizes=[(256, 256), (128, 128), (96, 96), (64, 64), (48, 48), (32, 32), (16, 16)],
        )
        return str(png_path), str(ico_path)

    def build_startup_command(self) -> str:
        python_exe = Path(sys.executable)
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
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NAS.Local.Desktop")
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
        ffmpeg_dir = BASE_DIR / "tools" / "ffmpeg" / "bin"
        if ffmpeg_dir.exists():
            env["PATH"] = f"{ffmpeg_dir}{os.pathsep}{env.get('PATH', '')}"

        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        self.backend_process = subprocess.Popen(
            [sys.executable, "main.py"],
            cwd=str(BASE_DIR),
            env=env,
            creationflags=creationflags,
            stdin=subprocess.DEVNULL,
        )
        self.owns_backend_process = True

        deadline = time.time() + 25
        last_error = None
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

    def create_mini_window(self) -> None:
        if self.mini_window is not None:
            return

        self.mini_window = webview.create_window(
            "NAS Mini Player",
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

    def create_tray_menu(self) -> Menu:
        return Menu(
            MenuItem("Show NAS", lambda icon, item: self.show_main_window(), default=True),
            MenuItem("Hide NAS", lambda icon, item: self.hide_main_window()),
            MenuItem(
                "Mini Player",
                lambda icon, item: self.toggle_mini_window(),
                checked=lambda item: self.mini_window_visible(),
            ),
            MenuItem("Play / Pause", lambda icon, item: self.dispatch_shell_action("toggle-play")),
            MenuItem("Previous", lambda icon, item: self.dispatch_shell_action("previous")),
            MenuItem("Next", lambda icon, item: self.dispatch_shell_action("next")),
            MenuItem("Toggle Vibe", lambda icon, item: self.dispatch_shell_action("toggle-vibe")),
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
            "nas_local",
            self.icon_image.resize((64, 64)),
            "NAS Local",
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

    def run(self) -> None:
        self.set_windows_app_id()
        self.start_backend()
        atexit.register(self.stop_backend)

        self.main_window = webview.create_window(
            "NAS Local",
            f"{BACKEND_URL}/",
            width=1440,
            height=900,
            min_size=(1100, 720),
            background_color="#08111d",
        )
        self.main_window.events.closed += lambda *_args: self.on_main_window_closed()

        webview.start(
            self.on_webview_ready,
            private_mode=False,
            storage_path=self.storage_path,
            icon=self.icon_ico_path,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch NAS Local desktop shell")
    parser.parse_args()

    app = DesktopApp()
    try:
        app.run()
        return 0
    except Exception as exc:
        print(f"[ERROR] {exc}")
        app.quit()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
