# -*- mode: python ; coding: utf-8 -*-
import sys
import sysconfig
from pathlib import Path

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

# Linux has no built-in pywebview renderer. Freeze the complete Qt backend;
# PyInstaller's PyQt6 hooks collect Qt plugins and QtWebEngine resources once
# these dynamically imported modules are visible to analysis.
if sys.platform.startswith("linux"):
    hiddenimports += collect_submodules("qtpy") + [
        "PyQt6.QtCore",
        "PyQt6.QtGui",
        "PyQt6.QtNetwork",
        "PyQt6.QtWebChannel",
        "PyQt6.QtWebEngineCore",
        "PyQt6.QtWebEngineWidgets",
        "PyQt6.QtWidgets",
        "webview.platforms.qt",
    ]
    # QtWebEngine loads EGL dynamically, so PyInstaller cannot infer these
    # system libraries from Python imports. Bundle the Linux loader pair beside
    # the executable; the bootloader adds its extraction directory to the
    # dynamic-linker search path before Qt imports.
    multiarch = sysconfig.get_config_var("MULTIARCH") or "x86_64-linux-gnu"
    library_roots = (
        Path("/usr/lib") / multiarch,
        Path("/lib") / multiarch,
        Path("/usr/lib64"),
        Path("/lib64"),
    )
    for library_name in ("libEGL.so.1", "libGLdispatch.so.0"):
        library = next(
            (root / library_name for root in library_roots if (root / library_name).is_file()),
            None,
        )
        if library is None:
            raise FileNotFoundError(f"Linux release dependency missing: {library_name}")
        binaries.append((str(library), "."))

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
    name="Forge-3.1",
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
