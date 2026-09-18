# -*- mode: python ; coding: utf-8 -*-
import sys

from PyInstaller.utils.hooks import collect_all, collect_submodules

# Dest must stay forge3/web — frozen web_main looks under _MEIPASS/forge3/web.
datas = [("forge3/web", "forge3/web")]
binaries = []
hiddenimports = collect_submodules("forge3.core") + [
    "forge3.cheap",
    "forge3.forge_session",
    "forge3.paths",
    "forge3.strength",
    "forge3.web_api",
]

for package in ("anthropic", "cryptography", "openai", "truststore", "webview"):
    package_data, package_binaries, package_hidden = collect_all(package)
    datas += package_data
    binaries += package_binaries
    hiddenimports += package_hidden

analysis = Analysis(
    ["forge3/web_main.py"],
    pathex=[".", "forge3"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["matplotlib", "tkinter"],
    noarchive=False,
    optimize=1,
)
archive = PYZ(analysis.pure)

executable = EXE(
    archive,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="Forge-3.0",
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
    icon="forge.ico" if sys.platform == "win32" else None,
)
