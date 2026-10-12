"""Windows desktop process lifecycle, independent of the webview UI."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import sys
import threading


def configure_windowed_logs(data_dir: Path, *, backend: bool = False) -> Path:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / ("backend.log" if backend else "desktop.log")
    if sys.stdout is None or sys.stderr is None:
        if path.is_file() and path.stat().st_size > 4 * 1024 * 1024:
            path.replace(path.with_suffix(".previous.log"))
        stream = path.open("a", encoding="utf-8", buffering=1)
        if sys.stdout is None:
            sys.stdout = stream
        if sys.stderr is None:
            sys.stderr = stream
    return path


class DesktopInstance:
    """Named handles are released by Windows even after an unexpected exit."""
    def __init__(self, data_root: Path):
        self.name = "Local\\NASMusicBox." + hashlib.sha256(
            str(data_root.resolve()).casefold().encode("utf-8")
        ).hexdigest()[:20]
        self.mutex = self.event = None
        self.stop = threading.Event()
        self.listener = None
        self.api = None
        if os.name == "nt":
            self.api = ctypes.WinDLL("kernel32", use_last_error=True)
            self.api.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
            self.api.CreateMutexW.restype = wintypes.HANDLE
            self.api.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
            self.api.CreateEventW.restype = wintypes.HANDLE
            self.api.SetEvent.argtypes = [wintypes.HANDLE]
            self.api.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
            self.api.WaitForSingleObject.restype = wintypes.DWORD
            self.api.CloseHandle.argtypes = [wintypes.HANDLE]

    def acquire(self) -> bool:
        if self.api is None:
            return True
        self.mutex = self.api.CreateMutexW(None, False, self.name)
        error = ctypes.get_last_error()
        if not self.mutex:
            raise ctypes.WinError(error)
        self.event = self.api.CreateEventW(None, False, False, self.name + ".activate")
        if not self.event:
            raise ctypes.WinError(ctypes.get_last_error())
        if error == 183:
            self.api.SetEvent(self.event)
            return False
        return True

    def listen(self, activate):
        if self.api is None or self.listener is not None:
            return
        def wait():
            while not self.stop.is_set():
                if self.api.WaitForSingleObject(self.event, 500) == 0 and not self.stop.is_set():
                    activate()
        self.listener = threading.Thread(target=wait, name="desktop-activation", daemon=True)
        self.listener.start()

    def close(self):
        self.stop.set()
        if self.listener:
            self.api.SetEvent(self.event)
            self.listener.join(timeout=2)
        if self.api:
            for handle in (self.event, self.mutex):
                if handle:
                    self.api.CloseHandle(handle)
        self.event = self.mutex = None
