"""Desktop window for FORGE 3.0."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import webview

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from forge3.web_api import Api  # noqa: E402


def resolve_shell(
    here: Path | None = None,
    meipass: str | Path | None = None,
) -> Path:
    """Locate index.html for source runs and the one-file extract.

    PyInstaller drops web_main.py at _MEIPASS and packs datas at forge3/web.
    Source keeps the shell next to this file at web/index.html.
    """
    here = Path(here) if here is not None else HERE
    if meipass is None and getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
    candidates: list[Path] = []
    if meipass:
        root = Path(meipass)
        candidates.append(root / "forge3" / "web" / "index.html")
        candidates.append(root / "web" / "index.html")
    candidates.append(here / "web" / "index.html")
    candidates.append(here / "forge3" / "web" / "index.html")
    for html in candidates:
        if html.is_file():
            return html
    tried = " ; ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"FORGE 3.0 shell not found. Tried: {tried}")


def main() -> int:
    html = resolve_shell()
    dev = "--dev" in sys.argv or os.getenv("FORGE3_DEBUG", "").lower() in {
        "1",
        "true",
        "yes",
    }
    api = Api()
    window = webview.create_window(
        title="FORGE 3.0",
        url=str(html),
        js_api=api,
        width=1180,
        height=780,
        fullscreen=False,
        min_size=(860, 560),
        background_color="#100E08",
        text_select=True,
        confirm_close=False,
    )
    api._bind_window(window)
    webview.start(debug=dev)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
