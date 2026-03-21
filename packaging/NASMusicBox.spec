# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project_root = Path(SPECPATH).resolve().parent

datas = [
    (str(project_root / "frontend" / "dist"), "frontend/dist"),
    (str(project_root / "assets"), "assets"),
]

ffmpeg_root = project_root / "tools" / "ffmpeg"
if ffmpeg_root.exists():
    datas.append((str(ffmpeg_root), "tools/ffmpeg"))

hiddenimports = sorted(
    set(
        collect_submodules("uvicorn")
        + ["webview.platforms.edgechromium", "webview.platforms.winforms", "pystray._win32", "PIL._tkinter_finder"]
    )
)

a = Analysis(
    [str(project_root / "desktop_app.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="NASMusicBox",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_root / "assets" / "app-icon.ico"),
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="NASMusicBox",
)
