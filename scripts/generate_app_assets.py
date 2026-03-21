from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from desktop_assets import write_icon_assets


def main() -> int:
    assets_dir = PROJECT_ROOT / "assets"
    png_path, ico_path = write_icon_assets(assets_dir, prefer_bundled_assets=False)
    print(f"Generated assets:\n- {png_path}\n- {ico_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
