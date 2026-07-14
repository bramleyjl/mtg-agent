"""
Merges manifest.json's placeholder server host_permission entry with the real
value from manifest.local.json (gitignored, never committed — see
manifest.local.json.example for the expected shape), then copies everything
into dist/ for Chrome's "Load unpacked" to point at.

manifest.json itself stays untouched in the working tree (still has the
literal YOUR_SERVER_IP placeholder) so there's no risk of accidentally
committing a real server address — only dist/ (already gitignored) ever
contains the real value.

Run: python build.py
Then: chrome://extensions -> Load unpacked -> chrome_extension/dist
"""

import json
import shutil
from pathlib import Path

EXT_DIR = Path(__file__).parent
DIST_DIR = EXT_DIR / "dist"
PLACEHOLDER = "http://YOUR_SERVER_IP:8765/*"


def main() -> None:
    local_path = EXT_DIR / "manifest.local.json"
    if not local_path.exists():
        raise SystemExit(
            f"Missing {local_path} — copy manifest.local.json.example to "
            "manifest.local.json and fill in your real server address first."
        )

    local = json.loads(local_path.read_text())
    real_permission = local["server_host_permission"]

    manifest = json.loads((EXT_DIR / "manifest.json").read_text())
    manifest["host_permissions"] = [
        real_permission if p == PLACEHOLDER else p for p in manifest["host_permissions"]
    ]

    if DIST_DIR.exists():
        shutil.rmtree(DIST_DIR)
    DIST_DIR.mkdir()

    for f in EXT_DIR.glob("*"):
        if f.name in ("build.py", "manifest.local.json", "manifest.local.json.example", "dist", "manifest.json"):
            continue
        if f.is_file():
            shutil.copy(f, DIST_DIR / f.name)

    (DIST_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {DIST_DIR} — load this directory as an unpacked extension.")


if __name__ == "__main__":
    main()
