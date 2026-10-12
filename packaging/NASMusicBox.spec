# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct,
    VarFileInfo, VarStruct,
)
import sys

project_root = Path(SPECPATH).resolve().parent
sys.path.insert(0, str(project_root))
from app_meta import APP_VERSION, APP_BRAND_NAME
version_tuple = tuple(int(part) for part in APP_VERSION.split(".")) + (0,)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_tuple, prodvers=version_tuple,
                      mask=0x3f, flags=0, OS=0x40004, fileType=1, subtype=0, date=(0, 0)),
    kids=[StringFileInfo([StringTable("080404b0", [
        StringStruct("FileDescription", APP_BRAND_NAME),
        StringStruct("ProductName", APP_BRAND_NAME),
        StringStruct("FileVersion", APP_VERSION),
        StringStruct("ProductVersion", APP_VERSION),
        StringStruct("OriginalFilename", "NASMusicBox.exe"),
    ])]), VarFileInfo([VarStruct("Translation", [0x0804, 1200])])],
)

datas = [
    (str(project_root / "frontend" / "dist"), "frontend/dist"),
    (str(project_root / "assets"), "assets"),
]

ffmpeg_root = project_root / "tools" / "ffmpeg"
if ffmpeg_root.exists():
    # ffplay is not used by this app; do not ship another 200 MB player.
    for name in ("ffmpeg.exe", "ffprobe.exe"):
        binary = ffmpeg_root / "bin" / name
        if binary.is_file():
            datas.append((str(binary), "tools/ffmpeg/bin"))
    if (ffmpeg_root / "LICENSE.txt").exists():
        datas.append((str(ffmpeg_root / "LICENSE.txt"), "tools/ffmpeg"))

node_root = project_root / "tools" / "node"
if node_root.is_dir():
    datas.append((str(node_root), "tools/node"))

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
    version=version_info,
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
